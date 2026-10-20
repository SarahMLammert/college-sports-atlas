from __future__ import annotations

"""Downloading roster and staff pages: retries, polite pacing per site, an on-disk cache, and an
optional headless-browser fallback. Shared by every sport."""
import hashlib
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

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            retry = Retry(total=3, connect=1, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
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
        self._pace(url)
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        if resp.status_code == 200 and resp.text:
            path.write_text(resp.text, encoding="utf-8")
            path.with_suffix(".url").write_text(resp.url)
        return resp.status_code, resp.url, resp.text

    def render(self, url: str, wait_ms: int = 4000) -> str:
        """Load the page in headless Chromium (Playwright) for JS-only sites."""
        path = self._cache_path(url, rendered=True)
        if path.exists() and not self.refresh:
            return path.read_text(encoding="utf-8", errors="replace")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright not installed: pip install playwright && playwright install chromium") from exc
        self._pace(url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(wait_ms)
                # Some sites lazy-load the list; scroll to the bottom once.
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)
                html = page.content()
            finally:
                browser.close()
        path.write_text(html, encoding="utf-8")
        return html
