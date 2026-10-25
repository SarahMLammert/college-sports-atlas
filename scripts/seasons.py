"""Shared: a sport's season roster files (rosters_<season>.csv) and the one-row-per-player list built from them.

The scraper writes one cleaned file per season. The geocoder, check_frozen_classes.py and build_map_data.py
read those files directly; players() turns them into one row per player per school, in memory, so no
combined file has to be kept on disk (scrape_rosters.py --combined still writes rosters_all_seasons.csv
and players_unique.csv for opening in a spreadsheet).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from hometowns import clean

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
