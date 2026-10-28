"""Check a sport's saved rosters after a run, and print where it stands.

    python scripts/check_rosters.py --sport softball

scripts/pipeline.py runs it as its last step. It only reads; it changes nothing. It prints:

  players       how many players the map build will have (one per player per school)
  scrape        ok / partial / failed / left out school-seasons by division (from the --report files)
  hometowns     how many players' hometowns couldn't be placed (unmatched_hometowns.csv)
  oversized     school-seasons with at least twice the school's usual (median) roster: usually the page
                was over-read or holds JV too (softball's Michigan 2018: 237 saved, 21 on the page)
  repeated      school-seasons whose roster is nearly the same as the season before, class years and all:
                usually an archive page that quietly shows another season's roster
  current       spring sports only: seasons taken from a school's main roster page that showed no year.
                Until Oct 27 the scraper took the main page in the autumn as this spring's season, though
                sites already show next spring's roster then. pipeline.py --redo-current scrapes those again.

The oversized and repeated lists are also written to rosters/<sport>/roster_checks.csv, with the page
address each one came from, for checking in a browser.
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import Counter, defaultdict

from paths import add_sport_argument, load_sport
from seasons import build_unique, read_csv, season_files

OVERSIZED = 2.0      # a school-season this many times the school's median is listed
OVERSIZED_MIN_EXTRA = 10   # ... and at least this many players over it (small rosters vary a lot)
REPEATED = 0.9       # this share of a roster's names on the season before's roster ...
SAME_CLASS = 0.8     # ... with this share of them still in the same class year is listed (a real roster
                     # keeps 60-80% of its players, and nearly all of them move up a class)


def report_rows(sport) -> list[dict]:
    rows = []
    for path in sorted(sport.rosters_dir.glob("scrape_report_*.csv")):
        rows += read_csv(path)
    return rows


def status_of(r: dict) -> str:
    st = r.get("status", "")
    if st == "failed" and (r.get("error") or "").lower().startswith("left out"):
        return "left_out"      # reports written before Oct 27
    return st


def name_key(name: str) -> str:
    return "".join(c for c in (name or "").lower() if c.isalpha())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    files = season_files(sport.rosters_dir)
    if not files:
        print(f"No season files in {sport.rosters_dir} yet: nothing to check.")
        return 0

    by_season: dict[int, list[dict]] = {}
    for season, path in files.items():
        by_season[season] = read_csv(path)
    rows = [r for season in files for r in by_season[season]]
    unique = build_unique(rows)
    print(f"{sport.label or sport.name}: {len(unique):,} players ({len(rows):,} player-seasons, "
          f"seasons {min(files)}-{max(files)})")

    # ---- scrape status by division, from the reports
    reports = report_rows(sport)
    if reports:
        order = list(sport.d1_divisions) + [d for d in sport.other_divisions if d not in sport.d1_divisions]
        counts: dict[str, Counter] = defaultdict(Counter)
        for r in reports:
            st = status_of(r)
            if st != "no_program":
                counts[r.get("division") or "?"][st] += 1
        divs = [d for d in order if d in counts] + sorted(d for d in counts if d not in order)
        print("\nschool-seasons      ok  partial  failed  left out")
        for d in divs:
            c = counts[d]
            print(f"  {d:<12} {c['ok']:7,} {c['partial']:8,} {c['failed']:7,} {c['left_out']:9,}")
    else:
        print("\n(no scrape reports yet: scrape with --report to get the ok/partial/failed table)")

    # ---- hometowns
    unmatched = read_csv(sport.rosters_dir / "unmatched_hometowns.csv")
    if unmatched or (sport.rosters_dir / "unmatched_hometowns.csv").exists():
        n = sum(int(r.get("players") or 0) for r in unmatched)
        print(f"\nhometowns not placed: {len(unmatched):,} places, {n:,} players"
              + (" (see unmatched_hometowns.csv)" if unmatched else ""))

    # ---- oversized and repeated rosters
    size: dict[tuple[str, int], int] = Counter((r["school"], int(r["season"])) for r in rows)
    url: dict[tuple[str, int], str] = {}
    names: dict[tuple[str, int], set[str]] = defaultdict(set)
    classes: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
    for r in rows:
        k = (r["school"], int(r["season"]))
        url.setdefault(k, r.get("roster_url", ""))
        names[k].add(name_key(r["name"]))
        classes[k][name_key(r["name"])] = (r.get("class_norm") or "").upper()
    seasons_of: dict[str, list[int]] = defaultdict(list)
    for school, season in size:
        seasons_of[school].append(season)

    found = []   # (kind, school, season, players, detail, url)
    for school, ys in seasons_of.items():
        ys.sort()
        if len(ys) >= 3:
            med = statistics.median(size[(school, y)] for y in ys)
            for y in ys:
                n = size[(school, y)]
                if n >= OVERSIZED * med and n - med >= OVERSIZED_MIN_EXTRA:
                    found.append(("oversized", school, y, n, f"usually {med:g}", url[(school, y)]))
        for prev, cur in zip(ys, ys[1:]):
            a, b = names[(school, prev)], names[(school, cur)]
            both = a & b
            if len(b) < sport.min_players or len(both) < REPEATED * len(b):
                continue
            # Returning players move up a class; a copy of the season before's page keeps every label.
            # (A roster with no class years can't be told apart, so it's listed too.)
            ca, cb = classes[(school, prev)], classes[(school, cur)]
            same_class = sum(1 for n in both if ca.get(n) == cb.get(n)) / len(both)
            if same_class >= SAME_CLASS:
                found.append(("repeated", school, cur, size[(school, cur)],
                              f"{len(both) / len(b):.0%} same names and {same_class:.0%} same class years as {prev}",
                              url[(school, cur)]))
    for kind, title in (("oversized", f"Rosters at least {OVERSIZED:g}x the school's usual size"),
                        ("repeated", "Rosters nearly the same as the season before (another season's page?)")):
        hits = sorted((f for f in found if f[0] == kind), key=lambda f: (f[1], f[2]))
        print(f"\n{title}: {len(hits) or 'none'}")
        for _, school, season, n, detail, _u in hits[:40]:
            print(f"  {school} {season}: {n} players ({detail})")
        if len(hits) > 40:
            print(f"  ... and {len(hits) - 40} more in roster_checks.csv")
    out = sport.rosters_dir / "roster_checks.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["check", "school", "season", "players", "detail", "roster_url"])
        w.writerows(sorted(found))

    # ---- spring seasons taken from a main page with no year on it
    if sport.spring_season and reports:
        current = sorted({(int(r["season"]), r["school"]) for r in reports
                          if r.get("season_check") == "current" and status_of(r) in ("ok", "partial")})
        if current:
            seasons = sorted({s for s, _ in current})
            print(f"\n{len(current)} school-seasons ({', '.join(map(str, seasons))}) came from a main roster page "
                  "with no year on it. In the autumn that page may already be next spring's roster.")
            print(f"  To scrape them again from their season pages: python3 scripts/pipeline.py {sport.name} --redo-current")

    # ---- the map
    data = sport.site_dir / "map_data.json"
    if data.exists():
        newest = max(p.stat().st_mtime for p in files.values())
        if data.stat().st_mtime < newest:
            print(f"\n{data.relative_to(sport.site_dir.parent.parent)} is older than the rosters: run the build step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
