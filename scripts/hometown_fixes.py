"""This file holds, in order:
    Suggesting hometown fixes (suggest)
    Spelling fixes (spellings)
    Checking the geocoder (check)

Commands:
    python3 scripts/hometown_fixes.py suggest --sport football   # suggesting hometown fixes
    python3 scripts/hometown_fixes.py spellings --sport football   # spelling fixes
    python3 scripts/hometown_fixes.py check --sport football   # checking the geocoder
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so the files here import each other

import geocode as g
from core import add_sport_argument, load_sport, ROOT
from geocode import _region, not_a_place, parse_hometown

# ==============================================================================================================
# Suggesting hometown fixes (suggest)   (was scripts/suggest_hometown_fixes.py)
# ==============================================================================================================

SUGGEST_HOMETOWN_FIXES_DOC = 'Suggest fixes for hometowns the geocoder couldn\'t place, and write them to\nconfig/<sport>/hometown_corrections.csv (default sport: football).\n\nRun it after geocode.py, which writes rosters/<sport>/unmatched_hometowns.csv. Each unmatched\nhometown is checked against a list of about 30,000 US towns (downloaded once to .cache/us_cities.csv\nfrom github.com/kelvins/US-Cities-Database):\n\n    fixed       a misspelled town with one close match in its own state ("Tuscon, AZ" -> Tucson)\n                a state spelled oddly ("Dallas, T.X.", "Galena, Illinios", "Oconomowoc. Wis.")\n                a town with no state that is the only US town of that name ("Ballston Lake" -> NY)\n    review      a likely misspelling with more than one possible town, a town name found in\n                several states, or a town missing from its state whose name (7+ letters) is in just one\n                other state ("Murrieta, GA": CA?); the note names the candidates, nothing is changed\n                a place abroad the parser now reads ("Winnipeg, MB", "Brandon, Manitoba, CA" -> Canada,\n                not California; "Willemstad, Curacao")\n    review      a likely misspelling with more than one possible town, a town name found in\n                several states, or a town missing from its state whose name (7+ letters) is in just one\n                other state ("Murrieta, GA": CA?); the note names the candidates, nothing is changed\n    unfixable   a state with no town ("MN", "Alabama"), a high school name ("Gateway HS"), or text from\n                another column ("R/R", "5-7", "Manager")\n\nOnly hometowns on the unmatched list are touched, so towns the geocoder already places are never\n"corrected" to a neighbour just because the town list lacks them. Rows already marked unfixable, and\nhometowns outside the US, are left alone. Every row it writes says why in its note, so the fixes are\neasy to find and check ("spelling \'...\'", "state from the only US town with this name", ...).\n\n    python scripts/hometown_fixes.py suggest              # add --sport <name> for another sport\n    python scripts/hometown_fixes.py suggest --dry-run    # print what it would change, write nothing\n    python scripts/geocode.py                   # then geocode again\n\nIt\'s safe to run more than once.\n'


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
NEIGHBORS = {k: set(v.split()) for k, v in {
    "AL": "FL GA MS TN", "AZ": "CA CO NM NV UT", "AR": "LA MO MS OK TN TX", "CA": "AZ NV OR", "CO": "AZ KS NE NM OK UT WY",
    "CT": "MA NY RI", "DE": "MD NJ PA", "DC": "MD VA", "FL": "AL GA", "GA": "AL FL NC SC TN", "ID": "MT NV OR UT WA WY",
    "IL": "IN IA KY MO WI", "IN": "IL KY MI OH", "IA": "IL MN MO NE SD WI", "KS": "CO MO NE OK", "KY": "IL IN MO OH TN VA WV",
    "LA": "AR MS TX", "ME": "NH", "MD": "DC DE PA VA WV", "MA": "CT NH NY RI VT", "MI": "IN OH WI", "MN": "IA ND SD WI",
    "MS": "AL AR LA TN", "MO": "AR IL IA KS KY NE OK TN", "MT": "ID ND SD WY", "NE": "CO IA KS MO SD WY",
    "NV": "AZ CA ID OR UT", "NH": "MA ME VT", "NJ": "DE NY PA", "NM": "AZ CO OK TX UT", "NY": "CT MA NJ PA VT",
    "NC": "GA SC TN VA", "ND": "MN MT SD", "OH": "IN KY MI PA WV", "OK": "AR CO KS MO NM TX", "OR": "CA ID NV WA",
    "PA": "DE MD NJ NY OH WV", "RI": "CT MA", "SC": "GA NC", "SD": "IA MN MT ND NE WY", "TN": "AL AR GA KY MO MS NC VA",
    "TX": "AR LA NM OK", "UT": "AZ CO ID NM NV WY", "VT": "MA NH NY", "VA": "DC KY MD NC TN WV", "WA": "ID OR",
    "WV": "KY MD OH PA VA", "WI": "IA IL MI MN", "WY": "CO ID MT NE SD UT"}.items()}
STATE_ONLY = set(FULL_NAMES) | {code.lower() for code in STATE_NAMES}
FOREIGN = re.compile(r"australia|england|canada|ontario|alberta|mexico|japan|germany|nigeria|samoa|guam|"
                     r"bahamas|jamaica|\buk$|new zealand|france|brazil|manitoba|saskatchewan|quebec|"
                     r"british columbia", re.I)
# Countries and provinces the geocoder can put a dot on (its centroid list), filled in by load_places()
PLACES_ABROAD: set[str] = {"Canada"}


def load_places() -> None:
    try:
        from geocode import COUNTRIES
        PLACES_ABROAD.update(COUNTRIES)
    except Exception:            # requests missing, say: Canada alone still works
        pass


def known_abroad(home: dict) -> bool:
    return home["country"] not in ("", "USA") and home["country"] in PLACES_ABROAD
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

    def add(state: str, city: str) -> None:
        if state in STATE_NAMES and city:
            towns[state].setdefault(norm(city), city)
            states_of[norm(city)].add(state)
    with open(TOWNS_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            add(r["STATE_CODE"], r["CITY"])
    # The list above (~30,000 towns, by ZIP code) misses big places such as Thornton CO, so a
    # misspelling of one ("Thorton") found nothing. Add the geocoder's own Census and USGS lists
    # when it has downloaded them (it does on its first run).
    for state, city in geocoder_place_names():
        add(state, city)
    return towns, states_of


def geocoder_place_names():
    """(state, town) from the Census places and county subdivisions and the USGS populated places
    in .cache/, if geocode.py has downloaded them. Nothing is downloaded here."""
    try:
        import geocode as geo
    except Exception:
        return
    files = [(geo.CACHE / geo.GAZ_PLACES, "\t", "usps", "name"), (geo.CACHE / geo.GAZ_COUSUBS, "\t", "usps", "name"),
             (geo.CACHE / "PopulatedPlaces_National_Text.zip", "|", None, None)]
    for path, delim, st_col, name_col in files:
        if not path.exists():
            continue
        try:
            col, rows = geo._read_zip_table(path, delim)
        except Exception:
            continue
        if st_col is None:     # USGS: its column names vary between releases
            name_col = next((h for h in col if h in ("feature_name", "featurename")), None)
            st_col = next((h for h in col if h in ("state_alpha", "state_name")), None)
            if name_col is None or st_col is None:
                continue
        by_name = {v.lower(): k for k, v in STATE_NAMES.items()}
        for row in rows:
            try:
                name = geo._SUFFIXES.sub("", re.sub(r"\s*\(balance\)$", "", row[col[name_col]]))
                st = row[col[st_col]]
                yield by_name.get(st.lower(), st), re.sub(r"\s*\(.*\)$", "", name)
            except IndexError:
                continue


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
    region = _region(t)              # the parser's longer list: "Illi.", "III.", "Virg.", "West Va.", ...
    if region and region["country"] == "USA" and region["state"] in STATE_NAMES:
        return region["state"]
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


def suggest(row: dict, towns: dict, states_of: dict, accept: bool = False) -> tuple[str, dict] | None:
    """(what was done, new field values) for one corrections row, or None to leave it"""
    raw = row["hometown_raw"]
    if raw in MANUAL:
        return "manual", MANUAL[raw]
    if not_a_place(raw):
        return "unfixable: not a hometown", dict(city="", state="", country="", query="", status="unfixable",
                                                 note="not a hometown: bats/throws, a height or a role from another column")
    home = parse_hometown(raw)
    if known_abroad(home):
        new = dict(city=home["city"], state=home["state"], country=home["country"],
                   query=", ".join(x for x in (home["city"], home["state"], home["country"]) if x),
                   status="fixed", note=f"read as {home['country']}")
        if all(row.get(k) == v for k, v in new.items() if k not in ("note", "query")):
            return None
        return "fixed: place abroad", new
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
            # --accept-likely: take the closer of the two when it is clearly closer ("Plattsburg" -> Plattsburgh,
            # not Prattsburgh); a tie ("Eagen": Eagan or Hagen) stays for a person
            if accept and other and other != best and edits(norm(town), norm(best)) < edits(norm(town), norm(other)) \
                    and norm(town)[:1] == norm(best)[:1]:      # "Worchester" -> Dorchester is not a misspelling
                return "fixed: spelling, the closer of two", fixed(best, code, f"spelling '{town}' -> {best} (closer than {other})")
            return "review: spelling unsure", dict(status="review", note=f"spelling? '{town}' -> {best}{alt}")
        # Not in that state, and the name is distinctive and in just one other state: the roster has
        # the state wrong ("Murrieta, GA", "Kankakee, Iowa", "Wappinger Falls, N.J.")
        states = states_of.get(norm(town), set()) - {code}
        if len(states) == 1 and len(norm(town)) >= 7 and not states_of.get(norm(town), set()) & {code}:
            st = next(iter(states))
            # Only a suggestion: many such towns are real neighbourhoods the town list lacks
            # (Rockaway NY, Cardiff CA), so a person decides.
            if accept and (st[0] == code[0] or st in NEIGHBORS.get(code, ())):
                # only a slip of the pen: a state with the same first letter (AR for AK, MD for MS) or a neighbour
                # (Monclova, Mich. -> OH). Farther off it is usually a school or neighbourhood the list lacks
                # ("Magna Vista, VA", "South Norfolk, Va.", "Warren Hills, NJ").
                return "fixed: wrong state", fixed(towns[st][norm(town)], st, f"state {code} -> {st}: no "
                                                   f"{towns[st][norm(town)]} in {code}, the only US town with this name")
            return "review: wrong state?", dict(status="review", note=f"state? no {towns[st][norm(town)]} in "
                                                f"{code}; the only US town with this name is in {st}")
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


def suggest_hometown_fixes_main(argv=None):
    ap = argparse.ArgumentParser(description=SUGGEST_HOMETOWN_FIXES_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    ap.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    ap.add_argument("--accept-likely", action="store_true",
                    help="also fix the two 'review' cases that are nearly always right: a misspelling with one "
                         "clearly closer town, and a distinctive town name found only in another state")
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    unmatched_csv, corrections_csv = sport.rosters_dir / "unmatched_hometowns.csv", sport.hometown_corrections_csv
    if not unmatched_csv.exists():
        sys.exit(f"{unmatched_csv} not found. Run geocode.py first.")

    with open(unmatched_csv, newline="", encoding="utf-8") as fh:
        unmatched = {r["hometown_raw"]: r for r in csv.DictReader(fh)}
    if not unmatched:
        print("Every hometown is placed: nothing to suggest.")
        return
    fields, rows = FIELDS, []
    if corrections_csv.exists():   # the geocoder only writes it once it has a suggestion of its own
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

    load_places()
    try:
        towns, states_of = load_towns()
    except OSError as exc:   # no internet the first time: skip this step, the map build still works
        TOWNS_CSV.unlink(missing_ok=True)
        print(f"Couldn't download the US town list ({exc}); no suggestions this time.")
        return
    counts, players = collections.Counter(), collections.Counter()
    for row in rows:
        raw = row["hometown_raw"]
        if raw not in unmatched or row["status"] == "unfixable" or row.get("source") == "manual":
            continue
        if row.get("country") and row["country"] != "USA" and row["country"] in PLACES_ABROAD \
                and row["status"] == "fixed":
            continue                 # a place abroad already read: the geocoder just has no closer dot for it
        result = suggest(row, towns, states_of, args.accept_likely)
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
    print(f"Saved {corrections_csv}. Next: python scripts/geocode.py, then build.py map.")


# ==============================================================================================================
# Spelling fixes (spellings)   (was scripts/fix_hometown_spellings.py)
# ==============================================================================================================

FIX_HOMETOWN_SPELLINGS_DOC = 'Add fixes for misspelled hometowns to config/<sport>/hometown_corrections.csv (default sport: football).\n\nEach pair below is a misspelling found next to the real town (within 25 km, same state) in the map\ndata, checked by hand. Pairs that are two real places (Los Gatos / Los Altos, Monroe / Montrose,\nGrosse Pointe Farms / Park, ...) are left out.\n\nThe script finds every raw hometown text in the geocoder\'s table, rosters/<sport>/hometowns.csv, that was\nplaced in a misspelled town, and writes a "fixed" row for it in config/<sport>/hometown_corrections.csv.\nRows you already have for those texts are updated; everything else is kept as it is. (Until Oct 27 it\nread players_unique_geocoded.csv, which the geocoder stopped writing on Oct 25, so it found nothing.)\n\nIt also updates hometowns.csv itself, which the geocoder checks before the corrections: each misspelled\nentry gets the real town\'s name and location from the same table. It\'s safe to run more than once.\n\nscripts/pipeline.py runs it in its fix-hometowns step. On its own:\n    python scripts/hometown_fixes.py spellings              # add --sport <name> for another sport\n    python scripts/geocode.py\n    python scripts/build.py map\n'


# Set from --sport in fix_hometown_spellings_main().
CORRECTIONS = LOOKUP = Path()   # hometown_corrections.csv, and hometowns.csv (the geocoder's table of
                                # hometowns it has placed)

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
SPELLING_FIELDS = ["hometown_raw", "city", "state", "country", "query", "status", "note", "players"]


def patch_lookup(wrong: dict) -> tuple[int, int]:
    """The geocoder keeps every hometown it has placed in rosters/<sport>/hometowns.csv (keyed by the raw text)
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


def fix_hometown_spellings_main(argv=None):
    global CORRECTIONS, LOOKUP
    ap = argparse.ArgumentParser(description=FIX_HOMETOWN_SPELLINGS_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    sport = load_sport(ap.parse_args(argv).sport)
    CORRECTIONS, LOOKUP = sport.hometown_corrections_csv, sport.rosters_dir / "hometowns.csv"
    if not LOOKUP.exists():
        sys.exit(f"{LOOKUP} not found. Run geocode.py first.")
    wrong = {(place, bad.lower()): good for place, bad, good in FIXES}

    found = {}   # raw hometown text -> (place, bad, good, players)
    with open(LOOKUP, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("school") or r.get("source") == "manual":
                continue        # per-school guesses repeat the main row; hand-placed rows are left alone
            place = r.get("state") or r.get("country") or ""
            key = (place, (r.get("city") or "").strip().lower())
            if key in wrong and r.get("hometown"):
                raw = r["hometown"]
                prev = found.get(raw)
                found[raw] = (place, r["city"], wrong[key], (prev[3] if prev else 0) + int(r.get("players") or 0))

    fields, rows = SPELLING_FIELDS, []
    if CORRECTIONS.exists():
        with open(CORRECTIONS, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or SPELLING_FIELDS
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

    if added or updated:
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
    if missing and len(missing) < len(FIXES):
        print(f"{len(missing)} of the {len(FIXES)} known misspellings aren't in this sport's hometowns "
              "(already fixed, or never seen)")
    if added or updated or patched or dropped:
        print("next: python scripts/geocode.py, then scripts/build.py map")


# ==============================================================================================================
# Checking the geocoder (check)   (was scripts/check_geocoder.py)
# ==============================================================================================================

CHECK_GEOCODER_DOC = """Check which geocoder version is in this folder and test a few towns that didn't place.

    python scripts/hometown_fixes.py check
"""


def check_geocoder_main(argv=None):

    print("\nLoading place data (about a minute)...")
    gaz = g.Gazetteer()
    print(f"Census places: {len(gaz.places):,}   USGS places: {len(gaz.gnis):,}   counties: {len(gaz.counties):,}")
    for name, state in [("Rabun Gap", "GA"), ("Ellenwood", "GA"), ("Loxahatchee", "FL"), ("Mililani", "HI"),
                        ("Hallandale", "FL"), ("Indian Land", "SC"), ("Cypress", "TX")]:
        print(f"  {name}, {state}: {gaz.lookup_us(name, state)}")
    print("\nUSGS keys that start with 'rabun' or 'ellenwood':",
          [k for k in gaz.gnis if k[0].startswith(("rabun", "ellenwood"))][:10])
    print("Census keys that start with 'rabun':", [k for k in gaz.places if k[0].startswith("rabun")][:10])


COMMANDS = {"suggest": suggest_hometown_fixes_main, "spellings": fix_hometown_spellings_main, "check": check_geocoder_main}


def command_line(argv=None) -> int:
    """python3 scripts/hometown_fixes.py <command> [options]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        sys.argv[0] = f"{Path(sys.argv[0]).name} {argv[0]}"     # so --help says "build.py map"
        return COMMANDS[argv[0]](argv[1:]) or 0
    sys.exit("commands: " + ", ".join(COMMANDS) + " (add --help to one for its options)")


if __name__ == "__main__":
    raise SystemExit(command_line())
