"""Find school-seasons whose class labels don't advance from year to year.

Some schools' archive roster pages show every player's class as of a later
season (Ohio State 2017-2022, for one). Newcomers then look like juniors or
older, and build_map_data.py's "arrived as a junior or older" rule reads them
as transfers. This script finds those seasons.

For each pair of a school's consecutive seasons in the data (2019 -> 2021
counts as consecutive), it takes the players on both rosters and checks
whether their class moved up. Two measures are printed:

  all     every returning player
  no_sr   only players who were FR, SO or JR the season before, so seniors and
          grads repeating a year (often the COVID free year) don't count

A frozen archive scores ~90-100% on both. A season inflated by COVID repeats
scores high on "all" but normal on "no_sr".

Run:  python scripts/check_frozen_classes.py          # add --sport <name> for another sport
Reads the rosters in rosters/<sport>/ and writes rosters/<sport>/frozen_class_seasons.csv
(school, season, share) for the build.
"""
import argparse
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

from paths import add_sport_argument, load_sport

CUTOFF = 0.6        # flag a pair of seasons when this share of players didn't advance
MIN_PAIRS = 30      # need at least this many returning players to judge (the sport's frozen_min_pairs replaces it)
WATCH = ("Ohio State", "Alabama", "Georgia", "Miami (FL)", "Florida", "Penn State")   # football examples; other sports print none

_RANKS = [(("FR", "FY", "FIRST", "1"), 1), (("SO", "2"), 2), (("JR", "JU", "3"), 3),
          (("SR", "SE", "4"), 4), (("GR", "5", "6", "7", "8"), 5)]


def class_rank(value):
    """FR=1 ... GR=5, ignoring redshirt and similar prefixes; None if unreadable."""
    s = (value or "").upper().replace("MEDICAL", "").replace("REDSHIRT", "")
    s = re.sub(r"^\W*(SUPER|RED|RS|CV|R|S)[\s.\-]+", "", s)   # R-SO, Red 5th, S-Sr., CV-Sr.
    s = re.sub(r"[^A-Z0-9]", "", s)
    if s in ("RF", "RJ"):                                        # Rf. = redshirt freshman
        return {"RF": 1, "RJ": 3}[s]
    for prefixes, rank in _RANKS:
        if s.startswith(prefixes):
            return rank
    return None


def load_rows(rosters: Path):
    path = rosters / "rosters_all_seasons.csv"
    files = [path] if path.exists() else sorted(p for p in rosters.glob("rosters_*.csv")
                                                  if re.fullmatch(r"rosters_\d{4}\.csv", p.name))
    if not files:
        raise SystemExit(f"No roster data found in {rosters}.")
    for f in files:
        with open(f, encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    sport = load_sport(ap.parse_args(argv).sport)
    global MIN_PAIRS
    MIN_PAIRS = sport.frozen_min_pairs
    out = sport.rosters_dir / "frozen_class_seasons.csv"
    by = defaultdict(dict)          # (school, season) -> {(name, hometown): rank}
    unreadable = defaultdict(int)
    for r in load_rows(sport.rosters_dir):
        rank = class_rank(r.get("class_norm"))
        if rank is None and r.get("class_norm"):
            unreadable[r["class_norm"]] += 1
        by[(r["school"], int(r["season"]))][(r["name"], r.get("hometown", ""))] = rank

    years = defaultdict(list)
    for school, season in by:
        years[school].append(season)

    results = []                    # (school, prev, cur, share_all, n_all, share_no_sr, n_no_sr)
    for school, ys in years.items():
        ys.sort()
        for prev, cur in zip(ys, ys[1:]):
            if cur - prev > 2:
                continue
            before, after = by[(school, prev)], by[(school, cur)]
            pairs = [(before[k], c) for k, c in after.items() if k in before and before[k] and c]
            young = [(a, b) for a, b in pairs if a <= 3]
            if len(pairs) < MIN_PAIRS:
                continue
            share = lambda ps: sum(b <= a for a, b in ps) / len(ps)
            # A frozen archive lists most players at their final class (SR/GR), so
            # too few underclassmen remain to judge; then fall back to everyone.
            sy = share(young) if len(young) >= MIN_PAIRS else None
            results.append((school, prev, cur, share(pairs), len(pairs), sy, len(young)))

    if not results:
        raise SystemExit("No season pairs had enough returning players to compare.")

    print(f"{len(results)} season pairs compared")
    print(f"median stuck share, all players: {statistics.median(r[3] for r in results):.0%}")
    print(f"median stuck share, no SR/GR:    "
          f"{statistics.median(r[5] for r in results if r[5] is not None):.0%}")
    if unreadable:
        top = sorted(unreadable.items(), key=lambda kv: -kv[1])[:10]
        print("class labels it couldn't read (ignored):", top)

    print("\nReference schools (prev -> season: all / no SR-GR):")
    for school, prev, cur, sa, na, sy, ny in sorted(results, key=lambda r: (r[0], r[2])):
        if school in WATCH:
            young_txt = f"{sy:4.0%} of {ny:3}" if sy is not None else f"  -- only {ny} underclassmen"
            print(f"  {school:12} {prev}->{cur}  {sa:4.0%} of {na:3}  /  {young_txt}")

    print(f"\nPairs at or above {CUTOFF:.0%} on 'all' but below it once SR/GR are left out"
          " (likely COVID repeats, not frozen):")
    covid = [r for r in results if r[3] >= CUTOFF and r[5] is not None and r[5] < CUTOFF]
    for school, prev, cur, sa, na, sy, ny in sorted(covid, key=lambda r: -r[3]):
        print(f"  {school} {prev}->{cur}  {sa:.0%} -> {sy:.0%}")
    if not covid:
        print("  none")

    flagged = {}
    for school, prev, cur, sa, na, sy, ny in results:
        measure = sy if sy is not None else sa
        if measure >= CUTOFF:
            for key in ((school, prev), (school, cur)):
                flagged[key] = max(measure, flagged.get(key, 0))

    print(f"\n{len(flagged)} school-seasons flagged as frozen (stuck share >= {CUTOFF:.0%};"
          " underclassmen only when there are enough of them):")
    for (school, season), sh in sorted(flagged.items()):
        print(f"  {school} {season}  {sh:.0%}")

    per_season = defaultdict(int)
    for _, season in flagged:
        per_season[season] += 1
    print("\nflagged by season:", dict(sorted(per_season.items())))

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["school", "season", "share"])
        for (school, season), sh in sorted(flagged.items()):
            w.writerow([school, season, f"{sh:.3f}"])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
