from __future__ import annotations

"""Downloading roster and staff pages: retries, polite pacing per site, an on-disk cache, and an
optional headless-browser fallback. Shared by every sport."""
import hashlib
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def current_season() -> int:
    from datetime import date
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


class _Retry(Retry):
    """Retry that honors a site's "come back in N seconds" (Retry-After) for at most 30 seconds.
    Without a cap, one site asking for an hour stalls that school, and the whole run waits on it."""
    MAX_WAIT = 30

    def get_retry_after(self, response):
        wait = super().get_retry_after(response)
        return None if wait is None else min(wait, self.MAX_WAIT)


class Fetcher:
    def __init__(self, cache_dir: Path, delay: float = 1.5, refresh: bool = False, timeout: int = 30):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.refresh = refresh
        self.timeout = timeout
        self._local = threading.local()
        self._host_lock = threading.Lock()
        self._last_hit: dict[str, float] = {}
        self._slow_sites: set[str] = set()

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            retry = _Retry(total=3, connect=1, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                          allowed_methods=("GET",), respect_retry_after_header=True)
            s.mount("https://", HTTPAdapter(max_retries=retry))
            s.mount("http://", HTTPAdapter(max_retries=retry))
            s.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
            self._local.session = s
        return s

    def _cache_path(self, url: str, rendered: bool) -> Path:
        host = urlparse(url).netloc.replace(":", "_")
        digest = hashlib.sha1(url.encode()).hexdigest()[:10]
        return self.cache_dir / f"{host}_{digest}{'_r' if rendered else ''}.html"

    def _pace(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._host_lock:
            wait = self._last_hit.get(host, 0) + self.delay - time.monotonic()
            self._last_hit[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str) -> tuple[int, str, str]:
        """Return (status, final_url, html). Cached responses come back with status 200."""
        path = self._cache_path(url, rendered=False)
        if path.exists() and not self.refresh:
            final = path.with_suffix(".url")
            return 200, final.read_text() if final.exists() else url, path.read_text(encoding="utf-8", errors="replace")
        self._skip_if_slow(url)
        self._pace(url)
        try:
            resp = self._download(url)
        except (TimeoutError, requests.exceptions.Timeout):
            self._mark_slow(url)
            raise
        if resp.status_code == 200 and resp.text:
            path.write_text(resp.text, encoding="utf-8")
            path.with_suffix(".url").write_text(resp.url)
        return resp.status_code, resp.url, resp.text

    RENDER_LIMIT = 45         # seconds for one whole browser load, start to finish
    DOWNLOAD_LIMIT = 90       # seconds for one whole page download, retries included

    # Sites that timed out once in this run. Their other addresses are skipped straight away, so a
    # site that never answers (Susquehanna) costs one time limit, not one per address and season.
    @staticmethod
    def _site(url: str) -> str:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    def _skip_if_slow(self, url: str) -> None:
        if self._site(url) in self._slow_sites:
            raise TimeoutError("site timed out earlier in this run; skipped")

    def _mark_slow(self, url: str) -> None:
        with self._host_lock:
            self._slow_sites.add(self._site(url))

    def _download(self, url: str) -> requests.Response:
        """session.get with a hard limit on the whole download.

        requests' timeout only limits each pause between pieces of a page, so a site that answers a
        trickle at a time (Susquehanna stalled a D3 run) can hold a school forever. The download runs
        in a background thread instead; past the limit the scraper gives up on it and moves on."""
        box: dict = {}

        def work():
            try:
                box["resp"] = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except BaseException as exc:   # handed to the waiting thread below
                box["exc"] = exc

        t = threading.Thread(target=work, daemon=True)   # daemon: a stuck download never blocks exit
        t.start()
        t.join(self.DOWNLOAD_LIMIT)
        if t.is_alive():
            raise TimeoutError(f"no complete answer in {self.DOWNLOAD_LIMIT}s")
        if "exc" in box:
            raise box["exc"]
        return box["resp"]

    def render(self, url: str, wait_ms: int = 4000) -> str:
        """Load the page in headless Chromium (Playwright) for JS-only sites.

        The browser runs in its own process with a hard time limit: a page or browser that hangs
        (one D2 site stalled a whole run) is killed and reported as an error instead."""
        path = self._cache_path(url, rendered=True)
        if path.exists() and not self.refresh:
            html = path.read_text(encoding="utf-8", errors="replace")
            if not is_bot_check(html):         # a check page saved by an older version: try again
                return html
            path.unlink(missing_ok=True)
        try:
            import playwright  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Playwright not installed: pip install playwright && playwright install chromium") from exc
        if self._site(url) in self._slow_sites:
            raise RuntimeError("browser gave up: site timed out earlier in this run")
        self._pace(url)
        tmp = path.with_name(path.name + ".part")
        args = [sys.executable, "-c", _RENDER_SCRIPT, url, str(tmp), USER_AGENT,
                str(self.timeout * 1000), str(wait_ms)]
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=self.RENDER_LIMIT)
        except subprocess.TimeoutExpired:   # subprocess.run kills the child (and its browser goes with it)
            tmp.unlink(missing_ok=True)
            self._mark_slow(url)
            raise RuntimeError(f"browser gave up after {self.RENDER_LIMIT}s")
        if done.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            last = (done.stderr or "").strip().splitlines()
            raise RuntimeError(last[-1][:200] if last else f"browser exited with code {done.returncode}")
        html = tmp.read_text(encoding="utf-8", errors="replace")
        if is_bot_check(html):
            # The site's "are you a robot" page, not the roster. Never cached, so a later run can
            # try again; never worked around: a site that keeps refusing is left out.
            tmp.unlink(missing_ok=True)
            raise RuntimeError("bot check not passed")
        tmp.replace(path)
        return html


_BOT_CHECK = ("awswaf.com", "AwsWafIntegration", "challenge-container", "cf-challenge", "Just a moment...",
              "verify you're not a robot", "verify you are human")


def is_bot_check(html: str) -> bool:
    """True for a bot-check page (Amazon WAF, Cloudflare) in place of the page asked for."""
    head = html[:20000]
    return len(html) < 60000 and any(m in head for m in _BOT_CHECK)


# Runs in a child process: python -c _RENDER_SCRIPT <url> <out file> <user agent> <goto ms> <wait ms>
_RENDER_SCRIPT = r"""
import sys
from playwright.sync_api import sync_playwright
url, out, ua, goto_ms, wait_ms = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        page = browser.new_page(user_agent=ua, ignore_https_errors=True)
        page.set_default_timeout(goto_ms)          # every step, not just the first load
        page.goto(url, wait_until="domcontentloaded", timeout=goto_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        # Some sites lazy-load the list; scroll to the bottom once. A script error on the page while
        # scrolling (Endicott) doesn't spoil what has already loaded, so it's ignored.
        try:
            page.evaluate("window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
            page.wait_for_timeout(1500)
        except Exception:
            pass
        html = page.content()
    finally:
        browser.close()
open(out, "w", encoding="utf-8").write(html)
"""
