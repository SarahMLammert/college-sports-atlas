"""Where each sport's files live, and its settings from config/<sport>.json.

    config/school_colors.csv, config/school_locations.csv   shared by every sport
    config/<sport>.json                                      a sport's settings (football.json, lacrosse-mens.json, ...)
    config/<sport>_schools.csv                               its colleges: D1, their seasons in another
                                                             division, and D2/D3/NAIA/JUCO
    config/<sport>_hometown_corrections.csv                  hometown fixes (yours and the geocoder's suggestions)
    rosters/<sport>/                                         the rosters (cleaned) and everything else the scripts
                                                             write: scrape reports, the geocoder's hometown table,
                                                             lists for checking (not committed)
    docs/<sport>/                                            the website pages for a sport, and the data they load

Every script takes --sport (default: football) and gets its paths from here, so it doesn't matter
which folder a script is run from.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the repo folder (this file is scripts/paths.py)
CONFIG = ROOT / "config"
ROSTERS = ROOT / "rosters"
DEFAULT_SPORT = "football"


@dataclass
class Sport:
    # Folder name: the sport, then the sex when the sport has both (football, lacrosse-mens,
    # lacrosse-womens, basketball-mens). Used for config/<name>.json, rosters/<name>/, docs/<name>/.
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
    # thin_roster is "thin" (build_map_data.py skips its class-year transfer rule for the season
    # after), and check_frozen_classes.py needs frozen_min_pairs returning players to judge a season.
    thin_roster: int = 40
    frozen_min_pairs: int = 30
    # The seasons scripts/pipeline.py scrapes when none are given, e.g. "2016-2026". Blank: football's
    # "2016-2019,2021-2026" for football, "2016-2026" for every other sport (default_seasons()).
    seasons: str = ""

    def division_label(self, division: str) -> str:
        return self.division_labels.get(division, division)

    def default_seasons(self) -> str:
        if self.seasons:
            return self.seasons
        return "2016-2019,2021-2026" if self.name == "football" else "2016-2026"

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
        return CONFIG / f"{self.name}_schools.csv"

    @property
    def hometown_corrections_csv(self) -> Path:
        return CONFIG / f"{self.name}_hometown_corrections.csv"

    @property
    def division_history_csv(self) -> Path:      # the history rows now live in schools.csv
        return self.schools_csv

    # ---- shared by every sport ----
    @property
    def colors_csv(self) -> Path:
        return CONFIG / "school_colors.csv"

    @property
    def locations_csv(self) -> Path:
        return CONFIG / "school_locations.csv"


def _settings_json(name: str) -> Path:
    return CONFIG / f"{name}.json"


def available_sports() -> list[str]:
    return sorted(p.stem for p in CONFIG.glob("*.json"))


def load_sport(name: str = DEFAULT_SPORT) -> Sport:
    path = _settings_json(name)
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
                    help=f"which sport's files to use: config/<sport>.json (default: {DEFAULT_SPORT})")


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
