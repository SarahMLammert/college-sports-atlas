"""Suggest fixes for hometowns the geocoder couldn't place, and write them to
config/<sport>_hometown_corrections.csv (default sport: football).

Run it after geocode_hometowns.py, which writes rosters/<sport>/unmatched_hometowns.csv. Each unmatched
hometown is checked against a list of about 30,000 US towns (downloaded once to .cache/us_cities.csv
from github.com/kelvins/US-Cities-Database):

    fixed       a misspelled town with one close match in its own state ("Tuscon, AZ" -> Tucson)
                a state spelled oddly ("Dallas, T.X.", "Galena, Illinios", "Oconomowoc. Wis.")
                a town with no state that is the only US town of that name ("Ballston Lake" -> NY)
    review      a likely misspelling with more than one possible town, or a town name found in
                several states; the note names the candidates, nothing is changed
    unfixable   a state with no town ("MN", "Alabama"), or a high school name ("Gateway HS")

Only hometowns on the unmatched list are touched, so towns the geocoder already places are never
"corrected" to a neighbour just because the town list lacks them. Rows already marked unfixable, and
hometowns outside the US, are left alone. Every row it writes says why in its note, so the fixes are
easy to find and check ("spelling '...'", "state from the only US town with this name", ...).

    python scripts/suggest_hometown_fixes.py              # add --sport <name> for another sport
    python scripts/suggest_hometown_fixes.py --dry-run    # print what it would change, write nothing
    python scripts/geocode_hometowns.py                   # then geocode again

It's safe to run more than once.
"""
import argparse
import collections
import csv
import difflib
import re
import sys
import urllib.request
from pathlib import Path

from paths import ROOT, add_sport_argument, load_sport

TOWNS_URL = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"
TOWNS_CSV = ROOT / ".cache" / "us_cities.csv"
FIELDS = ["hometown_raw", "city", "state", "country", "query", "status", "note", "players"]

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
# AP-style and other common abbreviations, compared with dots and spaces removed ("N. C." -> "nc")
ABBREV = {
    "ala": "AL", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA", "colo": "CO", "conn": "CT", "del": "DE",
    "fla": "FL", "flo": "FL", "ga": "GA", "ill": "IL", "ind": "IN", "kan": "KS", "kans": "KS", "ky": "KY",
    "md": "MD", "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO", "mont": "MT", "neb": "NE",
    "nebr": "NE", "nev": "NV", "okla": "OK", "ore": "OR", "oreg": "OR", "penn": "PA", "tenn": "TN", "tex": "TX",
    "vt": "VT", "wash": "WA", "was": "WA", "wis": "WI", "wisc": "WI", "wyo": "WY", "wva": "WV",
}
FULL_NAMES = {name.lower(): code for code, name in STATE_NAMES.items()}
STATE_ONLY = set(FULL_NAMES) | {code.lower() for code in STATE_NAMES}
FOREIGN = re.compile(r"australia|england|canada|ontario|alberta|mexico|japan|germany|nigeria|samoa|guam|"
                     r"bahamas|jamaica|\buk$|new zealand|france|brazil", re.I)
SCHOOL = re.compile(r"\b(HS|H\.S\.|High School|Academy|Prep|Preparatory|Charter|Christian|Catholic|Cathedral)\b", re.I)
# Hand-checked exceptions to the rules below
MANUAL = {
    "Anchorage, Ala.": dict(city="Anchorage", state="AK", country="USA", query="Anchorage, AK, USA",
                            status="fixed", note="'Ala.' here means Alaska"),
    "Yosemite": dict(status="review", note="Yosemite: a park, not a town; probably Yosemite HS (Oakhurst, CA)"),
    "Lakin City, Kan.": dict(status="review", note="spelling? 'Lakin City' -> Lakin or Lake City"),
}


def norm(city: str) -> str:
    """lowercase, spelled-out St./Ft./Mt., single spaces: 'St. Paul' and 'Saint Paul' compare equal"""
    c = city.lower().strip().strip(".").strip()
    c = re.sub(r"^st\.? ", "saint ", c)
    c = re.sub(r"^ft\.? ", "fort ", c)
    c = re.sub(r"^mt\.? ", "mount ", c)
    c = re.sub(r"\btwp\.?$", "township", c)
    return re.sub(r"\s+", " ", c)


def load_towns() -> tuple[dict, dict]:
    """state -> {normalized name: name as the list spells it}, and normalized name -> states"""
    if not TOWNS_CSV.exists():
        print(f"Downloading the US town list to {TOWNS_CSV} ...")
        TOWNS_CSV.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(TOWNS_URL, TOWNS_CSV)
    towns, states_of = collections.defaultdict(dict), collections.defaultdict(set)
    with open(TOWNS_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            towns[r["STATE_CODE"]].setdefault(norm(r["CITY"]), r["CITY"])
            states_of[norm(r["CITY"])].add(r["STATE_CODE"])
    return towns, states_of


def state_code(text: str) -> str | None:
    """'Neb.', 'N. C.', 'TX', 'Mihcigan' -> a state code; None for anything else (or a foreign place)"""
    t = text.strip().strip('|"').strip()
    if not t or FOREIGN.search(t):
        return None
    key = re.sub(r"[.\s]", "", t).lower()
    if key.upper() in STATE_NAMES:
        return key.upper()
    if key in ABBREV:
        return ABBREV[key]
    if t.lower().rstrip(".") in FULL_NAMES:
        return FULL_NAMES[t.lower().rstrip(".")]
    close = difflib.get_close_matches(t.lower(), list(FULL_NAMES), n=1, cutoff=0.8)   # "Illnois", "Coloradso"
    return FULL_NAMES[close[0]] if close else None


def split_hometown(raw: str, towns: dict) -> tuple[str, str | None, bool]:
    """raw text -> (town text, state code or None, whether anything followed the town)"""
    t = raw.strip().strip('"').strip()
    town_after_slash = t.startswith("HS City (State)")   # "HS City (State): Dominguez HS / Compton (CA)"
    if re.match(r"^(HS |Hometown)", t):                  # a roster label left in front: "Hometown/...: Omaha, Neb."
        t = re.sub(r"^[^:]{0,60}:\s*", "", t)
    parts = re.split(r"\s*/\s*", t)
    t = (parts[1] if town_after_slash and len(parts) > 1 else parts[0]).strip()   # else "Wilson, NC / Beddingfield HS"
    m = re.match(r"^(.*?)\s*\(([A-Za-z]{2})\)$", t)        # "Compton (CA)"
    if m and m.group(2).upper() in STATE_NAMES:
        t = f"{m.group(1)}, {m.group(2).upper()}"
    if "," in t:
        town, tail = t.rsplit(",", 1)
        return town.strip(), state_code(tail), True
    m = re.match(r"^(.+?)[.,]?\s+([A-Za-z][A-Za-z. ]{0,8})$", t)   # no comma: "Hugo Okla.", "Watertown S.D."
    if m:
        code = state_code(m.group(2))
        if code and norm(m.group(1)) in towns[code]:
            return m.group(1).strip(), code, True
    return t, None, False


def edits(a: str, b: str) -> int:
    """edit distance, counting two swapped neighbouring letters as one edit (Tuscon/Tucson)"""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def closest_town(town: str, code: str, towns: dict) -> tuple[str | None, str | None]:
    """(best match, runner-up) among the state's towns, or (None, None); a runner-up means 'not sure'"""
    c = norm(town)
    if len(c) >= 5:
        limit = 1 if len(c) < 9 else 2
        near = sorted((n for n in towns[code] if abs(len(n) - len(c)) <= limit and edits(c, n) <= limit),
                      key=lambda n: edits(c, n))
        if near:
            return towns[code][near[0]], (towns[code][near[1]] if len(near) > 1 else None)
    close = difflib.get_close_matches(c, list(towns[code]), n=2, cutoff=0.85)
    if not close:
        return None, None
    r1 = difflib.SequenceMatcher(None, c, close[0]).ratio()
    r2 = difflib.SequenceMatcher(None, c, close[1]).ratio() if len(close) > 1 else 0
    sure = r1 - r2 > 0.05 and not (r1 < 0.9 and len(c) < 6)
    return towns[code][close[0]], (None if sure else (towns[code][close[1]] if len(close) > 1 else close[0]))


def suggest(row: dict, towns: dict, states_of: dict) -> tuple[str, dict] | None:
    """(what was done, new field values) for one corrections row, or None to leave it"""
    raw = row["hometown_raw"]
    if raw in MANUAL:
        return "manual", MANUAL[raw]
    town, code, has_tail = split_hometown(raw, towns)
    if not town:
        return None
    fixed = lambda name, st, note: dict(city=name, state=st, country="USA", query=f"{name}, {st}, USA",
                                         status="fixed", note=note)
    if code:
        if norm(town) in towns[code]:
            name = towns[code][norm(town)]
            if (row["city"], row["state"], row["status"]) != (name, code, "fixed"):
                return "fixed: town and state read", fixed(name, code, "town and state read from the text")
            return None
        best, other = closest_town(town, code, towns)
        if best and not other:
            return "fixed: spelling", fixed(best, code, f"spelling '{town}' -> {best}")
        if best:
            alt = f" or {other}" if other != best else ""
            return "review: spelling unsure", dict(status="review", note=f"spelling? '{town}' -> {best}{alt}")
        return None
    if has_tail:                     # something after the town that isn't a US state: foreign or garbled
        return None
    if norm(town).strip(' ,"') in STATE_ONLY:
        return "unfixable: state only", dict(city="", state="", country="", query="", status="unfixable",
                                             note="state only, no town")
    if SCHOOL.search(town):
        return "unfixable: school name", dict(city="", state="", country="", query="", status="unfixable",
                                              note="a school name, not a town")
    states = states_of.get(norm(town), set())
    if len(states) == 1 and len(town) >= 5:
        st = next(iter(states))
        return "fixed: only US town with this name", fixed(towns[st][norm(town)], st,
                                                            "state from the only US town with this name")
    if len(states) > 1 and row["status"] != "fixed":
        return "review: name in several states", dict(status="review",
                                                      note="town name in several states: " + ", ".join(sorted(states)))
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    ap.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    unmatched_csv, corrections_csv = sport.rosters_dir / "unmatched_hometowns.csv", sport.hometown_corrections_csv
    for p in (unmatched_csv, corrections_csv):
        if not p.exists():
            sys.exit(f"{p} not found. Run geocode_hometowns.py first.")

    with open(unmatched_csv, newline="", encoding="utf-8") as fh:
        unmatched = {r["hometown_raw"]: r for r in csv.DictReader(fh)}
    with open(corrections_csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or FIELDS
        rows = list(reader)
    by_raw = {r["hometown_raw"]: r for r in rows}
    for raw, u in unmatched.items():          # an unmatched hometown with no corrections row yet gets one
        if raw not in by_raw:
            row = {f: u.get(f, "") for f in fields}
            row["status"] = row.get("status") or "review"
            rows.append(row)
            by_raw[raw] = row

    towns, states_of = load_towns()
    counts, players = collections.Counter(), collections.Counter()
    for row in rows:
        raw = row["hometown_raw"]
        if raw not in unmatched or row["status"] == "unfixable":
            continue
        if row.get("country") and row["country"] != "USA":
            continue
        result = suggest(row, towns, states_of)
        if not result:
            continue
        what, new = result
        if all(row.get(k) == v for k, v in new.items()):
            continue
        if args.dry_run:
            print(f"{raw!r}: {new.get('query') or new['note']} ({new['status']})")
        row.update(new)
        counts[what] += 1
        players[what] += int(row.get("players") or 0)

    for what in sorted(counts):
        print(f"{what}: {counts[what]} hometowns, {players[what]} players")
    if not counts:
        print("Nothing to change.")
    if args.dry_run or not counts:
        return
    with open(corrections_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {corrections_csv}. Next: python scripts/geocode_hometowns.py, then build_map_data.py.")


if __name__ == "__main__":
    main()
