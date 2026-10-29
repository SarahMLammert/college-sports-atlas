"""This file holds, in order:
    Paths and settings
    Downloading pages
    Season files
    Transfer levels
    Long lists to a notes file
    Compressing the page cache (compress-cache)

Commands:
    python3 scripts/core.py compress-cache   # compressing the page cache
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import re


def clean(text) -> str:
    """Whitespace squeezed, non-breaking spaces made plain; None -> ''."""
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


# ==============================================================================================================
# Paths and settings   (was scripts/paths.py)
# ==============================================================================================================

PATHS_DOC = """Where each sport's files live, and its settings from config/<sport>/settings.json.

    config/shared/school_colors.csv, school_locations.csv     shared by every sport
    config/<sport>/settings.json                               a sport's settings (football, lacrosse-mens, ...)
    config/<sport>/schools.csv                                 its colleges: D1, their seasons in another
                                                               division, and D2/D3/NAIA/JUCO
    config/<sport>/hometown_corrections.csv                    hometown fixes (yours and the geocoder's suggestions)
    config/<sport>/wrong_seasons.csv, season_pages.csv         roster pages to skip, or to use, for a season (optional)
    rosters/<sport>/                                           the rosters (cleaned) and everything else the scripts
                                                               write: scrape reports, the geocoder's hometown table,
                                                               lists for checking (not committed)
    docs/<sport>/                                              the website pages for a sport, and the data they load

Until Oct 28 config/ was flat (config/<sport>.json, config/<sport>_schools.csv, ...); load_sport() says so if it
finds that layout.

Every script takes --sport (default: football) and gets its paths from here, so it doesn't matter
which folder a script is run from.
"""
import argparse
import contextlib
import csv
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the repo folder (this file is scripts/core.py)
CONFIG = ROOT / "config"
ROSTERS = ROOT / "rosters"
DEFAULT_SPORT = "football"


@dataclass
class Sport:
    # Folder name: the sport, then the sex when the sport has both (football, lacrosse-mens,
    # lacrosse-womens, basketball-mens). Used for config/<name>/, rosters/<name>/, docs/<name>/.
    name: str
    label: str = ""
    roster_paths: list[str] = field(default_factory=list)
    presto_paths: list[str] = field(default_factory=list)   # PrestoSports season pages: /sports/fball/{season}-{next_yy}/roster
    # A normal roster for this sport has min_players to max_players players. Outside that, a scraped page is
    # flagged as partial (cut off, or the wrong page). max_players 0 = no upper limit.
    min_players: int = 25
    max_players: int = 0
    junior_colleges: list[str] = field(default_factory=list)
    position_groups: list[str] = field(default_factory=list)
    position_abbreviations: dict[str, str] = field(default_factory=dict)
    position_words: list[list[str]] = field(default_factory=list)
    position_fallback: str = ""
    # Hockey: the "Last School" on a roster is usually a junior, prep or club team, so a previous school only makes
    # a player a transfer when it is a college in the schools file (core.py finds its level).
    transfer_needs_known_college: bool = False
    # A spring sport's season is named for the spring it ends in: lacrosse's 2024 season is spring
    # 2024, which sites label "2024" or "2023-24". Football (a fall sport) labels 2024 as "2024-25".
    spring_season: bool = False
    # How the sport splits its colleges into divisions, as written in the schools file's "division"
    # column. d1_divisions are the top-level divisions whose schools the maps are about (football:
    # FBS and FCS; lacrosse, basketball, baseball: just D1). other_divisions are the other college
    # levels (used to sort transfers, and scraped if a row has a domain). division_labels is how
    # each one is written on the pages ("D1" -> "Division I").
    d1_divisions: list[str] = field(default_factory=lambda: ["FBS", "FCS"])
    other_divisions: list[str] = field(default_factory=lambda: ["D2", "D3", "NAIA", "JUCO"])
    division_labels: dict[str, str] = field(default_factory=dict)
    # How each position group is written on the pages' chips ("FO" -> "Faceoff"); unlisted groups show as is.
    position_labels: dict[str, str] = field(default_factory=dict)
    # Roster size checks, which depend on the sport: a school-season with fewer players than
    # thin_roster is "thin" (build.py map skips its class-year transfer rule for the season
    # after), and build.py frozen needs frozen_min_pairs returning players to judge a season.
    thin_roster: int = 40
    frozen_min_pairs: int = 30
    # The seasons scripts/pipeline.py scrapes when none are given, e.g. "2016-2026". Blank: 2016 to the current
    # season, without 2020 for football (default_seasons()).
    seasons: str = ""

    def division_label(self, division: str) -> str:
        return self.division_labels.get(division, division)

    def default_seasons(self, today=None) -> str:
        """2016 to the current season. Spring sports name a season by the spring it ends in, and post next
        spring's roster when school starts, so from August the current season is next year's (October 2026:
        2027, the 2026-27 team). Fall sports: the fall it's played in, from March. Football skips 2020."""
        if self.seasons:
            return self.seasons
        from datetime import date
        t = today or date.today()
        if self.spring_season:
            last = t.year + 1 if t.month >= 8 else t.year
        else:
            last = t.year if t.month >= 3 else t.year - 1
        return f"2016-2019,2021-{last}" if self.name == "football" else f"2016-{last}"

    # ---- this sport's folders and files ----
    @property
    def settings_json(self) -> Path:
        return _settings_json(self.name)

    @property
    def rosters_dir(self) -> Path:
        return ROSTERS / self.name

    @property
    def site_dir(self) -> Path:
        return ROOT / "docs" / self.name

    @property
    def schools_csv(self) -> Path:
        return CONFIG / self.name / "schools.csv"

    @property
    def wrong_seasons_csv(self) -> Path:
        """School-seasons whose only roster page is another season's (a site's archive page that shows the
        year before, or its main page for every old season). Never scraped; rows saved from them are dropped."""
        return CONFIG / self.name / "wrong_seasons.csv"

    def wrong_seasons(self) -> dict[tuple[str, int], str]:
        """(school, season) -> why, from config/<sport>/wrong_seasons.csv (school, season, reason)."""
        path = self.wrong_seasons_csv
        if not path.exists():
            return {}
        import csv
        with open(path, newline="", encoding="utf-8") as fh:
            return {(r["school"].strip(), int(r["season"])): (r.get("reason") or "").strip()
                    for r in csv.DictReader(fh) if r.get("school") and str(r.get("season", "")).strip().isdigit()}

    @property
    def season_pages_csv(self) -> Path:
        """School-seasons whose roster is on a page the usual addresses get wrong (Albany women's lacrosse filed
        spring 2017-2020 under the year before: its "2019" page is the 2020 team). The page given is used as is."""
        return CONFIG / self.name / "season_pages.csv"

    def season_pages(self) -> dict[tuple[str, int], str]:
        """(school, season) -> the roster page to use, from config/<sport>/season_pages.csv (school, season, url, note)."""
        path = self.season_pages_csv
        if not path.exists():
            return {}
        import csv
        with open(path, newline="", encoding="utf-8") as fh:
            return {(r["school"].strip(), int(r["season"])): r["url"].strip()
                    for r in csv.DictReader(fh) if r.get("url") and str(r.get("season", "")).strip().isdigit()}

    @property
    def hometown_corrections_csv(self) -> Path:
        return CONFIG / self.name / "hometown_corrections.csv"

    @property
    def division_history_csv(self) -> Path:      # the history rows now live in schools.csv
        return self.schools_csv

    # ---- shared by every sport ----
    @property
    def colors_csv(self) -> Path:
        return CONFIG / "shared" / "school_colors.csv"

    @property
    def locations_csv(self) -> Path:
        return CONFIG / "shared" / "school_locations.csv"


def _settings_json(name: str) -> Path:
    return CONFIG / name / "settings.json"


def available_sports() -> list[str]:
    return sorted(p.parent.name for p in CONFIG.glob("*/settings.json"))


def load_sport(name: str = DEFAULT_SPORT) -> Sport:
    path = _settings_json(name)
    if not path.exists() and (CONFIG / f"{name}.json").exists():
        raise SystemExit(f"config/ is in its old flat layout (config/{name}.json). Since Oct 28 each sport has a folder: "
                         f"config/{name}/settings.json, schools.csv, hometown_corrections.csv, and config/shared/ for "
                         "the school colors and locations. Move the files (README: 'The config folder').")
    if not path.exists():
        have = ", ".join(available_sports()) or "none yet"
        raise SystemExit(f"No settings for sport '{name}' ({path} is missing). Sports set up: {have}.")
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings.pop("name", None)
    known = set(Sport.__dataclass_fields__)
    unknown = sorted(set(settings) - known)
    if unknown:
        raise SystemExit(f"{path}: unknown settings {', '.join(unknown)}")
    sport = Sport(name=name, **settings)
    use_divisions(sport)
    return sport


def use_divisions(sport: Sport) -> None:
    """Point D1 and SCRAPED at this sport's divisions. The sets are changed in place, so code that
    did `from paths import D1` sees the sport's divisions too."""
    clash = set(sport.d1_divisions) & set(sport.other_divisions)
    if clash or not sport.d1_divisions:
        raise SystemExit(f"{sport.settings_json}: d1_divisions must be set and not repeat other_divisions "
                         f"({', '.join(sorted(clash))})")
    D1.clear()
    D1.update(sport.d1_divisions)
    SCRAPED.clear()
    SCRAPED.update(sport.d1_divisions, sport.other_divisions)


class SportBusy(SystemExit):
    pass


LOCK_ENV = "COLLEGE_SPORTS_LOCK_HELD"   # set by pipeline.py for the steps it runs, which share its lock


@contextlib.contextmanager
def sport_lock(sport: Sport, what: str = "a scrape"):
    """Refuse to start when another scrape or pipeline of the same sport is running: both would write
    the same season files. The lock is the OS's (flock), so it ends with the process, even after a
    crash or Ctrl-C; there's no stale lock file to delete. Steps run by pipeline.py skip it, since the
    pipeline already holds it for them."""
    if os.environ.get(LOCK_ENV) == sport.name:
        yield
        return
    path = sport.rosters_dir / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        import fcntl
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.seek(0)
            who = fh.read().strip() or "another run"
            fh.close()
            raise SportBusy(f"{sport.name} is busy: {who}. Wait for it to finish (or stop it) and run this again.")
    except ImportError:            # Windows: no flock; carry on without the check
        fcntl = None
    fh.seek(0)
    fh.truncate()
    fh.write(f"{what} started {time.strftime('%H:%M')} (process {os.getpid()})")
    fh.flush()
    try:
        yield
    finally:
        fh.close()


def add_sport_argument(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--sport", default=DEFAULT_SPORT,
                    help=f"which sport's files to use: config/<sport>/ (default: {DEFAULT_SPORT})")


# ---- reading a sport's school lists ----

# The current sport's divisions, set by load_sport() from its settings (d1_divisions,
# other_divisions). These starting values are football's, for code that never loads a sport.
D1 = {"FBS", "FCS"}
SCRAPED = {"FBS", "FCS", "D2", "D3", "NAIA", "JUCO"}     # divisions the scraper downloads (not HS or "none")


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("school") and not r["school"].startswith("#")]


def _spans(r: dict) -> bool:
    return bool((r.get("first_season") or "").strip() or (r.get("last_season") or "").strip())


def _season(v: str, default: int) -> int:
    v = (v or "").strip()
    return int(v) if v else default


def _main_row(rows: list[dict]) -> tuple[dict, bool]:
    """(the row a college is scraped under, whether it has a row with no season range).
    That's its row with no season range; failing that, its open-ended range (Thomas More: D2 from
    2023); failing that, its latest range (a program that has closed)."""
    plain = [r for r in rows if not _spans(r)]
    if plain:
        return plain[0], True
    open_ended = [r for r in rows if not (r.get("last_season") or "").strip()]
    if open_ended:
        return max(open_ended, key=lambda r: _season(r.get("first_season"), 0)), False
    return max(rows, key=lambda r: _season(r.get("last_season"), 0)), False


def load_schools(path: Path, divisions: set[str] | None = None) -> list[dict]:
    """The colleges the scraper downloads: one row per college with a domain or roster_url, in the
    file's order, limited to `divisions` (by the college's current division) if given.

    Each college's row is the one with no season range, or, for a college that only has ranges (it
    moved between divisions, started recently or closed), its current or latest range; a domain or
    roster_url missing there is taken from another of its rows. Its other rows are its seasons in
    another division or with no team (load_division_history). A college with only ranges gets
    ``has_plain_row = False``, so division_for() reads seasons outside every range as "none".
    D1 schools come back exactly as before. load_all_colleges() reads every row, d1_schools() only D1."""
    groups: dict[str, list[tuple[int, dict]]] = {}
    for i, r in enumerate(_rows(path)):
        if r["division"].strip() in SCRAPED:
            groups.setdefault(r["school"], []).append((i, r))
    picked = []
    for name, rows in groups.items():
        main, plain = _main_row([r for _, r in rows])
        if divisions and main["division"].strip() not in divisions:
            continue
        row = dict(main)
        for f in ("domain", "roster_url"):
            if not (row.get(f) or "").strip():
                row[f] = next(((r.get(f) or "").strip() for _, r in rows if (r.get(f) or "").strip()), "")
        if not (row["domain"] or (row.get("roster_url") or "").strip()):
            continue                                       # no site known yet: nothing to download
        if not plain:
            row["has_plain_row"] = False
        picked.append((next(i for i, r in rows if r is main), row))
    return [row for _, row in sorted(picked, key=lambda p: p[0])]


def d1_schools(path: Path) -> list[dict]:
    """Rows in the sport's D1 divisions (football: FBS/FCS) with no season range: the D1 schools. The scraper's "is this a college?" check
    (sidearm.load_known_colleges) uses only these names, since many smaller colleges share a name
    with high schools ("Central", "Union", "Franklin")."""
    return [r for r in _rows(path) if r["division"].strip() in D1 and not _spans(r)]


def load_all_colleges(path: Path) -> list[dict]:
    return _rows(path) if Path(path).exists() else []


def load_division_history(path: Path) -> dict[str, list[dict]]:
    """College -> its rows with a season range (seasons in another division, or with no team)."""
    hist: dict[str, list[dict]] = {}
    if Path(path).exists():
        rows = _rows(path)
        scraped = {r["school"] for r in rows if r["division"].strip() in SCRAPED}
        for r in rows:
            if r["school"] in scraped and _spans(r) and r["division"].strip() != "HS":
                hist.setdefault(r["school"], []).append(r)
    return hist


def division_for(school: dict, season: int, history: dict[str, list[dict]]) -> str:
    """The college's division that season. Outside every range: its usual division, or "none" (no
    team) for a college that only has ranges (Mount Mercy before 2026, St. Cloud State after 2019)."""
    for r in history.get(school["school"], []):
        lo = int(r["first_season"]) if r["first_season"] else 0
        hi = int(r["last_season"]) if r["last_season"] else 9999
        if lo <= season <= hi:
            return r["division"]
    return school.get("division", "") if school.get("has_plain_row", True) else "none"


# ==============================================================================================================
# Downloading pages   (was scripts/fetch.py)
# ==============================================================================================================

FETCH_DOC = ''
"""Downloading roster and staff pages: retries, polite pacing per site, an on-disk cache, and an
optional headless-browser fallback. Shared by every sport."""
import gzip
import hashlib
import os
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


# Set by sidearm.configure() from the sport's settings.
SPRING_SEASON = False


def current_season(today=None) -> int:
    """The season a school's main roster page shows today.

    Fall sport (football): the season is the fall it's played in, so 2026 from March 2026 (when the
    new roster goes up) to February 2027. Spring sport (lacrosse, baseball, softball): the season is the
    spring it ends in, and sites put up next spring's roster when school starts, so from August 2026 the
    main page is the 2027 roster. (This used to answer 2026 all autumn for spring sports, so a main page
    with no year on it was saved as 2026 while it already showed 2027.)"""
    from datetime import date
    today = today or date.today()
    if SPRING_SEASON:
        return today.year + 1 if today.month >= 8 else today.year
    return today.year if today.month >= 3 else today.year - 1


class _Retry(Retry):
    """Retry that honors a site's "come back in N seconds" (Retry-After) for at most 30 seconds.
    Without a cap, one site asking for an hour stalls that school, and the whole run waits on it."""
    MAX_WAIT = 30

    def get_retry_after(self, response):
        wait = super().get_retry_after(response)
        return None if wait is None else min(wait, self.MAX_WAIT)


# A past season's address that answered "not found" is remembered for this many days (a .miss file next to
# the cached pages), so later runs don't ask for it again: Ohio State's 2016 season has 21 addresses to try,
# 8 of them missing, and those 8 used to be downloaded again (1.5 s apart) on every run.
MISS_DAYS = 60
MISS_STATUSES = (404, 410)


class Fetcher:
    def __init__(self, cache_dir: Path, delay: float = 1.5, refresh: bool = False, timeout: int = 30,
                 forget_misses: bool = False):
        self.forget_misses = forget_misses    # --forget-misses: ask again for addresses that were "not found"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.refresh = refresh
        self.timeout = timeout
        self._local = threading.local()
        self._host_lock = threading.Lock()
        self._last_hit: dict[str, float] = {}
        self._slow_sites: set[str] = set()
        # Hosts that couldn't be reached at all this run (no such name, connection refused). Their other
        # addresses are skipped straight away: a dead host costs one failed connection, not one (with
        # retries, ~13 s) per address and season. Kept per host, since www. and the bare domain can differ.
        self._dead_hosts: set[str] = set()

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
        """The page's name in the cache, as <host>_<hash>.html. Since Oct 28 it is saved compressed, next to
        that name as .html.gz (pages shrink ~14x: the cache went from 64 GB to ~5 GB); read_cached() reads
        either."""
        host = urlparse(url).netloc.replace(":", "_")
        digest = hashlib.sha1(url.encode()).hexdigest()[:10]
        return self.cache_dir / f"{host}_{digest}{'_r' if rendered else ''}.html"

    @staticmethod
    def gz_path(path: Path) -> Path:
        return path.with_name(path.name + ".gz")

    @classmethod
    def is_cached(cls, path: Path) -> bool:
        return cls.gz_path(path).exists() or path.exists()

    @classmethod
    def read_cached(cls, path: Path) -> str:
        """A cached page's text. A page saved before Oct 28 (plain .html) is compressed the first time it's read."""
        gz = cls.gz_path(path)
        if gz.exists():
            with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            cls.write_cached(path, text)
        except OSError:
            pass
        return text

    @classmethod
    def write_cached(cls, path: Path, text: str) -> None:
        """Save a page compressed (written to a temporary name first, so a stopped run never leaves half a file)."""
        gz = cls.gz_path(path)
        tmp = gz.with_name(gz.name + f".{os.getpid()}.tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
            fh.write(text)
        tmp.replace(gz)
        path.unlink(missing_ok=True)

    @classmethod
    def drop_cached(cls, path: Path) -> None:
        cls.gz_path(path).unlink(missing_ok=True)
        path.unlink(missing_ok=True)

    def _pace(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._host_lock:
            wait = self._last_hit.get(host, 0) + self.delay - time.monotonic()
            self._last_hit[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def _known_miss(self, path: Path) -> int | None:
        """The status (404, 410) a past "not found" for this address was saved with, if still fresh."""
        miss = path.with_suffix(".miss")
        if self.forget_misses or not miss.exists():
            return None
        try:
            if time.time() - miss.stat().st_mtime > MISS_DAYS * 86400:
                return None
            return int(miss.read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def get(self, url: str, remember_miss: bool = True) -> tuple[int, str, str]:
        """Return (status, final_url, html). Cached responses come back with status 200.

        remember_miss: a 404/410 is saved and answered from disk on later runs, even with --refresh (a
        missing archive page from 2017 doesn't appear later). Not for the current season's addresses,
        which can go up any day: the scraper passes False for those."""
        path = self._cache_path(url, rendered=False)
        if not self.refresh and self.is_cached(path):
            final = path.with_suffix(".url")
            return 200, final.read_text() if final.exists() else url, self.read_cached(path)
        if remember_miss:
            status = self._known_miss(path)
            if status is not None:
                return status, url, ""
        self._skip_if_slow(url)
        host = urlparse(url).netloc.lower()
        if host in self._dead_hosts:
            raise requests.exceptions.ConnectionError(f"{host} couldn't be reached earlier in this run; skipped")
        self._pace(url)
        try:
            resp = self._download(url)
        except (TimeoutError, requests.exceptions.Timeout):
            self._mark_slow(url)
            raise
        except requests.exceptions.ConnectionError as exc:
            if unreachable(exc):
                with self._host_lock:
                    self._dead_hosts.add(host)
            raise
        if resp.status_code == 200 and resp.text:
            self.write_cached(path, resp.text)
            path.with_suffix(".url").write_text(resp.url)
            path.with_suffix(".miss").unlink(missing_ok=True)
        elif resp.status_code in MISS_STATUSES and remember_miss:
            path.with_suffix(".miss").write_text(f"{resp.status_code} {url}\n")
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
        if not self.refresh and self.is_cached(path):
            html = self.read_cached(path)
            if not is_bot_check(html):         # a check page saved by an older version: try again
                return html
            self.drop_cached(path)
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
        self.write_cached(path, html)
        tmp.unlink(missing_ok=True)
        return html


_UNREACHABLE = ("NameResolutionError", "Failed to resolve", "nodename nor servname", "Name or service not known",
                "getaddrinfo failed", "NewConnectionError", "Connection refused", "No route to host",
                "Unable to connect to proxy")


def unreachable(exc: Exception) -> bool:
    """True when the host itself can't be reached (no such name, refused), as opposed to a connection that
    broke halfway (reset, cut off), which may work on the next address."""
    text = repr(exc)
    return any(m in text for m in _UNREACHABLE)


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


# ==============================================================================================================
# Season files   (was scripts/seasons.py)
# ==============================================================================================================

SEASONS_DOC = """Shared: a sport's season roster files (rosters_<season>.csv) and the one-row-per-player list built from them.

The scraper writes one cleaned file per season. The geocoder, build.py frozen and build.py map
read those files directly; players() turns them into one row per player per school, in memory, so no
combined file has to be kept on disk (scrape_rosters.py --combined still writes rosters_all_seasons.csv
and players_unique.csv for opening in a spreadsheet).
"""
import csv
import re
from pathlib import Path

# (clean() is defined at the top of this file)

UNIQUE_FIELDS = ["school", "name", "position", "hometown", "home_city", "home_state", "home_country",
                 "high_school", "previous_school", "first_season", "last_season", "n_seasons", "seasons",
                 "first_class", "division_first_season", "current_conference"]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:  # files written by the first version used "conference"
        if "current_conference" not in r and "conference" in r:
            r["current_conference"] = r.pop("conference")
    return rows


def season_files(out_dir: Path) -> dict[int, Path]:
    """season -> rosters_<season>.csv for every season saved in the folder."""
    out = {}
    for path in Path(out_dir).glob("rosters_*.csv"):
        m = re.fullmatch(r"rosters_(\d{4})\.csv", path.name)
        if m:
            out[int(m.group(1))] = path
    return dict(sorted(out.items()))


def season_rows(rosters_dir: Path) -> list[dict]:
    """Every row of every saved season file, oldest season first."""
    files = season_files(rosters_dir)
    if not files:
        raise SystemExit(f"No season roster files (rosters_<season>.csv) in {rosters_dir}. Run scrape_rosters.py first.")
    rows = []
    for path in files.values():
        rows += read_csv(path)
    return rows


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def person_key(row: dict) -> tuple:
    name = _SUFFIX.sub("", clean(row["name"]).lower())
    name = re.sub(r"[^a-z]", "", name)
    city = re.sub(r"[^a-z]", "", (row.get("home_city") or "").lower())
    return (row["school"], name, city, row.get("home_state") or row.get("home_country") or "")


def build_unique(rows: list[dict]) -> list[dict]:
    """Season rows -> one row per player per school, with first/last season on the roster."""
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


def players(rosters_dir: Path) -> list[dict]:
    """One row per player per school, built from the sport's season files."""
    return build_unique(season_rows(rosters_dir))


# ==============================================================================================================
# Transfer levels   (was scripts/levels.py)
# ==============================================================================================================

LEVELS_DOC = 'Which level a transfer\'s previous school was at: D1, D2, D3, NAIA, JUCO, club or unknown.\n\nEvery college is a row in config/<sport>/schools.csv: the D1 schools, the seasons some of them spent in\nanother division, and the D2, D3, NAIA and junior colleges, with other spellings in its aliases column\n(separated by "|"). A row can be limited to a range of seasons, so "Tarleton State" means Division II\nfor a player who left before 2020 and D1 after. Rows with division HS are high schools whose name looks\nlike a college ("St. John\'s College"), so they stay unknown. Rows with division CLUB are club (non-varsity)\nteams, such as lacrosse\'s MCLA teams: never scraped, only a level for transfers.\n\n    levels = Levels.load(sport)\n    levels.level("Valdosta St.", 2018)        -> ("D2", "Valdosta State")\n    levels.level("Hutchinson (Kan.) CC", 2022) -> ("JUCO", "")\n\nSpellings are compared by key(): lowercase words without "University", "the", "of", "at" or punctuation,\n"St." read as "State" at the end of a name and "Saint" elsewhere, "UW-" as "Wisconsin", and a\nparenthetical state ("(Kan.)", "(MO)") kept as a postal code. A name that fits schools at two different\nlevels ("Bethel", "Concordia") comes back unknown rather than guessed.'
import csv
import re
from pathlib import Path

LEVELS = ["D1", "D2", "D3", "NAIA", "JUCO", "CLUB", "unknown"]
LEVEL_NAMES = {"D1": "Division I", "D2": "Division II", "D3": "Division III", "NAIA": "NAIA",
               "JUCO": "Junior college", "CLUB": "Club team", "unknown": "Unknown"}

_DROP = {"the", "of", "at", "university", "univ", "suny", "in"}
_EXPAND = {"mt": "mount", "uw": "wisconsin", "wis": "wisconsin", "unc": "north carolina",
           "ft": "fort", "miss": "mississippi", "okla": "oklahoma", "ark": "arkansas", "tenn": "tennessee",
           "ala": "alabama", "ga": "georgia", "kan": "kansas", "neb": "nebraska", "minn": "minnesota",
           "mich": "michigan", "conn": "connecticut", "nw": "northwest", "sw": "southwest",
           "colo": "colorado", "calif": "california", "wva": "west virginia", "ne": "northeast",
           "se": "southeast", "ky": "kentucky", "fla": "florida", "pa": "pennsylvania", "col": "college",
           "coll": "college", "inst": "institute"}
_STATES = {
    "al": "al", "ala": "al", "alabama": "al", "ak": "ak", "alaska": "ak", "az": "az", "ariz": "az", "arizona": "az",
    "ar": "ar", "ark": "ar", "arkansas": "ar", "ca": "ca", "cal": "ca", "calif": "ca", "california": "ca",
    "co": "co", "colo": "co", "colorado": "co", "ct": "ct", "conn": "ct", "connecticut": "ct", "de": "de",
    "del": "de", "delaware": "de", "fl": "fl", "fla": "fl", "florida": "fl", "ga": "ga", "georgia": "ga",
    "hi": "hi", "hawaii": "hi", "ia": "ia", "iowa": "ia", "id": "id", "idaho": "id", "il": "il", "ill": "il",
    "illinois": "il", "in": "in", "ind": "in", "indiana": "in", "ks": "ks", "kan": "ks", "kans": "ks",
    "kansas": "ks", "ky": "ky", "kentucky": "ky", "la": "la", "louisiana": "la", "ma": "ma", "mass": "ma",
    "massachusetts": "ma", "md": "md", "maryland": "md", "me": "me", "maine": "me", "mi": "mi",
    "mich": "mi", "michigan": "mi", "mn": "mn", "minn": "mn", "minnesota": "mn", "mo": "mo",
    "missouri": "mo", "ms": "ms", "miss": "ms", "mississippi": "ms", "mt": "mt", "mont": "mt",
    "montana": "mt", "nc": "nc", "nd": "nd", "ne": "ne", "neb": "ne", "nebraska": "ne", "nh": "nh",
    "nj": "nj", "nm": "nm", "nv": "nv", "nev": "nv", "nevada": "nv", "ny": "ny", "oh": "oh", "ohio": "oh",
    "ok": "ok", "okla": "ok", "oklahoma": "ok", "or": "or", "ore": "or", "oregon": "or", "pa": "pa",
    "penn": "pa", "pennsylvania": "pa", "ri": "ri", "sc": "sc", "sd": "sd", "tn": "tn", "tenn": "tn",
    "tennessee": "tn", "tx": "tx", "tex": "tx", "texas": "tx", "ut": "ut", "utah": "ut", "va": "va",
    "virginia": "va", "vt": "vt", "vermont": "vt", "wa": "wa", "wash": "wa", "washington": "wa",
    "wi": "wi", "wis": "wi", "wisc": "wi", "wisconsin": "wi", "wv": "wv", "wva": "wv", "wy": "wy",
    "wyo": "wy", "wyoming": "wy", "n c": "nc", "s c": "sc", "n d": "nd", "s d": "sd", "n m": "nm",
    "n y": "ny", "n j": "nj", "n h": "nh", "w va": "wv", "r i": "ri",
}

# Generic two-year college wording: "Butler CC", "Tyler Junior College", "Santa Barbara City College".
_JUCO = re.compile(r"(?i:\b(community|junior|comm\.?)\s+college\b|\bjuco\b|\bcity college\b(?! of new york)|"
                   r"\bc\.\s?c\.(?=\W|$)|\bj\.\s?c\.(?=\W|$)|\bcommunity and technical college\b)|"
                   r"\b(CC|JC|CTC)\b")
# Academic majors that some roster pages (Valparaiso's, for one) put in the previous-school field.
_MAJOR = re.compile(
    r"(?i)^(?:(?:pre-?)?(?:business|finance|marketing|management|accounting|communications?|kinesiology|"
    r"exercise|sports?|sport|engineering|mechanical|electrical|civil|chemical|computer|environmental|"
    r"bio\w*|integrated|healthcare|health|leadership|psychology|criminal|justice|economics|econometrics|"
    r"data|science|sociology|political|history|nursing|mathematics|administration|undecided|undeclared|"
    r"general|studies|education|physical|recreation|journalism|english|and|&|,)\s*)+$")


# Wording that only a high school uses: "St. John's College H.S.", "Boston College High".
_HIGH_SCHOOL = re.compile(r"(?i)\b(high school|high|h\.\s?s\.?|hs|prep|preparatory|secondary|vo-?tech|"
                          r"lab(oratory)? school|collegiate institute|charter)\b(?![- ]?(at|of)\b)")


def is_major(text: str) -> bool:
    """'Business', 'Sport Management', 'Mechanical Engineering' -> True: a major, not a school."""
    return bool(_MAJOR.match((text or "").strip()))


def _state(v: str) -> str:
    v = re.sub(r"[^a-z ]", "", v.lower()).strip()
    return _STATES.get(v, _STATES.get(v.replace(" ", ""), ""))


def key(name: str) -> str:
    """'Valdosta St.' and 'Valdosta State University' -> 'valdosta state'; 'UW-Whitewater' ->
    'wisconsin whitewater'; 'Lincoln University (Mo.)' -> 'lincoln (mo)'."""
    v = (name or "").lower().replace("&", " and ").replace("’", "'")
    hint = ""
    for p in re.findall(r"\(([^)]*)\)", v):
        if not hint:   # a state becomes its postal code; anything else ("St. Louis", "Moorhead") is read like a name
            hint = _state(p) or " ".join("saint" if w == "st" else _EXPAND.get(w, w)
                                         for w in re.findall(r"[a-z]+", p) if w not in _DROP)
    v = re.sub(r"\([^)]*\)", " ", v)
    words = [w for w in re.findall(r"[a-z0-9]+", v.replace("'", "")) if w not in _DROP]
    words = re.sub(r"\b([a-z]) (?=[a-z]\b)", r"\1", " ".join(words)).split()   # "n c state" -> "nc state"
    out = []
    for i, w in enumerate(words):
        if w == "st":
            w = "state" if i == len(words) - 1 else "saint"
        out.extend(_EXPAND.get(w, w).split())
    if len(out) > 2 and out[-1] == "u":            # "Arizona State U." (but "Cal U" stays as it is)
        out.pop()
    if len(out) > 1 and out[0] == "u":             # "U of Mary"
        out.pop(0)
    base = " ".join(out)
    return f"{base} ({hint})" if hint and base else base


def _base(k: str) -> str:
    return re.sub(r"\s*\([^)]*\)$", "", k)


def _loose(k: str) -> set[str]:
    """Looser spellings of a key: without its parenthetical, without 'College' / 'CC' / 'JC'."""
    b = _base(k)
    out = {b}
    for pat in (r"\s+(college|community college|junior college|cc|jc|ctc)$", r"^college\s+"):
        s = re.sub(pat, "", b)
        if s and s != b:
            out.add(s)
    return out - {k, ""}


class Levels:
    def __init__(self):
        self.strong: dict[str, list[tuple]] = {}   # key -> [(level, first, last, school)]
        self.weak: dict[str, list[tuple]] = {}

    def add(self, school: str, level: str, first: int | None, last: int | None, aliases=(), loose=True):
        entry = (level, first, last, school)
        names = [school, *aliases]
        for n in names:
            k = key(n)
            if k:
                self.strong.setdefault(k, []).append(entry)
                if loose:
                    for w in _loose(k):
                        self.weak.setdefault(w, []).append(entry)

    @staticmethod
    def _at(entries, year):
        """Entries for that season; for a season outside every range (a program that closed), the nearest."""
        def gap(e):
            return max((e[1] - year) if e[1] is not None else 0, (year - e[2]) if e[2] is not None else 0, 0)
        if not entries:
            return []
        best = min(gap(e) for e in entries)
        return [e for e in entries if gap(e) == best]

    def _pick(self, table, k, year):
        """(level, school) for a key, ("ambiguous", "") if it fits schools at two levels, None if no school."""
        hits = self._at(table.get(k, []), year)
        if not hits:
            return None
        levels = {e[0] for e in hits}
        if len(levels) > 1:
            return ("ambiguous", "")                     # same name at two levels: don't guess
        schools = {e[3] for e in hits}
        return (hits[0][0], hits[0][3] if len(schools) == 1 else "")

    def level(self, text: str, year: int) -> tuple[str, str]:
        """(level, school name it matched) for a previous-school text, in the season he left.
        Several schools in one field ("Wawasee | Ball State | Bethel (Tenn.)", "Lyons (College of the
        Sequoias)") are tried from the last one listed, which is usually the most recent."""
        got = self._one(text, year)
        if got[0] != "unknown" or got[1]:
            return got
        parts = [x.strip() for x in re.split(r"\s*[|/;]\s*", text or "") if x.strip()]
        parts += [x.strip() for x in re.findall(r"\(([^)]{6,})\)", text or "") if not _state(x)]
        if len(parts) > 1 or (parts and parts[0] != (text or "").strip()):
            for part in reversed(parts):
                got = self._one(part, year)
                if got[0] != "unknown":
                    return got
        return ("unknown", "")

    def _one(self, text: str, year: int) -> tuple[str, str]:
        text = (text or "").strip()
        if not text or is_major(text) or _HIGH_SCHOOL.search(text):
            return ("unknown", "")
        k = key(text)
        for table, kk in ((self.strong, k), (self.strong, _base(k)), (self.weak, k), (self.weak, _base(k))):
            got = self._pick(table, kk, year)
            if got:
                if got[0] == "unknown":
                    return got                            # a name listed as not a college ("Gonzaga College")
                if got[0] != "ambiguous":
                    return got
                if table is self.weak:
                    return ("unknown", "")
                break                                     # an ambiguous exact name: try the JUCO wording only
        if _JUCO.search(text):
            return ("JUCO", "")
        for kk in sorted(_loose(k), key=len, reverse=True):   # "Hope College" -> "hope"
            got = self._pick(self.strong, kk, year) or self._pick(self.weak, kk, year)
            if got:
                return got if got[0] != "ambiguous" else ("unknown", "")
        return ("unknown", "")

    @classmethod
    def load(cls, sport, schools: list[dict] | None = None) -> "Levels":
        """Every college in the sport's schools.csv (or the rows given), and the sport's junior colleges."""
        lv = cls()
        if schools is None:
            schools = _read_schools(Path(sport.schools_csv))
        by_school: dict[str, list[tuple]] = {}
        aliases: dict[str, list[str]] = {}
        for r in schools:
            name = (r.get("school") or "").strip()
            if not name or name.startswith("#"):
                continue
            by_school.setdefault(name, []).append(
                (_int(r.get("first_season")), _int(r.get("last_season")), (r.get("division") or "").strip()))
            aliases.setdefault(name, []).extend(a.strip() for a in (r.get("aliases") or "").split("|") if a.strip())
        # The sport's own D1 divisions (football: FBS, FCS; most sports: D1) all count as D1.
        level_of = {**_LEVEL_OF, **{d.upper(): "D1" for d in getattr(sport, "d1_divisions", [])}}
        for name, rows in sorted(by_school.items()):
            for first, last, level in _level_spans(rows, level_of):
                if level:                                  # "none": no team those seasons
                    lv.add(name, level, first, last, aliases[name])
        for n in getattr(sport, "junior_colleges", []):
            lv.add(n, "JUCO", None, None)
        return lv


def _int(v):
    v = (v or "").strip()
    return int(v) if v else None


# A division in schools.csv -> its level here. "none" (no team) has no level. Levels.load() adds the
# sport's own D1 divisions (d1_divisions in config/<sport>/settings.json), so FBS and FCS are D1 for football.
_LEVEL_OF = {"D1": "D1", "D2": "D2", "D3": "D3", "NAIA": "NAIA", "JUCO": "JUCO", "CLUB": "CLUB", "HS": "unknown"}


def _level_spans(rows, level_of=None):
    """One college's (first, last, division) rows -> (first, last, level) for its seasons: each row with a
    season range as given, and the row without one (the school's usual level) filling the seasons between."""
    level_of = level_of or _LEVEL_OF

    def level(d):
        return level_of.get(d.upper(), "")
    usual = next((level(d) for f, l, d in rows if f is None and l is None), None)
    ranged = sorted(((f, l, level(d)) for f, l, d in rows if f is not None or l is not None),
                    key=lambda r: -1 if r[0] is None else r[0])
    if usual is None:
        return ranged
    out, cur = [], None                                   # cur: the first season not covered yet (None: from the start)
    for first, last, lvl in ranged:
        if first is not None and (cur is None or first > cur):
            out.append((cur, first - 1, usual))
        out.append((first, last, lvl))
        if last is None:
            return out
        cur = last + 1
    out.append((cur, None, usual))
    return out


def _read_schools(path: Path) -> list[dict]:
    if not path.exists():
        print(f"{path} not found; only the sport's junior colleges have a level")
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ==============================================================================================================
# Long lists to a notes file   (was scripts/notes.py)
# ==============================================================================================================

NOTES_DOC = 'Long lists of schools go to a notes file instead of the terminal.\n\n    from notes import Notes\n    notes = Notes(sport.rosters_dir / "notes_build.txt")      # rewritten on each run\n    notes.listed("no colors in config/shared/school_colors.csv for", missing)\n\nFive names or fewer are printed as before. More print one line with the count and where the names are.'
from pathlib import Path

SHOWN = 5


class Notes:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.started = False

    def listed(self, label: str, items, shown: int = SHOWN) -> None:
        items = [str(x) for x in items]
        if not items:
            return
        if len(items) <= shown:
            print(f"{label}: {', '.join(items)}")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w" if not self.started else "a", encoding="utf-8") as fh:
            fh.write(f"{label} ({len(items)}):\n" + "".join(f"  {x}\n" for x in items) + "\n")
        self.started = True
        try:
            where = self.path.relative_to(Path.cwd())
        except ValueError:
            where = self.path
        print(f"{label}: {len(items)} (names in {where})")


# ==============================================================================================================
# Compressing the page cache (compress-cache)   (was scripts/compress_cache.py)
# ==============================================================================================================

COMPRESS_CACHE_DOC = """Compress the downloaded pages in .cache/html (each <name>.html becomes <name>.html.gz, ~14x smaller).

Since Oct 28 the scraper saves pages compressed and reads both kinds, so this only frees the space the
pages saved before then take (64 GB -> ~5 GB). Safe to stop at any time and run again: it carries on
where it stopped. Don't run it while a scrape of any sport is running.

    python3 scripts/core.py compress-cache               # everything (about 10-20 minutes)
    python3 scripts/core.py compress-cache --minutes 5   # stop after 5 minutes
"""
import argparse
import os
import sys
import time
from pathlib import Path


CACHE = Path(__file__).resolve().parent.parent / ".cache" / "html"


def compress_cache_main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=COMPRESS_CACHE_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=0, help="stop after this many minutes (default: run to the end)")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args(argv)
    stop = time.monotonic() + args.minutes * 60 if args.minutes else None
    done = before = after = left = 0
    with os.scandir(args.cache) as it:
        names = [e.name for e in it]
    for name in names:
        path = args.cache / name
        if name.endswith((".part", ".tmp")) or ".html.gz." in name:
            path.unlink(missing_ok=True)            # left over from a stopped download or an earlier stopped run
            continue
        if not name.endswith(".html"):
            continue
        if stop and time.monotonic() > stop:
            left += 1
            continue
        try:
            size = path.stat().st_size
            Fetcher.write_cached(path, path.read_text(encoding="utf-8", errors="replace"))
            before += size
            after += Fetcher.gz_path(path).stat().st_size
            done += 1
        except FileNotFoundError:
            continue
        if done % 2000 == 0:
            print(f"  {done:,} pages, {before / 1e9:.1f} GB -> {after / 1e9:.2f} GB", flush=True)
    print(f"Compressed {done:,} pages: {before / 1e9:.1f} GB -> {after / 1e9:.2f} GB."
          + (f" {left:,} left: run it again to finish." if left else " All done."))
    return 0


COMMANDS = {"compress-cache": compress_cache_main}


def command_line(argv=None) -> int:
    """python3 scripts/core.py <command> [options]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        sys.argv[0] = f"{Path(sys.argv[0]).name} {argv[0]}"     # so --help says "build.py map"
        return COMMANDS[argv[0]](argv[1:]) or 0
    sys.exit("commands: " + ", ".join(COMMANDS) + " (add --help to one for its options)")


if __name__ == "__main__":
    raise SystemExit(command_line())
