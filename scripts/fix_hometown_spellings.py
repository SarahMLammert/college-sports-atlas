"""Add fixes for misspelled hometowns to data/<sport>/hometown_corrections.csv (default sport: football).

Each pair below is a misspelling found next to the real town (within 25 km, same state) in the map
data, checked by hand. Pairs that are two real places (Los Gatos / Los Altos, Monroe / Montrose,
Grosse Pointe Farms / Park, ...) are left out.

The script finds every raw hometown text in data/<sport>/players_unique_geocoded.csv that the geocoder placed
in a misspelled town, and writes a "fixed" row for it in data/<sport>/hometown_corrections.csv. Rows you
already have for those texts are updated; everything else is kept as it is.

It also updates the geocoder's lookup table, data/<sport>/hometowns.csv, which the geocoder checks before the
corrections: each misspelled entry gets the real town's name and location from the same table.
It's safe to run more than once.

Run it, then geocode and build again (from the repo folder):
    python scripts/fix_hometown_spellings.py              # add --sport <name> for another sport
    python scripts/geocode_hometowns.py
    python scripts/check_frozen_classes.py
    python scripts/build_map_data.py
"""
import argparse
import csv
import sys
from pathlib import Path

from core.paths import add_sport_argument, load_sport

# Set from --sport in main(): files in data/<sport>/.
PLAYERS = CORRECTIONS = LOOKUP = Path()   # players_unique_geocoded.csv, hometown_corrections.csv, and
                                          # hometowns.csv (the geocoder's table of hometowns it has placed)

# (state or country, misspelled city as it appears on the map, correct city)
FIXES = [
    ("CA", "Milipitas", "Milpitas"), ("CA", "Pasedena", "Pasadena"), ("CA", "Rockling", "Rocklin"),
    ("CA", "San Clarita", "Santa Clarita"),
    ("CT", "Wetherfield", "Wethersfield"),
    ("FL", "Altamonte Spring", "Altamonte Springs"), ("FL", "Broward Country", "Broward County"),
    ("FL", "Cocunut Creek", "Coconut Creek"), ("FL", "For Pierce", "Fort Pierce"),
    ("FL", "Glen Saint Mary", "Glen St. Mary"), ("FL", "Pompano Bch.", "Pompano Beach"),
    ("FL", "Port Saint Lucie", "Port St. Lucie"), ("FL", "W. Palm Beach", "West Palm Beach"),
    ("GA", "Douglasvillle", "Douglasville"), ("GA", "Saint Simon Island", "St. Simons Island"),
    ("HI", "Wailuka", "Wailuku"),
    ("IL", "East Saint Louis", "East St. Louis"),
    ("LA", "Baton Rogue", "Baton Rouge"), ("LA", "St. Francesville", "St. Francisville"),
    ("MA", "Hopkinson", "Hopkinton"), ("MA", "North Attleborough", "North Attleboro"),
    ("MA", "Tyngsboro", "Tyngsborough"),
    ("MD", "Capital Heights", "Capitol Heights"), ("MD", "Oxon HIlls", "Oxon Hill"),
    ("MD", "Reisertown", "Reisterstown"), ("MD", "Sandy Springs", "Sandy Spring"),
    ("MD", "Temple Hill", "Temple Hills"), ("MD", "W. Friendship", "West Friendship"),
    ("MI", "Sault Sainte Marie", "Sault Ste. Marie"),
    ("MO", "Lake Saint Louis", "Lake St. Louis"), ("MO", "Lee Summit", "Lee's Summit"),
    ("MO", "Weldon Springs", "Weldon Spring"),
    ("MS", "Bay Saint Louis", "Bay St. Louis"), ("MS", "Holly Spring", "Holly Springs"),
    ("MS", "Leaksville", "Leakesville"),   # the real town is Leakesville, though fewer rosters spell it so
    ("NE", "Colombus", "Columbus"),
    ("NY", "Niagra Falls", "Niagara Falls"), ("NY", "Walkill", "Wallkill"),
    ("NY", "Wappinger Falls", "Wappingers Falls"),
    ("OH", "Gates Mill", "Gates Mills"), ("OH", "Kings Mill", "Kings Mills"),
    ("PA", "Chester Spring", "Chester Springs"), ("PA", "Corapolis", "Coraopolis"),
    ("PA", "Huntington Valley", "Huntingdon Valley"), ("PA", "Landsdale", "Lansdale"),
    ("SC", "Mrytle Beach", "Myrtle Beach"), ("SC", "St. Stephens", "St. Stephen"),
    ("South Africa", "Capetown", "Cape Town"),
    ("TN", "Murfressboro", "Murfreesboro"),
    ("TX", "China Springs", "China Spring"),
    ("UT", "North Salt Lake City", "North Salt Lake"),
    ("VA", "Bealton", "Bealeton"),
    ("WA", "Seatlle", "Seattle"),
    ("WI", "Harland", "Hartland"),
]
FIELDS = ["hometown_raw", "city", "state", "country", "query", "status", "note", "players"]


def patch_lookup(wrong: dict) -> tuple[int, int]:
    """The geocoder keeps every hometown it has placed in data/<sport>/hometowns.csv (keyed by the raw text)
    and reuses those rows before it reads hometown_corrections.csv, so a correction alone never moves
    a hometown it has already placed. Point the misspelled rows at the real town: copy its location
    from the table's own row for that town, or drop the row if the table has none (the next geocode
    run then looks it up again, using the correction)."""
    if not LOOKUP.exists():
        return 0, 0
    with open(LOOKUP, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    place = lambda r: r.get("state") or r.get("country") or ""
    # the real town's location: its best-supported row in the table
    ref = {}
    goods = {(p, good.lower()) for (p, _), good in wrong.items()}
    for r in rows:
        key = (place(r), (r.get("city") or "").strip().lower())
        if key in goods and r.get("lat"):
            rank = (r.get("precision") == "city", int(r.get("players") or 0))   # a city-level match first, then the most used
            if key not in ref or rank > ref[key][0]:
                ref[key] = (rank, r)
    ref = {k: r for k, (_, r) in ref.items()}
    keep, patched, dropped = [], 0, 0
    for r in rows:
        good = wrong.get((place(r), (r.get("city") or "").strip().lower()))
        if not good:
            keep.append(r)
            continue
        src = ref.get((place(r), good.lower()))
        if src:
            r.update(city=good, lat=src["lat"], lon=src["lon"], source="spelling_fix", precision=src["precision"])
            keep.append(r)
            patched += 1
        else:
            dropped += 1
    if patched or dropped:
        with open(LOOKUP, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(keep)
    return patched, dropped


def main(argv=None):
    global PLAYERS, CORRECTIONS, LOOKUP
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    data = load_sport(ap.parse_args(argv).sport).data_dir
    PLAYERS, CORRECTIONS, LOOKUP = (data / "players_unique_geocoded.csv", data / "hometown_corrections.csv",
                                    data / "hometowns.csv")
    for p in (PLAYERS, CORRECTIONS):
        if not p.exists():
            sys.exit(f"{p} not found. Run geocode_hometowns.py first.")
    wrong = {(place, bad.lower()): good for place, bad, good in FIXES}

    found = {}   # raw hometown text -> (place, bad, good, players)
    with open(PLAYERS, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        need = {"hometown", "home_city", "home_state", "home_country"} - set(reader.fieldnames or [])
        if need:
            sys.exit(f"{PLAYERS} has no {', '.join(sorted(need))} column; can't match hometowns.")
        for r in reader:
            place = r.get("home_state") or r.get("home_country") or ""
            key = (place, (r.get("home_city") or "").strip().lower())
            if key in wrong and r.get("hometown"):
                raw = r["hometown"]
                prev = found.get(raw)
                found[raw] = (place, r["home_city"], wrong[key], (prev[3] if prev else 0) + 1)

    with open(CORRECTIONS, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or FIELDS
        rows = list(reader)
    by_raw = {r["hometown_raw"]: r for r in rows}

    added = updated = 0
    for raw, (place, bad, good, n) in sorted(found.items()):
        us = len(place) == 2
        fix = {
            "city": good, "state": place if us else "", "country": "USA" if us else place,
            "query": f"{good}, {place}, USA" if us else f"{good}, {place}",
            "status": "fixed", "note": f"spelling '{bad}' -> {good}", "players": str(n),
        }
        if raw in by_raw:
            by_raw[raw].update(fix)
            updated += 1
        else:
            row = {f: "" for f in fields}
            row.update(fix, hometown_raw=raw)
            rows.append(row)
            by_raw[raw] = row
            added += 1

    with open(CORRECTIONS, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    patched, dropped = patch_lookup(wrong)
    if patched or dropped:
        print(f"{LOOKUP}: {patched} misspelled entries moved to the real town"
              + (f", {dropped} removed so the geocoder looks them up again" if dropped else ""))

    towns = {(p, b) for p, b, _, _ in found.values()}
    missing = [f"{bad}, {place}" for place, bad, _ in FIXES if (place, bad) not in towns]
    print(f"{added} corrections added and {updated} updated in {CORRECTIONS}, covering {len(towns)} misspelled towns")
    if missing:
        print("not found in the player data (already fixed, or spelled differently now):", "; ".join(missing))
    print("next: python scripts/geocode_hometowns.py, then scripts/check_frozen_classes.py and scripts/build_map_data.py")


if __name__ == "__main__":
    main()
