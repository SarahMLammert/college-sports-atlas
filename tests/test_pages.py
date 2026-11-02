"""Open the website's pages in a real (headless) browser and fail on any error (Nov 1).

    python -m pytest tests/test_pages.py -q                      # football, softball and women's hockey
    PAGE_TEST_SPORTS=all python -m pytest tests/test_pages.py -q  # every sport that has map data

Needs Playwright's Chromium (python3 -m playwright install chromium, as for scrape_rosters.py --render);
without it these tests are skipped. The pages load d3 and the map outlines from cdnjs and jsDelivr, so
the computer needs to be online.

For each sport it opens the front page and the five shared pages (players-dotmap.html?sport=..., the
heatmap, transfers, and the two staff pages when the sport has staff data), waits until they finish
loading, and fails on a JavaScript error, an error in the console, or a missing local file. It also checks
that the page shows the sport's own title from docs/sports.js and that the front page has a disc for every
sport in it.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import re
import threading
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"
DEFAULT_SPORTS = ["football", "softball", "hockey-womens"]
PLAYER_PAGES = ["players-dotmap", "players-heatmap", "players-transfers"]
STAFF_PAGES = ["staff-moves", "staff-directory"]


def site_lists(docs: Path = DOCS) -> tuple[dict, list]:
    """SPORT_PAGES and SPORT_DISCS from docs/sports.js (build.py pages writes them as JSON)."""
    text = (docs / "sports.js").read_text(encoding="utf-8")
    pages = json.loads(re.search(r"window\.SPORT_PAGES = (\{.*?\n\});", text, re.S).group(1))
    discs = json.loads(re.search(r"window\.SPORT_DISCS = (\[.*?\n\]);", text, re.S).group(1))
    return pages, discs


def sports_to_check(docs: Path = DOCS) -> list[str]:
    built = [p.parent.name for p in sorted(docs.glob("*/map_data.json"))]
    want = os.environ.get("PAGE_TEST_SPORTS", "")
    if want == "all":
        return built
    names = [s.strip() for s in want.split(",") if s.strip()] or DEFAULT_SPORTS
    return [s for s in names if s in built]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(docs: Path):
    """A web server for docs/ on a free port, in a background thread. Returns (server, base URL)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(docs)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/"


def check_page(browser, url: str, route=None) -> tuple[list[str], object]:
    """Open url and wait for it to settle. Returns (problems, page); the caller closes the page. route: an optional
    Playwright route handler for the CDN and font requests, to serve them from local copies when offline."""
    page = browser.new_page()
    if route:
        page.route(re.compile(r"https://(cdn|fonts)"), route)
    problems = []
    page.on("pageerror", lambda e: problems.append(f"JavaScript error: {e}"))
    page.on("console", lambda m: problems.append(f"console error: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)
    page.on("requestfailed", lambda r: problems.append(f"failed to load: {r.url}"))
    page.goto(url, wait_until="networkidle", timeout=120_000)
    page.wait_for_timeout(500)          # the last drawing after the data arrives
    return problems, page


def run_checks(sports: list[str], docs: Path = DOCS, route=None) -> list[str]:
    """Every problem on the front page and the sports' pages, as 'page: problem'."""
    from playwright.sync_api import sync_playwright
    words, discs = site_lists(docs)
    server, base = serve(docs)
    out = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            problems, page = check_page(browser, base + "index.html", route)
            n = page.locator(".disc").count()
            if n != len(discs):
                problems.append(f"{n} discs on the page, {len(discs)} in sports.js")
            text = page.inner_text("body").lower()       # the names are in capitals on the page
            for d in discs:
                if d["name"].lower() not in text:
                    problems.append(f"{d['name']} isn't on the page")
            page.close()
            out += [f"index.html: {x}" for x in problems]
            for sport in sports:
                pages = PLAYER_PAGES + [s for s in STAFF_PAGES if (docs / sport / "staff_data.json").exists()] + ["school-influence"]
                for name in pages:
                    problems, page = check_page(browser, f"{base}{name}.html?sport={sport}", route)
                    want = (words[sport].get(name) or {}).get("title")
                    if want and page.title() != want:
                        problems.append(f"title is {page.title()!r}, not {want!r}")
                    if "index.html" in page.url:
                        problems.append("sent back to the front page (the sport isn't in sports.js)")
                    page.close()
                    out += [f"{name}.html?sport={sport}: {x}" for x in problems]
            browser.close()
    finally:
        server.shutdown()
    return out


def _browser_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


needs_browser = pytest.mark.skipif(not _browser_ok(), reason="Playwright's Chromium isn't installed "
                                   "(python3 -m playwright install chromium)")


@needs_browser
def test_pages_open_without_errors():
    sports = sports_to_check()
    if not sports:
        pytest.skip("no sport with map data in docs/")
    problems = run_checks(sports)
    assert not problems, "\n".join(problems)
