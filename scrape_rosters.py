#!/usr/bin/env python3
"""Scrape FBS and FCS football rosters into CSV, for one season or many.

Examples
    python scrape_rosters.py                                   # current season, every school
    python scrape_rosters.py --seasons 2016-2019,2021-2026     # last 10 seasons, skipping 2020
    python scrape_rosters.py --seasons 2019 --only "Alabama,Clemson"
    python scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed --render
    python scrape_rosters.py --recombine                       # no downloads: re-clean saved seasons, rebuild the combined files

Outputs (in --out, default ./data)
    seasons/rosters_<season>.csv          every player that season, one row each
    reports/scrape_report_<season>.csv    per school: status, strategy, player counts, URL, errors
    rosters_all_seasons.csv       all requested seasons stacked (one row per player per season)
    players_unique.csv            one row per player per school, with first/last season on the roster
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import sys
import threading
import time
from itertools import zip_longest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =============================================================================
# Fetching: HTTP with retries, polite pacing, an on-disk cache, headless-browser fallback
# =============================================================================
# HTTP fetching with retries, polite pacing, an on-disk cache, and an optional headless-browser fallback.

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

ROSTER_PATHS = [
    "/sports/football/roster",
    "/sports/m-footbl/roster",
    "/sports/fball/roster",
    "/sports/fb/roster",
]


def current_season() -> int:
    from datetime import date
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


def _fill(template: str, season: int) -> str:
    return template.format(season=season, next_season=season + 1, next_yy=f"{(season + 1) % 100:02d}")


def candidate_urls(domain: str, override: str = "", season: int | None = None) -> list[str]:
    """Roster URLs to try, most likely first.

    ``season=None`` means the current roster page. For past seasons the list always has the same
    length and order for a given school, so the index of the URL that worked can be reused.
    ``roster_url`` overrides may contain {season}, {next_season} and {next_yy} (e.g. 2019-{next_yy} -> 2019-20).
    """
    urls: list[str] = []
    override = (override or "").strip()
    if override:
        if season is None:
            urls.append(_fill(override, current_season()))
        elif "{season}" in override:
            urls.append(_fill(override, season))
        else:  # plain URL: try the Sidearm and WMT archive conventions on it
            o, yy = override.rstrip("/"), f"{(season + 1) % 100:02d}"
            urls += [f"{o}/{season}", f"{o}/season/{season}/", f"{o}/{season}-{yy}", f"{o}/season/{season}-{yy}/"]
    base = f"https://{domain.strip().strip('/')}"
    for path in ROSTER_PATHS:
        path = path.rstrip("/")
        if season:
            yy = f"{(season + 1) % 100:02d}"
            urls.append(f"{base}{path}/{season}")                # Sidearm:  /roster/2019
            urls.append(f"{base}{path}/season/{season}/")        # WMT:      /roster/season/2019/
            urls.append(f"{base}{path}/{season}-{yy}")           # Sidearm:  /roster/2019-20 (Cornell, Ohio State)
            urls.append(f"{base}{path}/season/{season}-{yy}/")   # WMT:      /roster/season/2019-20/ (Notre Dame, Georgia Tech)
        else:
            urls.append(f"{base}{path}")
    if domain and not domain.startswith("www."):
        urls.append(f"https://www.{domain}/sports/football/roster" + (f"/{season}" if season else ""))
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


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


# =============================================================================
# Cleaning: hometowns, class years, heights, weights
# =============================================================================
# Clean up raw roster fields: hometowns, class years, heights, names.

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

# AP-style and other abbreviations seen on rosters -> USPS code.
_STATE_ALIASES = {
    "ala": "AL", "alas": "AK", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA",
    "colo": "CO", "col": "CO", "conn": "CT", "del": "DE", "d.c": "DC", "dc": "DC",
    "washington dc": "DC", "washington d.c": "DC", "fla": "FL", "flor": "FL", "ga": "GA",
    "ill": "IL", "ills": "IL", "ind": "IN", "kan": "KS", "kans": "KS", "ky": "KY", "la": "LA",
    "md": "MD", "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO",
    "mont": "MT", "neb": "NE", "nebr": "NE", "nev": "NV", "n.h": "NH", "nh": "NH",
    "n.j": "NJ", "nj": "NJ", "n.m": "NM", "n.mex": "NM", "nm": "NM", "n.y": "NY", "ny": "NY",
    "n.c": "NC", "nc": "NC", "n.d": "ND", "n.dak": "ND", "nd": "ND", "okla": "OK",
    "ore": "OR", "oreg": "OR", "pa": "PA", "penn": "PA", "penna": "PA", "r.i": "RI", "ri": "RI",
    "s.c": "SC", "sc": "SC", "s.d": "SD", "s.dak": "SD", "sd": "SD", "tenn": "TN",
    "tex": "TX", "vt": "VT", "va": "VA", "wash": "WA", "w.va": "WV", "w.v": "WV", "wva": "WV",
    "wv": "WV", "wis": "WI", "wisc": "WI", "wyo": "WY", "p.r": "PR", "pr": "PR",
    "puerto rico": "PR", "guam": "GU", "american samoa": "AS", "a.s": "AS",
    "u.s. virgin islands": "VI", "virgin islands": "VI", "saipan": "MP",
    # Hawaii: islands and spellings with the okina
    "hawai'i": "HI", "hawaii": "HI", "hi": "HI", "o'ahu": "HI", "oahu": "HI", "maui": "HI",
    "kaua'i": "HI", "kauai": "HI", "big island": "HI", "hawai'i island": "HI", "moloka'i": "HI",
    "lana'i": "HI", "molokai": "HI", "lanai": "HI",
    "ga": "GA", "geo": "GA", "tx": "TX", "texas": "TX", "fl": "FL", "ca": "CA",
    "ken": "KY", "w. va": "WV", "w. virginia": "WV", "hawai‘i": "HI", "hawaiʻi": "HI",
}
for _code, _name in US_STATES.items():
    _STATE_ALIASES[_name.lower()] = _code
    _STATE_ALIASES[_code.lower()] = _code

_COUNTRY_FIXES = {
    "aus": "Australia", "aust": "Australia", "australia": "Australia", "nz": "New Zealand",
    "new zealand": "New Zealand", "eng": "England", "england": "England", "uk": "United Kingdom",
    "can": "Canada", "canada": "Canada", "ger": "Germany", "germany": "Germany",
    "mex": "Mexico", "mexico": "Mexico", "nigeria": "Nigeria", "bahamas": "Bahamas",
    "the bahamas": "Bahamas", "jamaica": "Jamaica", "samoa": "Samoa", "tonga": "Tonga",
    "japan": "Japan", "france": "France", "ireland": "Ireland", "sweden": "Sweden",
    "netherlands": "Netherlands", "austria": "Austria", "brazil": "Brazil",
    "the netherlands": "Netherlands", "holland": "Netherlands", "united kingdom": "United Kingdom",
    "great britain": "United Kingdom", "scotland": "Scotland", "wales": "Wales",
    "northern ireland": "Northern Ireland", "au": "Australia", "western australia": "Australia",
    "south australia": "Australia", "new south wales": "Australia", "nsw": "Australia",
    "queensland": "Australia", "qld": "Australia", "victoria": "Australia", "tasmania": "Australia",
    "grand bahama": "Bahamas", "nassau": "Bahamas", "china": "China", "serbia": "Serbia",
    "hungary": "Hungary", "south korea": "South Korea", "korea": "South Korea", "greece": "Greece",
    "russia": "Russia", "egypt": "Egypt", "liberia": "Liberia", "syria": "Syria", "panama": "Panama",
    "venezuela": "Venezuela", "croatia": "Croatia", "gabon": "Gabon", "ghana": "Ghana",
    "cameroon": "Cameroon", "kenya": "Kenya", "senegal": "Senegal", "south africa": "South Africa",
    "italy": "Italy", "spain": "Spain", "denmark": "Denmark", "norway": "Norway", "finland": "Finland",
    "switzerland": "Switzerland", "belgium": "Belgium", "poland": "Poland", "ukraine": "Ukraine",
    "israel": "Israel", "haiti": "Haiti", "dominican republic": "Dominican Republic", "fiji": "Fiji",
    "democratic republic of the congo": "Democratic Republic of the Congo",
    "democratic republic of congo": "Democratic Republic of the Congo",
    "dr of the congo": "Democratic Republic of the Congo", "drc": "Democratic Republic of the Congo",
    "congo": "Congo", "czech republic": "Czech Republic", "czechia": "Czech Republic",
}
_CANADIAN_PROVINCES = {
    "ont": "ON", "ontario": "ON", "on": "ON", "que": "QC", "quebec": "QC", "qc": "QC",
    "b.c": "BC", "bc": "BC", "british columbia": "BC", "alta": "AB", "alberta": "AB", "ab": "AB",
    "man": "MB", "manitoba": "MB", "sask": "SK", "saskatchewan": "SK", "n.s": "NS",
    "nova scotia": "NS", "n.b": "NB", "new brunswick": "NB", "p.e.i": "PE", "newfoundland": "NL",
    "ontario, canada": "ON", "québec": "QC", "nfld": "NL",
}


def clean(text) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _key(part: str) -> str:
    part = clean(part).replace("’", "'").replace("‘", "'").replace("ʻ", "'").replace("`", "'")
    return part.lower().rstrip(".").strip()


_PLACEHOLDERS = {"hometown", "n/a", "na", "-", "--", "tbd", "none", "unknown", "/"}


def _lookup(table: dict, k: str) -> str:
    """Look a state/country token up as written, then with dots, spaces and stray symbols
    removed, so 'W. Va.', 'F.L.', 'P.A.', 'U.K.' and 'SC|' all match."""
    if k in table:
        return table[k]
    return table.get(re.sub(r"[^a-z]", "", k), "")


def split_hometown_highschool(value: str) -> tuple[str, str]:
    """'Atlanta, Ga. / Westlake HS' -> ('Atlanta, Ga.', 'Westlake HS')."""
    value = clean(value)
    if " / " in value:
        a, b = value.split(" / ", 1)
        return clean(a), clean(b)
    if "/" in value and value.count("/") == 1:
        a, b = value.split("/", 1)
        return clean(a), clean(b)
    return value, ""


def parse_hometown(raw: str) -> dict:
    """Return {'city','state','country'} from strings like 'Mobile, Ala.' or 'Sydney, Australia'."""
    raw = clean(raw).replace("’", "'").replace("‘", "'").replace("ʻ", "'")
    out = {"city": "", "state": "", "country": ""}
    if not raw or raw.lower().strip(" .") in _PLACEHOLDERS:
        return out
    raw = re.sub(r"^(hometown|home town)(\s*/\s*(last|high|previous) school)?\s*:?\s*", "", raw, flags=re.I)
    # Drop a school that shares the field: "Atlanta, Ga. / Westlake HS", "Houston, Texas - Lamar"
    raw = re.split(r"\s*/\s*|\s+[-\u2013\u2014]\s+", raw, maxsplit=1)[0].strip()
    if re.fullmatch(r"washington,?\s*d\.?\s*c\.?", raw, flags=re.I):
        return {"city": "Washington", "state": "DC", "country": "USA"}
    # Drop parenthetical notes: "Miami, Fla. (Central HS)", "Houston, Texas (Alief Taylor)"
    raw = re.sub(r"\s*\([^)]*\)?\s*$", "", raw).strip().rstrip(",")
    if not raw:
        return out
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:
        k = _key(parts[0])
        if _lookup(_STATE_ALIASES, k):  # just a state
            out.update(state=_lookup(_STATE_ALIASES, k), country="USA")
        elif _lookup(_COUNTRY_FIXES, k):
            out["country"] = _lookup(_COUNTRY_FIXES, k)
        else:
            out["city"] = parts[0]
        return out

    city, rest = parts[0].strip("'\" "), parts[1:]
    last = _key(rest[-1])
    # "Montreal, Quebec, Canada" -> keep the province
    if len(rest) >= 2 and last in ("canada", "can") and _key(rest[-2]) in _CANADIAN_PROVINCES:
        return {"city": city, "state": _CANADIAN_PROVINCES[_key(rest[-2])], "country": "Canada"}
    if last in ("usa", "u.s.a", "us", "u.s", "united states"):
        rest = rest[:-1] or rest
        last = _key(rest[-1])
    if _lookup(_STATE_ALIASES, last):
        out.update(city=city, state=_lookup(_STATE_ALIASES, last), country="USA")
    elif _lookup(_CANADIAN_PROVINCES, last):
        out.update(city=city, state=_lookup(_CANADIAN_PROVINCES, last), country="Canada")
    elif _lookup(_COUNTRY_FIXES, last):
        out.update(city=city, country=_lookup(_COUNTRY_FIXES, last))
    else:
        # Unknown trailing token: treat as a foreign country/region.
        out.update(city=city, country=clean(rest[-1]))
    return out


_RS = r"^(r|rs|red|redshirt|medical redshirt)?[\s\-.]*"
_CLASS_MAP = [
    (_RS + r"(fr|fy|first[\s\-]year)", "FR"),
    (_RS + r"so", "SO"),
    (_RS + r"jr|junior", "JR"),
    (_RS + r"sr|senior", "SR"),
    (r"^gr|grad|^5th|fifth|^6th|sixth|^7th|seventh|^gs|post[\s\-]?bacc", "GR"),
    (r"^1st|first", "FR"),
    (r"^2nd|second", "SO"),
    (r"^3rd|third", "JR"),
    (r"^4th|fourth", "SR"),
]


def normalize_class(value: str) -> str:
    v = clean(value).lower()
    if not v:
        return ""
    for pattern, code in _CLASS_MAP:
        if re.search(pattern, v):
            redshirt = re.match(r"^(r[\s\-.]|rs|red|redshirt|medical redshirt)", v)
            return ("R-" + code) if redshirt and code != "GR" else code
    return clean(value)


def format_height(feet=None, inches=None, raw: str = "") -> str:
    if feet not in (None, "", 0, "0"):
        try:  # a bad value here used to raise and throw away the whole roster
            return f"{int(float(feet))}-{int(float(inches or 0))}"
        except (TypeError, ValueError):
            pass
    raw = clean(raw)
    m = re.match(r"^(\d)\s*['\-’ ]\s*(\d{1,2})", raw)
    return f"{m.group(1)}-{int(m.group(2))}" if m else raw


def clean_weight(value) -> str:
    m = re.search(r"\d{2,3}", clean(value))
    return m.group(0) if m else ""


# =============================================================================
# Season check: which year an archive page is really showing
# =============================================================================
# Work out which season a roster page is showing, so archive URLs that silently fall back
# to the current roster are caught instead of being saved under the wrong year.

_YEAR = re.compile(r"\b(20[0-3]\d)(?:\s*[-–/]\s*(?:20)?(\d{2}))?\b")


def detect_season(html: str) -> int | None:
    soup = BeautifulSoup(html[:400_000], "lxml")
    candidates: list[str] = []
    if soup.title:  # .string is None when the title has child nodes; get_text() isn't
        candidates.append(soup.title.get_text(" "))
    for sel in ("select[name=season] option[selected]", "select option[selected]",
                "h1", "h2", "[class*=roster-title]", "[class*=season] [aria-selected=true]"):
        for el in soup.select(sel)[:3]:
            candidates.append(el.get_text(" "))
    for text in candidates:
        m = _YEAR.search(text or "")
        if m:
            return int(m.group(1))
    return None


# =============================================================================
# Parsing: pull players out of a roster page
# =============================================================================
# Roster page parsers.
#
# Each strategy takes raw HTML and returns a list of player dicts with these keys
# (any may be empty): name, first_name, last_name, jersey, position, class_year,
# height, weight, hometown, high_school, previous_school, bio_url.
#
# Strategies, tried in order by ``parse_roster``:
#   1. nuxt_data       - Nuxt 3 ``__NUXT_DATA__`` payload (Sidearm "nextgen" and WMT sites)
#   2. sidearm_classic - older Sidearm markup (li.sidearm-roster-player)
#   3. sidearm_cards   - Sidearm nextgen person cards (data-test-id attributes)
#   4. html_table      - any <table> whose header mentions Hometown
#   5. embedded_json   - any other <script> JSON blob (__NEXT_DATA__, ld+json, ...) with hometown keys

FIELDS = [
    "name", "first_name", "last_name", "jersey", "position", "class_year",
    "height", "weight", "hometown", "high_school", "previous_school", "bio_url",
]


def _blank() -> dict:
    return {f: "" for f in FIELDS}


# ---------------------------------------------------------------------------
# 1. Nuxt devalue payload
# ---------------------------------------------------------------------------

_WRAPPERS = {"ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}
_OPAQUE = {"Date", "Set", "Map", "RegExp", "BigInt", "Error", "NuxtError", "URL", "URLSearchParams"}


def decode_devalue(raw: list) -> Any:
    """Rehydrate a devalue-flattened array (the format Nuxt 3 uses for __NUXT_DATA__).

    Iterative rather than recursive: the old version raised the process-wide recursion limit,
    which raced between worker threads and could crash or silently drop a roster."""
    memo: dict[int, Any] = {}
    todo: list[tuple[Any, Any]] = []   # (empty container, source list/dict) still to fill

    def get(i):
        if not isinstance(i, int) or isinstance(i, bool):
            return i
        if i < 0 or i >= len(raw):  # -1 undefined, -2 hole, -3 NaN, ...
            return None
        if i in memo:
            return memo[i]
        j, hops = i, set()
        while True:  # unwrap Reactive/Ref/... chains
            v = raw[j]
            if isinstance(v, list) and v and isinstance(v[0], str) and v[0] in _WRAPPERS:
                nxt = v[1] if len(v) > 1 else -1
                if not isinstance(nxt, int) or nxt < 0 or nxt >= len(raw) or nxt in hops:
                    memo[i] = None
                    return None
                hops.add(j)
                j = nxt
                if j in memo:
                    memo[i] = memo[j]
                    return memo[j]
                continue
            break
        v = raw[j]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _OPAQUE:
                out = None
            else:
                out = []
                todo.append((out, v))
        elif isinstance(v, dict):
            out = {}
            todo.append((out, v))
        else:
            out = v
        memo[i] = memo[j] = out
        return out

    root = get(0)
    while todo:
        container, src = todo.pop()
        if isinstance(container, list):
            container.extend(get(x) for x in src)
        else:
            for k, x in src.items():
                container[k] = get(x)
    return root


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", k.lower())


def _text(v) -> str:
    """Flatten a JSON value to display text (dicts like {'abbreviation': 'QB', 'name': ...})."""
    if v is None:
        return ""
    if isinstance(v, dict):
        for k in ("abbreviation", "abbrev", "short", "shortName", "name", "title", "value", "text"):
            if v.get(k):
                return clean(v[k])
        return ""
    if isinstance(v, list):
        return ", ".join(t for t in (_text(x) for x in v) if t)
    return clean(v)


# Candidate JSON keys (already passed through _norm_key) for each output field, best first.
_KEYMAP = {
    "first_name": ["firstname", "first"],
    "last_name": ["lastname", "last"],
    "name": ["fullname", "displayname", "playername", "name"],
    "jersey": ["jerseynumber", "jerseynumberlabel", "jersey", "number", "uniformnumber", "no"],
    "position": ["positionshort", "playerposition", "positionabbreviation", "position", "pos",
                 "positionlong"],
    "class_year": ["academicyearshort", "academicyear", "classlevel", "academicyearlong",
                   "classyear", "class", "year", "eligibility", "yr"],
    "hometown": ["hometown", "homecity", "hometowncity"],
    "high_school": ["highschool", "hs", "highschoolname", "lastschool"],
    # "Last School" is a high school for freshmen and a college for transfers; sort_schools() decides which.
    "previous_school": ["previousschool", "previousschools", "previousschoolname", "prevschool", "priorschool",
                        "formerschool", "transferschool", "transferfrom", "transferredfrom", "previouscollege",
                        "lastcollege", "college"],
    "weight": ["weight", "wt"],
    "bio_url": ["calltoaction", "relativeurl", "url", "permalink", "biourl"],
}


# Fields a wrapper object may supply for the player it contains (WMT puts season-specific
# position/class/jersey on the roster entry and hometown etc. on the nested ``player``).
_PARENT_FIELDS = ("position", "class_year", "jersey", "bio_url")


def _pick(d: dict, field: str) -> str:
    for k in _KEYMAP[field]:
        if k in d:
            t = _text(d[k])
            if t:
                return t
    return ""


def _record_from_json(obj: dict, parent: dict | None = None) -> dict | None:
    d = {_norm_key(k): v for k, v in obj.items()}
    rec = _blank()
    for field in _KEYMAP:
        rec[field] = _pick(d, field)
    if parent:
        p = {_norm_key(k): v for k, v in parent.items()}
        for field in _PARENT_FIELDS:
            val = _pick(p, field)
            if val:
                rec[field] = val
        for field in ("high_school", "previous_school"):   # only to fill a blank: the player's own record wins
            if not rec[field]:
                rec[field] = _pick(p, field)

    rec["height"] = format_height(d.get("heightfeet"), d.get("heightinches"),
                                  _text(d.get("height") or d.get("heightdisplay") or ""))
    rec["weight"] = clean_weight(rec["weight"])

    if rec["first_name"] or rec["last_name"]:
        full = clean(f"{rec['first_name']} {rec['last_name']}")
        if not rec["name"]:
            rec["name"] = full
    if not rec["name"]:
        return None
    if rec["hometown"] and not rec["high_school"]:
        ht, hs = split_hometown_highschool(rec["hometown"])
        if hs:
            rec["hometown"], rec["high_school"] = ht, hs
    return rec


# ---------------------------------------------------------------------------
# Staff filter: coaches, managers, trainers and other support staff share the roster page (and
# often the same markup or JSON shape) with players. Every parser runs its results through this.
# ---------------------------------------------------------------------------

STAFF_WORDS = re.compile(
    r"\b(coach(es|ing)?|coordinator|manager|mgr|trainer|athletic training|director|analyst|"
    r"graduate assistant|grad assistant|quality control|intern|staff|operations|recruiting|"
    r"equipment|video|strength|conditioning|nutrition(ist)?|dietitian|chaplain|physician|doctor|"
    r"sports medicine|therapist|psycholog\w*|administrat\w*|advisor|consultant|"
    r"personnel|scouting|student assistant|assistant|support|team services|"
    r"chief of staff|general manager|gm|creative|social media|photographer|mascot)\b",
    re.I,
)
# Only checked against a record's position, class and job-title fields, never its name or school.
# Words that can describe players are left out: "Medical Redshirt" is a class, "Scout team" a note.
# JSON keys that hold a staff member's job title:
_STAFF_KEYS = {"title", "jobtitle", "stafftitle", "positiontitle", "role", "stafftype", "type"}


def staff_text_hit(*texts: str) -> bool:
    return any(t and STAFF_WORDS.search(t) for t in texts)


def is_staff(rec: dict) -> bool:
    """A scraped record whose position or class column holds a job title ("Head Coach",
    "Student Manager", "Director of Football Operations") is staff, not a player."""
    return staff_text_hit(rec.get("position", ""), rec.get("class_year", ""), rec.get("staff_title", ""))


def drop_staff(rows: list[dict]) -> list[dict]:
    rows = [r for r in rows if not is_staff(r)]
    # Players nearly always have a position or jersey number; staff almost never do. If most of
    # the page has them, a record with neither (and no class or size) is support staff.
    def has_player_fields(r):
        return any(r.get(f) for f in ("position", "jersey", "class_year", "height", "weight"))
    if rows and sum(1 for r in rows if r.get("position") or r.get("jersey")) >= 0.8 * len(rows):
        rows = [r for r in rows if has_player_fields(r)]
    return rows


_STAFF_SECTIONS = re.compile(r"coach|staff|manager|support|trainer|administration", re.I)


def _looks_like_player(d: dict) -> bool:
    keys = {_norm_key(k) for k in d}
    has_home = bool(keys & {"hometown", "homecity", "hometowncity"})
    has_name = bool(keys & {"firstname", "lastname", "fullname", "name", "displayname"})
    return has_home and has_name


def players_from_json_tree(root: Any) -> list[dict]:
    """Walk any decoded JSON tree, collecting player-like dicts (with their parent for context)."""
    out: list[dict] = []
    seen: set[int] = set()
    # (node, parent dict, key it was stored under). Anything under a key like "coaches",
    # "staff" or "support_staff" is skipped, whatever it looks like.
    stack: list[tuple[Any, dict | None, str]] = [(root, None, "")]
    while stack:
        node, parent, key = stack.pop()
        if _STAFF_SECTIONS.search(key):
            continue
        if isinstance(node, dict):
            if id(node) in seen:
                continue
            seen.add(id(node))
            if _looks_like_player(node):
                rec = _record_from_json(node, parent)
                if rec:
                    titles = [_text(v) for d in (node, parent or {}) for k, v in d.items()
                              if _norm_key(k) in _STAFF_KEYS and not isinstance(v, (dict, list))]
                    rec["staff_title"] = " / ".join(t for t in titles if t)
                    out.append(rec)
                continue
            for k, v in node.items():
                stack.append((v, node, str(k)))
        elif isinstance(node, list):
            if id(node) in seen:
                continue
            seen.add(id(node))
            for v in node:
                stack.append((v, None, key))
    out.reverse()  # stack order -> document order
    return out


def parse_nuxt_data(html: str, soup: BeautifulSoup) -> list[dict]:
    tag = soup.find("script", id="__NUXT_DATA__")
    if not tag or not tag.string:
        return []
    try:
        raw = json.loads(tag.string)
    except json.JSONDecodeError:
        return []
    root = decode_devalue(raw) if isinstance(raw, list) else raw
    return _dedupe(players_from_json_tree(root))


# ---------------------------------------------------------------------------
# 2. Classic Sidearm markup
# ---------------------------------------------------------------------------

def _sel_text(node: Tag, selector: str) -> str:
    el = node.select_one(selector)
    return clean(el.get_text(" ")) if el else ""


def parse_sidearm_classic(html: str, soup: BeautifulSoup) -> list[dict]:
    out = []
    for li in soup.select("li.sidearm-roster-player"):
        if _in_staff_section(li):
            continue
        rec = _blank()
        name_el = li.select_one(".sidearm-roster-player-name h3 a, .sidearm-roster-player-name a, "
                                ".sidearm-roster-player-name h3, .sidearm-roster-player-name")
        rec["name"] = clean(name_el.get_text(" ")) if name_el else ""
        if name_el is not None and name_el.name == "a":
            rec["bio_url"] = name_el.get("href", "")
        rec["jersey"] = _sel_text(li, ".sidearm-roster-player-jersey-number")
        rec["position"] = _sel_text(li, ".sidearm-roster-player-position-long-short, .sidearm-roster-player-position > span:first-child, .sidearm-roster-player-position")
        rec["class_year"] = _sel_text(li, ".sidearm-roster-player-academic-year")
        rec["height"] = format_height(raw=_sel_text(li, ".sidearm-roster-player-height"))
        rec["weight"] = clean_weight(_sel_text(li, ".sidearm-roster-player-weight"))
        # Exact classes only: "sidearm-roster-player-class-hometown" is a wrapper that can hold
        # nothing but the class year ("R-Fr.") when a season has no hometowns on file.
        rec["hometown"] = _sel_text(li, ".sidearm-roster-player-hometown")
        rec["high_school"] = _sel_text(li, ".sidearm-roster-player-highschool")
        rec["previous_school"] = _sel_text(li, ".sidearm-roster-player-previous-school")
        # Position text often runs into height/weight ("Wide Receiver 6'2\" 195 lbs"); cut at the
        # first number instead of the first space, so "Wide Receiver" doesn't become "Wide".
        rec["position"] = re.split(r"\s+(?=\d)", rec["position"])[0].strip() if rec["position"] else ""
        if rec["name"]:
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 3. Sidearm nextgen person cards (HTML, used if the JSON payload is missing)
# ---------------------------------------------------------------------------

def _in_staff_section(node: Tag) -> bool:
    """True if the element sits inside a block whose id/class/heading marks it as coaches or staff
    (Sidearm: #sidearm-roster-coaches, .s-person-card-list--staff, a "Coaching Staff" heading)."""
    for anc in node.parents:
        if not isinstance(anc, Tag) or anc.name in ("body", "html", "[document]"):
            break
        attrs = " ".join([anc.get("id", ""), " ".join(anc.get("class", [])), anc.get("data-test-id", ""),
                          anc.get("aria-label", "")])
        if re.search(r"coach|staff", attrs, re.I):
            return True
        if anc.name in ("section", "div"):
            head = anc.find(["h2", "h3"], recursive=False)
            if head is not None and re.search(r"\b(coach|staff|support|manager)", head.get_text(" "), re.I) \
                    and not re.search(r"\broster\b|\bplayers?\b", head.get_text(" "), re.I):
                return True
    return False


def _strip_label(node: Tag | None) -> str:
    if node is None:
        return ""
    node = BeautifulSoup(str(node), "lxml")
    for sr in node.select(".sr-only"):
        sr.decompose()
    text = clean(node.get_text(" "))
    return re.sub(r"^(Hometown|Last School|High School|Previous School|Position|Academic Year|Height|Weight)\s*:?\s*", "", text, flags=re.I)


def parse_sidearm_cards(html: str, soup: BeautifulSoup) -> list[dict]:
    out = []
    for card in soup.select('[data-test-id="s-person-card-list__root"], .s-person-card'):
        if _in_staff_section(card):
            continue
        rec = _blank()
        a = card.select_one('[data-test-id="s-person-details__personal-single-line-person-link"]') or card.select_one("h3")
        if a is None:
            continue
        rec["name"] = clean(a.get_text(" "))
        if a.name == "a":
            rec["bio_url"] = a.get("href", "")
        g = lambda tid: _strip_label(card.select_one(f'[data-test-id="{tid}"]'))
        rec["position"] = g("s-person-details__bio-stats-person-position-short")
        rec["class_year"] = g("s-person-details__bio-stats-person-title")
        rec["height"] = format_height(raw=g("s-person-details__bio-stats-person-season"))
        rec["weight"] = clean_weight(g("s-person-details__bio-stats-person-weight"))
        rec["hometown"] = g("s-person-card-list__content-location-person-hometown")
        rec["high_school"] = g("s-person-card-list__content-location-person-high-school")
        rec["previous_school"] = g("s-person-card-list__content-location-person-previous-school")
        stamp = card.select_one('[data-test-id="s-stamp__root"]')
        rec["jersey"] = re.sub(r"\D", "", _strip_label(stamp)) if stamp else ""
        if rec["name"]:
            out.append(rec)
    # Staff cards put their job title where players have their class ("Head Coach"); drop_staff
    # (run on every parser's result) removes them.
    return out


# ---------------------------------------------------------------------------
# 4. Generic HTML table
# ---------------------------------------------------------------------------

_HEADER_FIELDS = [
    (r"hometown\s*/\s*(high school|last school|previous school)", "hometown_hs"),
    (r"hometown", "hometown"),
    (r"(high\s*school|^hs).*/.*(previous|prior|transfer|college)", "hs_prev"),
    (r"high\s*school|last\s*school|^hs$", "high_school"),
    (r"previous|transfer|prior|former|^college$|^last college$", "previous_school"),
    (r"^(#|no\.?|num|number|jersey)$", "jersey"),
    (r"first\s*name", "first_name"),
    (r"last\s*name", "last_name"),
    (r"name|player", "name"),
    (r"^pos", "position"),
    (r"^(cl|class|yr|year|academic|elig)", "class_year"),
    (r"^(ht|height)", "height"),
    (r"^(wt|weight)", "weight"),
]


def _header_field(text: str) -> str | None:
    t = clean(text).lower()
    for pattern, field in _HEADER_FIELDS:
        if re.search(pattern, t):
            return field
    return None


def _name_from_link(cell: Tag) -> str:
    """Some sites (PrestoSports) render the visible name with JS; fall back to link metadata."""
    a = cell.find("a")
    if a is None:
        return ""
    for attr in ("aria-label", "title", "data-player-name"):
        v = clean(a.get(attr, ""))
        if v:
            return clean(re.split(r":|\bjersey\b|\bfull bio\b", v, flags=re.I)[0])
    img = a.find("img")
    if img is not None and clean(img.get("alt", "")):
        return clean(img["alt"])
    m = re.search(r"/bios?/([a-z0-9_\-]+?)(?:_[a-z0-9]{5,})?(?:\?|$)", a.get("href", ""), flags=re.I)
    if m:
        return " ".join(w.capitalize() for w in re.split(r"[_\-]+", m.group(1)) if w)
    return ""


def parse_html_tables(html: str, soup: BeautifulSoup) -> list[dict]:
    best: list[dict] = []
    for table in soup.find_all("table"):
        header_row = table.find("thead")
        header_cells = header_row.find_all(["th", "td"]) if header_row else []
        if not header_cells:
            first = table.find("tr")
            header_cells = first.find_all(["th", "td"]) if first else []
        headers = [_header_field(c.get_text(" ")) for c in header_cells]
        header_text = [clean(c.get_text(" ")).lower() for c in header_cells]
        if any(h in ("title", "position/title", "staff", "coaching staff", "support staff") for h in header_text):
            continue  # a staff table, even if it also lists hometowns
        cap = table.find("caption")
        if (cap is not None and _STAFF_SECTIONS.search(cap.get_text(" "))) or _in_staff_section(table):
            continue
        if "hometown" not in headers and "hometown_hs" not in headers:
            continue
        if "name" not in headers and "last_name" not in headers:
            continue
        body_rows = table.select("tbody tr") or table.find_all("tr")[1:]
        rows = []
        for tr in body_rows:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(headers) - 1:
                continue
            # Some sites repeat the header row inside the table (once per position group). Those
            # rows used to come through as a "player" named "Name" from the hometown "Hometown".
            same = sum(1 for c, h in zip(cells, header_text) if h and clean(c.get_text(" ")).lower() == h)
            if same >= 2:
                continue
            rec = _blank()
            for field, cell in zip_longest(headers, cells):
                if cell is None:
                    continue
                val = clean(cell.get_text(" "))
                m = _CELL_LABEL.match(val)
                if m:  # PrestoSports-style responsive cells carry their own label; trust it
                    field = _header_field(m.group(1)) or field
                    val = val[m.end():].strip()
                if not field:
                    continue
                if field == "name" and not val:
                    val = _name_from_link(cell)
                if field == "hometown_hs":
                    rec["hometown"], rec["high_school"] = split_hometown_highschool(val)
                elif field == "hs_prev":
                    rec["high_school"], rec["previous_school"] = split_hometown_highschool(val)
                elif not rec.get(field):
                    rec[field] = val
                if field == "name":
                    a = cell.find("a")
                    if a and a.get("href"):
                        rec["bio_url"] = a["href"]
            if not rec["name"] and (rec["first_name"] or rec["last_name"]):
                rec["name"] = clean(f"{rec['first_name']} {rec['last_name']}")
            rec["height"] = format_height(raw=rec["height"])
            rec["weight"] = clean_weight(rec["weight"])
            if rec["name"]:
                rows.append(rec)
        if len(rows) > len(best):
            best = rows
    return best


# ---------------------------------------------------------------------------
# 5. Any other embedded JSON
# ---------------------------------------------------------------------------

def parse_embedded_json(html: str, soup: BeautifulSoup) -> list[dict]:
    best: list[dict] = []
    for tag in soup.find_all("script"):
        txt = tag.string or tag.get_text() or ""
        if "hometown" not in txt.lower() or tag.get("id") == "__NUXT_DATA__":
            continue
        for blob in _json_candidates(txt):
            players = _dedupe(players_from_json_tree(blob))
            if len(players) > len(best):
                best = players
    return best


def _json_candidates(txt: str) -> Iterable[Any]:
    txt = txt.strip()
    try:
        yield json.loads(txt)
        return
    except (json.JSONDecodeError, ValueError):
        pass
    # JSON assigned in JS: window.__DATA__ = {...};  Scan for balanced top-level objects/arrays.
    # After a successful decode, jump past it: scanning inside it again is quadratic on big blobs.
    dec = json.JSONDecoder()
    pat = re.compile(r"[\[{]")
    pos = 0
    while True:
        m = pat.search(txt, pos)
        if not m:
            return
        start = m.start()
        window = txt[max(0, start - 3): start]
        if "=" not in window and ":" not in window and start != 0 and "(" not in window:
            pos = start + 1
            continue
        try:
            obj, end = dec.raw_decode(txt, start)
        except (json.JSONDecodeError, ValueError):
            pos = start + 1
            continue
        pos = end
        if "hometown" in txt[start:end].lower():
            yield obj


# ---------------------------------------------------------------------------

def _merge_into(kept: dict, r: dict) -> None:
    for f, v in r.items():
        if v and not kept.get(f):
            kept[f] = v


def _dedupe(rows: list[dict]) -> list[dict]:
    """Collapse repeats of the same player, filling blanks from the other copies.

    Same name + same hometown is one player. Some pages list everyone twice (a grid view and a
    list view) and one copy has no hometown; that copy is folded into the one same-named player
    who has a hometown. Two players who share a name but not a hometown stay separate."""
    by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (r["name"].lower(), r["hometown"].lower())
        if key not in by_key:
            by_key[key] = dict(r)
        else:
            _merge_into(by_key[key], r)
    with_home: dict[str, list[tuple]] = {}
    for name, home in by_key:
        if home:
            with_home.setdefault(name, []).append((name, home))
    for key in [k for k in by_key if not k[1]]:
        if len(with_home.get(key[0], [])) == 1:
            _merge_into(by_key[with_home[key[0]][0]], by_key.pop(key))
    return list(by_key.values())


STRATEGIES: list[tuple[str, Callable[[str, BeautifulSoup], list[dict]]]] = [
    ("nuxt_data", parse_nuxt_data),
    ("sidearm_classic", parse_sidearm_classic),
    ("sidearm_cards", parse_sidearm_cards),
    ("html_table", parse_html_tables),
    ("embedded_json", parse_embedded_json),
]

MIN_PLAYERS = 25  # a real football roster has 80-130+; anything below this is suspicious


_CELL_LABEL = re.compile(
    r"^(No\.?|#|Jersey|Name|Full Name|Pos\.?|Position|Cl\.?|Class|Yr\.?|Year|Academic Year|Elig\.?|"
    r"Ht\.?|Height|Wt\.?|Weight|Hometown(?:\s*/\s*[A-Za-z ]+)?|High School|Last School|"
    r"Previous Schools?|Prev\. School|Former School|College|Experience|Exp\.?)\s*:\s*",
    re.I,
)
_CLASS_ONLY = re.compile(
    r"(?i)(r|rs|red|redshirt|medical redshirt)?[\s\-.]*"
    r"(fr|fy|so|jr|sr|gr|gs|freshman|sophomore|junior|senior|graduate|grad|5th|6th|"
    r"fifth|sixth)(\s*year)?\.?")
_HS_WORDS = re.compile(r"\b(hs|h\.s\.|high|academy|prep|preparatory|school)\b", re.I)


# Telling a college from a high school, for fields like "Last School" that can hold either.
# Filled with the names in config/schools.csv when the scraper starts (see main()).
KNOWN_COLLEGES: set[str] = set()
# Football junior colleges whose roster names often leave out "College"/"CC" (multi-word or distinctive only:
# a single common word like "Independence" or "Highland" is also a high school name).
JUCO_NAMES = ["Iowa Western", "East Mississippi", "Northwest Mississippi", "Mississippi Gulf Coast", "Copiah-Lincoln",
              "Co-Lin", "Pearl River", "Itawamba", "Hinds", "Holmes", "Garden City", "Dodge City", "Fort Scott",
              "Coffeyville", "Hutchinson", "Butler", "Ellsworth", "Trinity Valley", "Navarro", "Blinn", "Kilgore",
              "Arizona Western", "Riverside City", "Mt. San Antonio", "Mt. SAC", "Saddleback", "El Camino", "Butte",
              "Laney", "Lackawanna", "Georgia Military", "Snow", "Pima", "ASA", "NEO", "Northeastern Oklahoma A&M"]
_HS_STRONG = re.compile(r"\b(high school|h\.s\.|hs|prep|preparatory|secondary)\b", re.I)
_COLLEGE_WORDS = re.compile(r"\b(university|univ\.?|college|community college|institute|polytechnic|state|tech|a&m|"
                            r"naval academy|air force academy|u\.?s\.? military academy|west point)\b", re.I)
_JUCO = re.compile(r"\b(CC|JC|JUCO)\b")          # capitals only: "C.C. Winn" is a high school in Laredo


def _college_key(v: str) -> str:
    v = re.sub(r"\((fl|fla|oh|ohio|pa)\.?\)", "", v.lower())          # "Miami (FL)" -> "miami"
    return re.sub(r"[^a-z&]", "", re.sub(r"^(the|university of)\s+", "", v.strip()))


def load_known_colleges(schools: list[dict]) -> None:
    """D1 schools from config/schools.csv plus the junior colleges above."""
    KNOWN_COLLEGES.update(_college_key(s["school"]) for s in schools)
    KNOWN_COLLEGES.update(_college_key(n) for n in JUCO_NAMES)


def looks_like_college(value: str) -> bool:
    """'Texas Tech', 'Wake Forest', 'Blinn College', 'Butler CC', 'Univ. of Iowa' -> True.
    'Lamar HS', 'IMG Academy', 'Mater Dei', 'College Park High School', 'Fork Union Military Academy' -> False."""
    v = clean(value)
    if not v or _HS_STRONG.search(v):
        return False
    if re.search(r"\b(university|college|naval academy|air force academy|military academy at|west point)\b", v, re.I) \
            and not re.search(r"\bmilitary academy\b(?! at)", v, re.I):
        return True
    if _JUCO.search(v):
        return True
    if _COLLEGE_WORDS.search(v) and not re.search(r"\b(academy|school)\b", v, re.I):
        return True                                          # "Texas Tech", "Penn State", "Prairie View A&M"
    return _college_key(v) in KNOWN_COLLEGES                 # "Wake Forest", "Notre Dame", "SMU"


def _same_school(a: str, b: str) -> bool:
    """'Menard' and 'Menard HS', or 'Rancho Cucamonga' and 'Rancho Cucamonga High School (Calif.)', are one school."""
    def n(v):
        v = re.sub(r"\([^)]*\)", "", v.lower())                                  # "(Calif.)", "(Pa.)"
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(high school|h\.?s\.?|school|the)\b", "", v))
    x, y = n(a or ""), n(b or "")
    if not x or not y:
        return False
    short, long_ = sorted((x, y), key=len)
    return x == y or (len(short) >= 5 and long_.startswith(short))


def sort_schools(p: dict) -> dict:
    """Put a college in previous_school and a high school in high_school, whichever field the site used.

    'Lamar HS / Texas Tech' in one field   -> high_school 'Lamar HS', previous_school 'Texas Tech'
    'Wake Forest' under "Last School"       -> previous_school 'Wake Forest'
    high school and college swapped         -> swapped back
    two separate fields the site filled     -> kept as they are otherwise ("Saddleback" stays a previous school)
    only a "previous school", not a college -> it's his high school (some sites file every high school there)
    previous school = the high school       -> dropped ('Menard' next to 'Menard HS')"""
    def parts(v):
        return [clean(x) for x in re.split(r"\s+/\s+|\s*;\s*", v or "") if clean(x)]
    hs_parts, prev_parts = parts(p.get("high_school")), parts(p.get("previous_school"))
    hs, prev = " / ".join(hs_parts), " / ".join(prev_parts)
    if len(hs_parts) > 1 or len(prev_parts) > 1:              # combined values
        every = hs_parts + prev_parts
        colleges = [x for x in every if looks_like_college(x)]
        others = [x for x in every if x not in colleges]
        hs = next((x for x in others if _HS_WORDS.search(x)), others[0] if others else "")
        if colleges:
            prev = colleges[-1]                               # most recent college is usually listed last
        elif len(prev_parts) == 1 and prev_parts[0] != hs:
            prev = prev_parts[0]                              # the site's own previous-school field
        else:
            prev = ""
    elif hs and looks_like_college(hs):
        if not prev:
            hs, prev = "", hs
        elif not looks_like_college(prev):
            hs, prev = prev, hs                               # the two were swapped
    elif prev and not hs and not looks_like_college(prev):
        hs, prev = prev, ""                                   # a high school filed as the previous school
    if _same_school(hs, prev):
        prev = ""
    elif prev and not looks_like_college(prev) and (_HS_STRONG.search(prev) or re.search(r"\bacademy\b", prev, re.I)):
        hs, prev = hs or prev, ""                             # clearly a high school: never a transfer
    p["high_school"], p["previous_school"] = hs, prev
    return p


def _undouble(name: str) -> str:
    """'Dami Adekunjo Dami Adekunjo' (name text plus a hidden copy) -> 'Dami Adekunjo'."""
    w = name.split()
    half = len(w) // 2
    if len(w) >= 4 and len(w) % 2 == 0 and [x.lower() for x in w[:half]] == [x.lower() for x in w[half:]]:
        return " ".join(w[:half])
    return name


_CAPTAIN = re.compile(r"\(\s*c\s*\)|©|\(\s*captain\s*\)|\s+-\s*captain\b|\*+", re.I)


def clean_name(name: str) -> str:
    """Strip roster decorations from a player's name:
    '89 Mason Thomas', '#89 Mason Thomas', 'Mason Thomas 89'  -> 'Mason Thomas'
    'C Mason Thomas', 'C 89 Mason Thomas', 'Mason Thomas (C)', 'Mason Thomas*' -> 'Mason Thomas'
    'Dami Adekunjo Dami Adekunjo' -> 'Dami Adekunjo'
    A real initial is kept: 'C.J. Stroud', 'CJ Stroud' and 'C J Stroud' are left alone."""
    n = clean(_CAPTAIN.sub(" ", name or ""))
    for _ in range(3):  # markers can be stacked: "C #89 Mason Thomas"
        before = n
        n = re.sub(r"^#?\d{1,3}\s+(?=\D)", "", n)               # leading jersey number
        n = re.sub(r"\s+#?\d{1,3}$", "", n)                       # trailing jersey number
        words = n.split()
        # a lone leading "C" is a captain marker when a full name (2+ words, not initials) follows
        if len(words) >= 3 and words[0] in ("C", "C:", "C.") and len(words[1].strip(".")) > 1:
            n = " ".join(words[1:])
        if n == before:
            break
    return _undouble(n.strip(" -,"))


def tidy_players(players: list[dict]) -> list[dict]:
    for p in players:
        for f in ("position", "class_year", "hometown", "high_school", "previous_school", "height", "weight", "jersey"):
            if p.get(f):
                p[f] = _CELL_LABEL.sub("", p[f]).strip()
        # A class year is never a hometown ("R-Fr.", "Sophomore", "Gr.")
        if p.get("hometown") and _CLASS_ONLY.fullmatch(p["hometown"].strip()):
            p["hometown"] = ""
        # "25 Jalyn Williams", "C Mason Thomas", "Mason Thomas (C)" -> the bare name
        p["name"] = clean_name(p.get("name", ""))
        # Hometown sitting in a school column: "Clinton, Md. / Glen Burnie HS"
        if not p.get("hometown"):
            for f in ("high_school", "previous_school"):
                v = p.get(f, "")
                if "/" not in v:
                    continue
                town, school = split_hometown_highschool(v)
                h = parse_hometown(town)
                if h["state"] or (h["country"] and h["city"]):
                    p["hometown"], p[f] = town, ""
                    dest = "high_school" if _HS_WORDS.search(school) else "previous_school"
                    if p.get(dest):
                        dest = f
                    p[dest] = school
                    break
        sort_schools(p)
    return players


def parse_roster(html: str) -> tuple[str, list[dict]]:
    """Run every strategy; return (strategy_name, players) for the best result."""
    soup = BeautifulSoup(html, "lxml")
    best_name, best = "", []
    for name, fn in STRATEGIES:
        try:
            players = tidy_players(drop_staff(fn(html, soup)))
        except Exception:  # one broken strategy shouldn't sink the page
            players = []
        with_home = sum(1 for p in players if p["hometown"])
        best_home = sum(1 for p in best if p["hometown"])
        if with_home > best_home or (with_home == best_home and len(players) > len(best)):
            best_name, best = name, players
        if len(players) >= MIN_PLAYERS and with_home >= 0.8 * len(players):
            break  # good enough, skip slower strategies
    for p in best:
        p.pop("staff_title", None)
        if p["hometown"].strip().lower().rstrip(":. ") in _PLACEHOLDERS:
            p["hometown"] = ""
    return best_name, _dedupe(best)


# =============================================================================
# Scraping and output
# =============================================================================

log = logging.getLogger("rosters")

OUT_FIELDS = (
    ["season", "division", "current_conference", "school"]
    + [f for f in FIELDS if f != "bio_url"]
    + ["class_norm", "home_city", "home_state", "home_country", "strategy", "bio_url", "roster_url"]
)
REPORT_FIELDS = ["season", "school", "division", "current_conference", "status", "season_check",
                 "strategy", "players", "with_hometown", "url", "error"]
UNIQUE_FIELDS = ["school", "name", "position", "hometown", "home_city", "home_state", "home_country",
                 "high_school", "previous_school", "first_season", "last_season", "n_seasons", "seasons",
                 "first_class", "division_first_season", "current_conference"]


# ---------------------------------------------------------------------------
# inputs

def parse_seasons(spec: str) -> list[int]:
    """'2016-2019,2021-2026' -> [2016, 2017, 2018, 2019, 2021, ..., 2026]"""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            out.update(range(min(a, b), max(a, b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def load_schools(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("school") and not r["school"].startswith("#")]


def load_division_history(path: Path) -> dict[str, list[dict]]:
    hist: dict[str, list[dict]] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                hist.setdefault(r["school"], []).append(r)
    return hist


def division_for(school: dict, season: int, history: dict[str, list[dict]]) -> str:
    for r in history.get(school["school"], []):
        lo = int(r["first_season"]) if r["first_season"] else 0
        hi = int(r["last_season"]) if r["last_season"] else 9999
        if lo <= season <= hi:
            return r["division"]
    return school.get("division", "")


# ---------------------------------------------------------------------------
# scraping

def scrape_school_season(school: dict, fetcher: Fetcher, season: int, division: str,
                         render: bool, prefer_idx: int | None,
                         save_dir: Path | None = None) -> tuple[list[dict], dict, int | None]:
    is_current = season == current_season()
    report = {"season": season, "school": school["school"], "division": division,
              "current_conference": school.get("conference", ""), "status": "failed",
              "season_check": "", "strategy": "", "players": 0, "with_hometown": 0, "url": "", "error": ""}
    urls = candidate_urls(school.get("domain", ""), school.get("roster_url", ""), None if is_current else season)
    if is_current:
        # A school's main roster page can still show last season for weeks (New Haven 2026 came
        # back identical to 2025). Its year is checked like any archive page's, and this season's
        # archive URLs are tried after it in case the main page hasn't switched over.
        urls += [u for u in candidate_urls(school.get("domain", ""), school.get("roster_url", ""), season)
                 if u not in urls]
    order = list(range(len(urls)))
    if prefer_idx is not None and prefer_idx < len(urls):  # try last season's winning URL pattern first
        order.remove(prefer_idx)
        order.insert(0, prefer_idx)

    best = ("", [], "", None, "")  # strategy, players, url, idx, season_check
    errors: list[str] = []
    for idx in order:
        url = urls[idx]
        try:
            status, final_url, html = fetcher.get(url)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            continue
        if status != 200:
            errors.append(f"{url}: HTTP {status}")
            continue
        if not is_current and str(season) in url and str(season) not in final_url:
            # e.g. liuathletics.com/.../roster/2019 quietly redirects to the current roster
            errors.append(f"{url}: redirected to {final_url}")
            continue
        shown = detect_season(html)
        if shown is not None and shown != season:
            errors.append(f"{url}: page shows {shown}")
            continue
        if is_current:
            check = "verified" if shown == season else "current"
        else:
            check = "verified" if shown == season else "unverified"
        strategy, players = parse_roster(html)
        # A page that shows the right year beats a bigger page that shows no year.
        if (check == "verified", len(players)) > (best[4] == "verified", len(best[1])):
            best = (strategy, players, final_url, idx, check)
        if len(players) >= MIN_PLAYERS and check != "unverified":
            break

    if render and len(best[1]) < MIN_PLAYERS:
        idx = best[3] if best[3] is not None else order[0]
        url = urls[idx]
        try:
            html = fetcher.render(url)
            shown = detect_season(html)
            if shown is None or shown == season:
                strategy, players = parse_roster(html)
                if len(players) > len(best[1]):
                    check = "verified" if shown == season else ("current" if is_current else "unverified")
                    best = (f"rendered:{strategy}", players, url, idx, check)
            else:
                errors.append(f"render {url}: page shows {shown}")
        except Exception as exc:
            errors.append(f"render {url}: {exc}")

    strategy, players, url, win_idx, check = best
    if save_dir and win_idx is not None:  # --save-pages: keep a copy of the page these players came from
        page = fetcher._cache_path(urls[win_idx], rendered=strategy.startswith("rendered:"))
        if page.exists():
            safe = re.sub(r"[^A-Za-z0-9]+", "_", school["school"]).strip("_")
            shutil.copy(page, save_dir / f"{safe}_{season}.html")
    rows = []
    for p in players:
        home = parse_hometown(p["hometown"])
        row = {
            "season": season, "division": division, "current_conference": school.get("conference", ""),
            "school": school["school"], **{f: p.get(f, "") for f in FIELDS},
            "class_norm": normalize_class(p.get("class_year", "")),
            "home_city": home["city"], "home_state": home["state"], "home_country": home["country"],
            "strategy": strategy, "roster_url": url,
        }
        if row["bio_url"] and url:
            row["bio_url"] = urljoin(url, row["bio_url"])
        rows.append(row)

    with_home = sum(1 for r in rows if r["hometown"])
    report.update(strategy=strategy, players=len(rows), with_hometown=with_home, url=url,
                  season_check=check, error="; ".join(errors[:8]))
    if len(rows) >= MIN_PLAYERS and with_home >= 0.5 * len(rows):
        report["status"] = "ok"
    elif rows:
        report["status"] = "partial"
    return rows, report, (win_idx if not is_current else None)


def scrape_school_all(school: dict, seasons: list[int], fetcher: Fetcher, history: dict,
                      render: bool, skip: set[tuple[str, int]],
                      reference: tuple[int, set[str]] | None = None,
                      save_dir: Path | None = None) -> list[tuple[int, list[dict], dict]]:
    """All seasons for one school, newest first, reusing the URL pattern that worked.

    ``reference`` is (season, roster names) from an already-saved newer season, used to catch
    archive pages that silently show the current roster."""
    results = []
    prefer: int | None = None
    newest_season, newest_names = reference if reference else (None, None)
    for season in sorted(seasons, reverse=True):
        if (school["school"], season) in skip:
            continue
        division = division_for(school, season, history)
        if division.lower() == "none":
            results.append((season, [], {"season": season, "school": school["school"], "division": "",
                                         "current_conference": school.get("conference", ""),
                                         "status": "no_program", "players": 0, "with_hometown": 0}))
            continue
        rows, report, idx = scrape_school_season(school, fetcher, season, division, render, prefer, save_dir)
        names = {r["name"].lower() for r in rows}
        # A page with no visible year that is ~the same roster as a newer season is almost
        # certainly the site falling back to its current roster.
        if (report["season_check"] == "unverified" and newest_names and newest_season > season
                and names and len(names & newest_names) / len(names) > 0.8):
            report.update(status="failed", players=0, with_hometown=0,
                          error=f"page looks like the {newest_season} roster; " + report.get("error", ""))
            rows = []
        elif rows and (newest_season is None or season > newest_season):
            newest_names, newest_season = names, season
        if idx is not None and report["status"] == "ok":
            prefer = idx
        results.append((season, rows, report))
    return results


# ---------------------------------------------------------------------------
# outputs

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:  # files written by the first version used "conference"
        if "current_conference" not in r and "conference" in r:
            r["current_conference"] = r.pop("conference")
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def person_key(row: dict) -> tuple:
    name = _SUFFIX.sub("", clean(row["name"]).lower())
    name = re.sub(r"[^a-z]", "", name)
    city = re.sub(r"[^a-z]", "", (row.get("home_city") or "").lower())
    return (row["school"], name, city, row.get("home_state") or row.get("home_country") or "")


def build_unique(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(person_key(r), []).append(r)
    # A season where the site left the hometown blank would otherwise count as a second player.
    # Fold it into the one group with the same school + name, if there is exactly one.
    by_name: dict[tuple, list[tuple]] = {}
    for k in groups:
        if k[2] or k[3]:
            by_name.setdefault(k[:2], []).append(k)
    for k in [k for k in groups if not (k[2] or k[3])]:
        homes = by_name.get(k[:2], [])
        if len(homes) == 1:
            groups[homes[0]].extend(groups.pop(k))
    out = []
    for grp in groups.values():
        grp.sort(key=lambda r: int(r["season"]))
        first, last = grp[0], grp[-1]
        seasons = sorted({int(r["season"]) for r in grp})
        out.append({
            "school": first["school"], "name": last["name"], "position": last["position"],
            **{f: next((r[f] for r in grp if r["hometown"]), first[f])
               for f in ("hometown", "home_city", "home_state", "home_country")},
            "high_school": next((r["high_school"] for r in grp if r["high_school"]), ""),
            "previous_school": next((r["previous_school"] for r in grp if r["previous_school"]), ""),
            "first_season": seasons[0], "last_season": seasons[-1], "n_seasons": len(seasons),
            "seasons": " ".join(map(str, seasons)), "first_class": first["class_norm"],
            "division_first_season": first["division"], "current_conference": first["current_conference"],
        })
    out.sort(key=lambda r: (r["school"], r["first_season"], r["name"]))
    return out


def write_combined(out_dir: Path, season_dir: Path) -> tuple[list[int], list[dict], list[dict]]:
    """Rebuild rosters_all_seasons.csv and players_unique.csv from every saved season, re-cleaning
    each row so parser fixes (names, hometowns, high school vs. previous school) reach old seasons too."""
    # Combined outputs cover every season saved so far, not just this run.
    combined = []
    all_saved = []
    for path in sorted(season_dir.glob("rosters_*.csv")):
        m = re.fullmatch(r"rosters_(\d{4})\.csv", path.name)
        if m:
            all_saved.append(int(m.group(1)))
            combined.extend(read_csv(path))
    n_before = len(combined)
    combined = [r for r in combined if not is_staff(r)]  # also cleans seasons saved by older versions
    if n_before != len(combined):
        log.info("Dropped %d coach/staff rows from the saved rosters", n_before - len(combined))
    for r in combined:  # re-clean so name/hometown fixes also reach seasons scraped earlier
        r["name"] = clean_name(r.get("name", ""))
        home = parse_hometown(r.get("hometown", ""))
        r["home_city"], r["home_state"], r["home_country"] = home["city"], home["state"], home["country"]
        r["class_norm"] = normalize_class(r.get("class_year", "")) or r.get("class_norm", "")
        sort_schools(r)
    write_csv(out_dir / "rosters_all_seasons.csv", OUT_FIELDS, combined)
    unique = build_unique(combined)
    write_csv(out_dir / "players_unique.csv", UNIQUE_FIELDS, unique)

    n_prev = sum(1 for r in unique if r["previous_school"])
    log.info("Combined files cover seasons %s: %d player-season rows, %d unique players (%d with a previous school) -> %s",
             ", ".join(map(str, all_saved)), len(combined), len(unique), n_prev, out_dir)
    return all_saved, combined, unique


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schools", default="config/schools.csv", type=Path)
    ap.add_argument("--division-history", default="config/division_history.csv", type=Path)
    ap.add_argument("--seasons", help="e.g. 2016-2019,2021-2026 (default: current season)")
    ap.add_argument("--season", type=int, help="single season (same as --seasons N)")
    ap.add_argument("--division", choices=["FBS", "FCS", "all"], default="all", help="by current division")
    ap.add_argument("--conference", help="only this current conference (as in schools.csv)")
    ap.add_argument("--only", help="comma-separated school names")
    ap.add_argument("--out", default="data", type=Path)
    ap.add_argument("--cache", default=".cache/html", type=Path)
    ap.add_argument("--workers", type=int, default=6, help="schools scraped in parallel (different sites)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests to the same site")
    ap.add_argument("--refresh", action="store_true", help="ignore cached HTML and re-download")
    ap.add_argument("--render", action="store_true", help="headless Chromium for pages the fast path can't parse")
    ap.add_argument("--save-pages", type=Path, metavar="DIR",
                    help="also copy each roster page used into DIR as <school>_<season>.html (for checking by hand)")
    ap.add_argument("--retry-failed", action="store_true", help="skip school-seasons already 'ok' in the reports")
    ap.add_argument("--recombine", action="store_true",
                    help="don't download anything: re-clean every saved season and rebuild the combined files")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    seasons = parse_seasons(args.seasons) if args.seasons else [args.season or current_season()]
    season_dir, report_dir = args.out / "seasons", args.out / "reports"
    for d in (season_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)
    all_schools = load_schools(args.schools)
    history = load_division_history(args.division_history)
    load_known_colleges(all_schools)
    if args.recombine:
        write_combined(args.out, season_dir)
        return 0

    schools = list(all_schools)
    if args.division != "all":
        schools = [s for s in schools if s["division"].upper() == args.division]
    if args.conference:
        schools = [s for s in schools if s["conference"].lower() == args.conference.lower()]
    if args.only:
        wanted = {w.strip().lower() for w in args.only.split(",")}
        schools = [s for s in schools if s["school"].lower() in wanted]
    if not schools:
        log.error("No schools selected.")
        return 1
    selected = {s["school"] for s in schools}

    # Keep previous results for schools/seasons not being re-scraped in this run.
    kept_rows: dict[int, list[dict]] = {}
    kept_reports: dict[int, dict[str, dict]] = {}
    skip: set[tuple[str, int]] = set()
    for season in seasons:
        prev_reports = {r["school"]: r for r in read_csv(report_dir / f"scrape_report_{season}.csv")}
        done = {k for k, r in prev_reports.items() if r.get("status") in ("ok", "no_program")} if args.retry_failed else set()
        keep_schools = {k for k in prev_reports if k not in selected} | done
        skip.update((k, season) for k in done)
        kept_reports[season] = {k: r for k, r in prev_reports.items() if k in keep_schools}
        kept_rows[season] = [r for r in read_csv(season_dir / f"rosters_{season}.csv") if r["school"] in keep_schools]

    todo = sum(1 for s in schools for y in seasons if (s["school"], y) not in skip)
    log.info("Scraping %d schools x %d seasons (%s) = %d roster pages",
             len(schools), len(seasons), ", ".join(map(str, seasons)), todo)

    # Newest saved roster per school (from earlier runs) for the fallback check. This includes
    # seasons inside the requested range, so --retry-failed still has the newest roster to
    # compare against when that season is skipped as already done.
    references: dict[str, tuple[int, set[str]]] = {}
    saved = sorted(season_dir.glob("rosters_*.csv"), reverse=True)
    for path in saved:
        m = re.fullmatch(r"rosters_(\d{4})\.csv", path.name)
        if not m:
            continue
        for r in read_csv(path):
            if r["school"] not in references or references[r["school"]][0] == int(m.group(1)):
                references.setdefault(r["school"], (int(m.group(1)), set()))[1].add(r["name"].lower())

    save_dir = args.save_pages.expanduser() if args.save_pages else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(args.cache, delay=args.delay, refresh=args.refresh)
    new_rows: dict[int, list[dict]] = {y: [] for y in seasons}
    new_reports: dict[int, dict[str, dict]] = {y: {} for y in seasons}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(scrape_school_all, s, seasons, fetcher, history, args.render, skip,
                               references.get(s["school"]), save_dir): s
                   for s in schools}
        for i, fut in enumerate(as_completed(futures), 1):
            school = futures[fut]
            try:
                results = fut.result()
            except Exception as exc:
                log.error("%s crashed: %r", school["school"], exc)
                continue
            with lock:
                summary = []
                for season, rows, report in results:
                    new_rows[season].extend(rows)
                    new_reports[season][school["school"]] = report
                    summary.append(f"{season}:{report['players'] if report['status'] in ('ok', 'partial') else report['status'][:4]}")
                log.info("[%3d/%d] %-26s %s", i, len(schools), school["school"], " ".join(sorted(summary)))

    order = {s["school"]: i for i, s in enumerate(all_schools)}
    totals = []
    for season in seasons:
        rows = kept_rows[season] + new_rows[season]
        rows.sort(key=lambda r: (order.get(r["school"], 9999), r["school"]))
        reports = {**kept_reports[season], **new_reports[season]}
        write_csv(season_dir / f"rosters_{season}.csv", OUT_FIELDS, rows)
        write_csv(report_dir / f"scrape_report_{season}.csv", REPORT_FIELDS,
                  sorted(reports.values(), key=lambda r: order.get(r["school"], 9999)))
        st = [r.get("status") for r in reports.values()]
        totals.append((season, len(rows), st.count("ok"), st.count("partial"), st.count("failed")))

    all_saved, combined, unique = write_combined(args.out, season_dir)
    log.info("season  players   ok  partial  failed")
    for season, n, ok, part, fail in totals:
        log.info("%6d  %7d  %3d  %7d  %6d", season, n, ok, part, fail)
    if any(t[3] or t[4] for t in totals):
        log.info("Not every school worked; see reports/scrape_report_<season>.csv, fix config/schools.csv, then re-run with --retry-failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
