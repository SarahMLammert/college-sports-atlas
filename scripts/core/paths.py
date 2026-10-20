"""Where each sport's files live, and its settings from config/<sport>/sport.json.

    config/school_colors.csv, config/school_locations.csv   shared by every sport
    config/<sport>/sport.json                                that sport's settings
    config/<sport>/schools.csv, division_history.csv         that sport's schools
    data/<sport>/                                            working files (not committed)
    docs/<sport>/data/                                       what the website loads

Every script takes --sport (default: football) and gets its paths from here, so it doesn't matter
which folder a script is run from.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # the repo folder (this file is scripts/core/paths.py)
CONFIG = ROOT / "config"
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
    def config_dir(self) -> Path:
        return CONFIG / self.name

    @property
    def data_dir(self) -> Path:
        return ROOT / "data" / self.name

    @property
    def site_data_dir(self) -> Path:
        return ROOT / "docs" / self.name / "data"

    @property
    def schools_csv(self) -> Path:
        return self.config_dir / "schools.csv"

    @property
    def division_history_csv(self) -> Path:
        return self.config_dir / "division_history.csv"

    # ---- shared by every sport ----
    @property
    def colors_csv(self) -> Path:
        return CONFIG / "school_colors.csv"

    @property
    def locations_csv(self) -> Path:
        return CONFIG / "school_locations.csv"


def available_sports() -> list[str]:
    return sorted(p.parent.name for p in CONFIG.glob("*/sport.json"))


def load_sport(name: str = DEFAULT_SPORT) -> Sport:
    path = CONFIG / name / "sport.json"
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
                    help=f"which sport's files to use, a folder in config/ (default: {DEFAULT_SPORT})")


# ---- reading a sport's school lists ----

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
