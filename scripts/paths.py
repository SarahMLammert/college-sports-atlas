"""Where each sport's files live, and its settings from config/<sport>.json.

    config/school_colors.csv, config/school_locations.csv   shared by every sport
    config/<sport>.json                                      a sport's settings (football.json, ...)
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
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the repo folder (this file is scripts/paths.py)
CONFIG = ROOT / "config"
ROSTERS = ROOT / "rosters"
DEFAULT_SPORT = "football"


@dataclass
class Sport:
    name: str                                   # folder name: football, mens-basketball, ...
    label: str = ""
    roster_paths: list[str] = field(default_factory=list)
    min_players: int = 25
    junior_colleges: list[str] = field(default_factory=list)
    position_groups: list[str] = field(default_factory=list)
    position_abbreviations: dict[str, str] = field(default_factory=dict)
    position_words: list[list[str]] = field(default_factory=list)
    position_fallback: str = ""

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
    return Sport(name=name, **settings)


def add_sport_argument(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--sport", default=DEFAULT_SPORT,
                    help=f"which sport's files to use: config/<sport>.json (default: {DEFAULT_SPORT})")


# ---- reading a sport's school lists ----

D1 = {"FBS", "FCS"}


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("school") and not r["school"].startswith("#")]


def _spans(r: dict) -> bool:
    return bool((r.get("first_season") or "").strip() or (r.get("last_season") or "").strip())


def load_schools(path: Path) -> list[dict]:
    """The D1 schools the scraper downloads: FBS/FCS rows of schools.csv with no season range.
    (The file's other rows are those schools' seasons in another division, and the D2, D3, NAIA and
    junior colleges used to sort transfers; load_all_colleges() reads everything.)"""
    return [r for r in _rows(path) if r["division"].strip() in D1 and not _spans(r)]


def load_all_colleges(path: Path) -> list[dict]:
    return _rows(path) if Path(path).exists() else []


def load_division_history(path: Path) -> dict[str, list[dict]]:
    """D1 school -> its rows with a season range (seasons in another division, or with no team)."""
    hist: dict[str, list[dict]] = {}
    if Path(path).exists():
        rows = _rows(path)
        d1 = {r["school"] for r in rows if r["division"].strip() in D1 and not _spans(r)}
        for r in rows:
            if r["school"] in d1 and _spans(r):
                hist.setdefault(r["school"], []).append(r)
    return hist


def division_for(school: dict, season: int, history: dict[str, list[dict]]) -> str:
    for r in history.get(school["school"], []):
        lo = int(r["first_season"]) if r["first_season"] else 0
        hi = int(r["last_season"]) if r["last_season"] else 9999
        if lo <= season <= hi:
            return r["division"]
    return school.get("division", "")
