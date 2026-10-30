"""This file holds, in order:
    The map data (map)
    Campus locations (locations)
    Frozen class years (frozen)
    Checking the rosters (check)
    Copying football's pages to every sport (sync)

Commands:
    python3 scripts/build.py map --sport football   # the map data
    python3 scripts/build.py locations --sport football   # campus locations
    python3 scripts/build.py frozen --sport football   # frozen class years
    python3 scripts/build.py check --sport football   # checking the rosters
    python3 scripts/build.py sync --check      # copying football's pages to every sport
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so the files here import each other

import sidearm
from core import (
    add_sport_argument,
    available_sports,
    build_unique,
    d1_schools,
    is_major,
    LEVELS,
    Levels,
    load_schools,
    load_sport,
    Notes,
    players,
    read_csv,
    ROOT,
    season_files,
    season_rows,
)
from sidearm import clean_name, load_known_colleges, sort_schools

# ==============================================================================================================
# The map data (map)   (was scripts/build_map_data.py)
# ==============================================================================================================

BUILD_MAP_DATA_DOC = """Pack a sport's players into the JSON its pages (docs/<sport>/) load.

    python scripts/build.py map                # rosters/football/ -> docs/football/map_data.json
    python scripts/build.py map --sport lacrosse-mens
    python scripts/build.py map <input.csv> <output.json>   # a geocoded CSV instead (older runs)

By default it reads the season files (rosters_<season>.csv), makes one row per player per school from
them, and places each hometown with hometowns.csv from geocode.py, so run the geocoder first.

Run it again whenever you re-scrape or re-geocode, then commit docs/<sport>/map_data.json.
Dot colors come from config/shared/school_colors.csv (school, primary, secondary hex colors), shared by every
sport; position groups, divisions and their labels from config/<sport>/settings.json.

Transfers: many roster pages never list a previous school, so a player counts as a transfer if
  1. the roster lists a college as his previous school, or
  2. he was on another college's roster in this data first (same name and hometown), or
  3. he's new to a roster whose previous season is also (nearly fully) in the data, and he's already a junior, senior or grad.
(2) also records the school he came from, so the site can show where transfers moved.

Every other transfer gets the level of the school he came from (scripts/core.py, with the colleges in
config/<sport>/schools.csv): a D1 school he wasn't found on, Division II or III, NAIA, junior
college, or unknown (no school named, or a name that fits two levels).

It reads frozen_class_seasons.csv from rosters/<sport>/ and writes transfer_levels.csv there.
"""

# The scraper's rules for telling a previous college from a high school, so both steps agree.

# Position groups come from the sport's settings (config/<sport>/settings.json): the groups, the roster
# abbreviations in each, words a spelled-out position starts with, and the group for anything else.
POS_GROUPS: list[str] = []
ABBR: dict[str, str] = {}
WORDS: list[tuple[str, str]] = []
FALLBACK = ""


def use_positions(sport) -> None:
    global POS_GROUPS, ABBR, WORDS, FALLBACK
    POS_GROUPS = list(sport.position_groups)
    ABBR = {a: g for g, v in sport.position_abbreviations.items() for a in v.split()}
    WORDS = [tuple(w) for w in sport.position_words]
    FALLBACK = sport.position_fallback or POS_GROUPS[-1]


def pos_group(p: str) -> int:
    p = re.sub(r"^pos\.?:\s*", "", (p or "").strip().lower())
    first = re.split(r"[\s,/-]+", p)[0] if p else ""
    if p in ABBR:
        g = ABBR[p]
    elif first in ABBR:
        g = ABBR[first]
    elif p.startswith("defensive") and "DEF" in POS_GROUPS:   # football: "Defensive Line", "Defensive Back"
        g = ("DL" if re.search(r"line|end|tackle", p) else "DB" if "back" in p else "DEF")
    else:
        g = next((grp for w, grp in WORDS if p.startswith(w)), FALLBACK)
    return POS_GROUPS.index(g) if g in POS_GROUPS else POS_GROUPS.index(FALLBACK)


def previous_college(prev: str, high_school: str) -> str:
    """The college the roster says he came from, or "". Uses the scraper's sort_schools(), so a high school
    filed as "previous school" ('Pickerington Central', 'Menard' next to 'Menard HS', 'IMG Academy') isn't one,
    and a major in that field ('Business', 'Sport Management' on Valparaiso's roster) isn't either."""
    p = sort_schools({"high_school": high_school or "", "previous_school": prev or ""})["previous_school"]
    return "" if is_major(p) else p


def is_transfer(prev: str, high_school: str) -> int:
    """1 if the roster names a college he came from."""
    return int(bool(previous_college(prev, high_school)))


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def person(r: dict) -> tuple:
    """Name + hometown, loose enough to match one player across two schools' rosters."""
    name = clean_name(r["name"])        # the scraper cleans names; this covers rosters cleaned by an older version
    name = re.sub(r"[^a-z]", "", _SUFFIX.sub("", name.lower()))
    city = re.sub(r"[^a-z]", "", (r.get("home_city") or "").lower())
    return name, city, r.get("home_state") or r.get("home_country") or ""


def find_moves(rows: list[dict]) -> dict[int, str]:
    """Row index -> the school he played for before, for players found on two schools' rosters in turn.

    Only players with a name and hometown are matched. If the same name + hometown is on two rosters
    in the same season, it's probably two different people, so that pair is left alone."""
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        key = person(r)
        if key[0] and key[1]:
            groups.setdefault(key, []).append(i)
    came_from = {}
    for idx in groups.values():
        if len({rows[i]["school"] for i in idx}) < 2:
            continue
        idx.sort(key=lambda i: (int(rows[i]["first_season"]), int(rows[i]["last_season"])))
        for a, b in zip(idx, idx[1:]):
            ra, rb = rows[a], rows[b]
            if (ra["school"] != rb["school"] and int(rb["first_season"]) > int(ra["first_season"])
                    and int(rb["first_season"]) >= int(ra["last_season"])):
                came_from[b] = ra["school"]
    return came_from


_HS_WORDS = re.compile(r"\b(high\s+school|h\s*\.\s*s\s*\.?|hs)(?=\W|$)", re.I)


def hs_key(name: str) -> str:
    """One key for spellings of the same high school: "Cedar Park HS", "Cedar Park High School",
    "Cedar Park H.S." -> "cedar park hs". Only the "high school" wording and punctuation are ignored,
    so "Cedar Park" and "Cedar Park HS" stay apart (they could be different schools)."""
    s = _HS_WORDS.sub(" hs ", (name or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s.replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


def hs_spellings(rows: list[dict]) -> dict[str, str]:
    """hs_key -> the spelling most players' rosters use (ties go to the shorter, then alphabetical)."""
    counts: dict[str, Counter] = {}
    for r in rows:
        hs = (r["high_school"] or "").strip()
        counts.setdefault(hs_key(hs), Counter())[hs] += 1
    return {k: min(c, key=lambda s: (-c[s], len(s), s)) for k, c in counts.items()}


UPPERCLASS = {"JR", "SR", "GR"}


def roster_seasons(rows: list[dict]) -> Counter:
    """(school, season) -> how many players that season's roster has in the data."""
    size = Counter()
    for r in rows:
        seasons = (r.get("seasons") or "").split() or range(int(r["first_season"]), int(r["last_season"]) + 1)
        size.update((r["school"], int(y)) for y in seasons)
    return size


def load_frozen_class_seasons(path) -> set[tuple[str, int]]:
    """(school, season) pairs whose roster pages show the wrong class year (made by build.py frozen)."""
    if not Path(path).exists():
        print(f"{path} not found; run build.py frozen first, or the class-year rule trusts every season")
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["school"], int(r["season"])) for r in csv.DictReader(fh)}


def arrived_as_upperclassman(r: dict, size: Counter, prev_season: dict[int, int],
                             frozen: set[tuple[str, int]] = frozenset(), thin: int = 40) -> bool:
    """New to this roster, and already a junior/senior/grad: almost always a transfer (junior college,
    Division II, or a D1 school this data doesn't cover). Only trusted when this school's roster for the
    season before is in the data and close to full (at least `thin` players, the sport's thin_roster): a
    failed or partial scrape (Ohio State 2016 has 3 players) would make every returning junior look new.
    Also skipped for seasons whose class labels can't be trusted: some archives show each player's later
    class (Ohio State 2017-2022), which makes freshmen look like juniors."""
    code = (r.get("first_class") or "").upper().replace("R-", "")
    if code not in UPPERCLASS:
        return False
    first = int(r["first_season"])
    if (r["school"], first) in frozen:
        return False
    before = prev_season.get(first)
    if before is None:
        return False
    n_before, n_now = size[(r["school"], before)], size[(r["school"], first)]
    return n_before >= thin and n_before >= 0.6 * n_now


HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_colors(path):
    """school -> (primary, secondary) hex colors."""
    out = {}
    if not Path(path).exists():
        print(f"{path} not found; all dots will be gray")
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        color_rows = list(csv.DictReader(fh))
    for r in color_rows:
        prim, sec = (r.get("primary") or "").strip(), (r.get("secondary") or "").strip()
        if not HEX.match(prim):
            print(f"bad primary color for {r['school']}: {prim!r}")
            continue
        out[r["school"].strip()] = (prim.upper(), sec.upper() if HEX.match(sec) else "#FFFFFF")
    return out


def placed_players(sport) -> list[dict]:
    """One row per player per school from the season files, with each hometown placed from hometowns.csv
    (geocode.py): its corrected city/state/country, lat/lon and precision. A town given without
    a state is looked up for the player's school first, since the geocoder guesses those per school."""
    path = sport.rosters_dir / "hometowns.csv"
    if not path.exists():
        sys.exit(f"{path} not found: run geocode.py first.")
    with open(path, newline="", encoding="utf-8") as fh:
        places = {(r.get("hometown", ""), r.get("school", "")): r for r in csv.DictReader(fh)}
    rows, unplaced = players(sport.rosters_dir), 0
    for r in rows:
        raw = r.get("hometown", "")
        p = places.get((raw, r["school"])) or places.get((raw, ""))
        if p is None:
            unplaced += bool(raw.strip())
            p = {}
        else:
            r["home_city"], r["home_state"], r["home_country"] = p.get("city", ""), p.get("state", ""), p.get("country", "")
            src = p.get("source", "")
            if src.startswith("census_guess_") and not r["home_state"]:   # as the geocoder labels a guessed state
                r["home_state"], r["home_country"] = src.rsplit("_", 1)[1], "USA"
        r["home_lat"], r["home_lon"] = p.get("lat", ""), p.get("lon", "")
        r["geo_source"], r["geo_precision"] = p.get("source", ""), p.get("precision", "")
    if unplaced:
        print(f"{unplaced} players have a hometown that isn't in {path.name} yet: run geocode.py again")
    return rows


# ---- the players' columns, packed (Oct 28) ----
# Football's map_data.json was 15.5 MB, almost all of it the players' columns written out in full. Columns that
# repeat (school, first season, division: the players are in school order) are written as runs, the last season as
# the number of seasons after the first, and the columns that are mostly empty (transfer, previous school, level
# of the previous school) as only the players they apply to. docs/common.js (loadData) unpacks them; unpack_players
# below does the same in Python. A file without "packed" is in the old, plain form.
PACKED = 1
SPLIT_ABOVE = 150_000     # players; above this the D1 schools' players get a file of their own


def _runs(a):
    out = []
    for v in a:
        if out and out[-2] == v:
            out[-1] += 1
        else:
            out += [v, 1]
    return out


def _unruns(a):
    out = []
    for i in range(0, len(a), 2):
        out += [a[i]] * a[i + 1]
    return out


def _sparse(a, empty):
    """[gap, value, gap, value, ...]: gap = players since the last one listed (first: its index)."""
    out, last = [], -1
    for i, v in enumerate(a):
        if v != empty:
            out += [i - last - 1, v]
            last = i
    return out


def _unsparse(a, n, empty):
    out, i = [empty] * n, -1
    for k in range(0, len(a), 2):
        i += a[k] + 1
        out[i] = a[k + 1]
    return out


def pack_players(P: dict) -> dict:
    n = len(P["s"])
    return {"packed": PACKED, "n": n, "s": _runs(P["s"]), "f": _runs(P["f"]), "d": _runs(P["d"]),
            "len": [l - f for f, l in zip(P["f"], P["l"])], "p": P["p"], "t": P["t"], "h": P["h"],
            "x": _sparse(P["x"], 0), "o": _sparse(P["o"], -1), "v": _sparse(P["v"], 0)}


def unpack_players(P: dict) -> dict:
    if not P.get("packed"):
        return P
    n = P["n"]
    f = _unruns(P["f"])
    return {"s": _unruns(P["s"]), "t": P["t"], "p": P["p"], "f": f, "l": [a + b for a, b in zip(f, P["len"])],
            "x": _unsparse(P["x"], n, 0), "o": _unsparse(P["o"], n, -1), "v": _unsparse(P["v"], n, 0),
            "d": _unruns(P["d"]), "h": P["h"]}



def make_map_data(src, dst, sport):
    sidearm.configure(sport)     # the sport's junior colleges, for telling a college from a high school
    use_positions(sport)
    if src:
        with open(src, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    else:
        rows = placed_players(sport)
    if sport.schools_csv.exists():
        load_known_colleges(d1_schools(sport.schools_csv))   # so "Wake Forest" counts as a college
    levels = Levels.load(sport)
    schools = sorted({r["school"] for r in rows})
    sidx = {s: i for i, s in enumerate(schools)}
    conf = {}
    div_now = {}   # school -> (newest first_season, division that season) = the school's current division
    for r in rows:
        conf[r["school"]] = r["current_conference"]
        fs = int(r["first_season"])
        if fs >= div_now.get(r["school"], (0, ""))[0]:
            div_now[r["school"]] = (fs, r["division_first_season"])
    confs = sorted(set(conf.values()))
    # The sport's divisions, as its schools file writes them (football: FBS, FCS, D2, ...; lacrosse: D1, D2, ...)
    divs = list(sport.d1_divisions) + [d for d in sport.other_divisions if d not in sport.d1_divisions]
    odd = sorted({r["division_first_season"] for r in rows if r["division_first_season"] not in divs})
    if odd:
        print(f"divisions not in config/{sport.name}/settings.json (shown as {divs[0]}):", ", ".join(o or "(blank)" for o in odd))
    notes = Notes(sport.rosters_dir / "notes_build.txt")
    colors = load_colors(sport.colors_csv)
    notes.listed("no colors in config/shared/school_colors.csv for", [x for x in schools if x not in colors])
    prec_codes = {"city": 0, "city_guess": 1, "county": 2, "region": 3, "country": 3}

    came_from = find_moves(rows)
    have = roster_seasons(rows)
    all_seasons = sorted({y for _, y in have})
    thin = sorted(f"{s} {y}" for (s, y), n in have.items() if n < sport.thin_roster)
    notes.listed(f"thin rosters (fewer than {sport.thin_roster} players; the class-year transfer rule skips the season "
                 "after each)", thin)
    prev_season = dict(zip(all_seasons[1:], all_seasons))   # a season missing from the data is skipped (football: 2021 -> 2019)
    frozen = load_frozen_class_seasons(sport.rosters_dir / "frozen_class_seasons.csv")
    if frozen:
        print(f"{len(frozen)} school-seasons with untrustworthy class years (the class-year transfer rule skips them)")
    how = Counter()
    level_count, matched = Counter(), Counter()

    towns, tidx = [], {}
    hs_tab, hidx = [], {}
    hs_name = hs_spellings(rows)   # hs_key -> the spelling shown on the site
    spellings = len({(r["high_school"] or "").strip() for r in rows})
    if spellings > len(hs_name):
        print(f"high schools: {spellings} spellings merged into {len(hs_name)} names ('HS' / 'High School' / 'H.S.')")
    unclean = sum(clean_name(r["name"]) != (r["name"] or "").strip() for r in rows)
    if unclean:
        print(f"cleaned {unclean} player names here; run scrape_rosters.py --recombine and geocode again"
              " to clean them in the roster files too")
    P = {k: [] for k in ("s", "t", "p", "f", "l", "x", "o", "v", "d", "h", "n")}
    for i, r in enumerate(rows):
        if r["home_lat"]:
            key = (round(float(r["home_lat"]), 4), round(float(r["home_lon"]), 4))
            if key not in tidx:
                st = r["home_state"] or r["home_country"]
                label = f'{r["home_city"]}, {st}' if r["home_city"] else st
                tidx[key] = len(towns)
                towns.append([key[0], key[1], label, prec_codes.get(r["geo_precision"], 3)])
            t = tidx[key]
        else:
            t = -1
        hs = hs_name[hs_key((r["high_school"] or "").strip())]
        if hs not in hidx:
            hidx[hs] = len(hs_tab)
            hs_tab.append(hs)
        prev = previous_college(r["previous_school"], r["high_school"])
        if prev and sport.transfer_needs_known_college and levels.level(prev, int(r["first_season"]) - 1)[0] == "unknown":
            prev = ""                                  # hockey: a junior or prep team, not a college
        listed, moved, upper = (int(bool(prev)), i in came_from,
                                arrived_as_upperclassman(r, have, prev_season, frozen, sport.thin_roster))
        transfer = int(listed or moved or upper)
        how["previous school on the roster"] += listed
        how["found on an earlier roster in the data"] += moved and not listed
        how["arrived as a junior/senior/grad"] += upper and not (listed or moved)
        if (not transfer and frozen and (r["school"], int(r["first_season"])) in frozen
                and arrived_as_upperclassman(r, have, prev_season, thin=sport.thin_roster)):
            how["not counted: class year untrustworthy that season"] += 1
        P["s"].append(sidx[r["school"]])
        P["t"].append(t)
        P["p"].append(pos_group(r["position"]))
        P["f"].append(int(r["first_season"]) - 2000)
        P["l"].append(int(r["last_season"]) - 2000)
        P["x"].append(transfer)
        P["o"].append(sidx[came_from[i]] if i in came_from else -1)   # the D1 school he transferred from, if known
        # level of the school a transfer with no line came from: LEVELS index + 1; 0 = not one of those
        lvl = ""
        if transfer and i not in came_from:
            lvl, school = levels.level(prev, int(r["first_season"]) - 1) if prev else ("unknown", "")
            level_count[lvl] += 1
            matched[(lvl, school or prev)] += 1
        P["v"].append(LEVELS.index(lvl) + 1 if lvl else 0)
        P["d"].append(divs.index(r["division_first_season"]) if r["division_first_season"] in divs else 0)
        P["h"].append(hidx[hs])
        P["n"].append(clean_name(r["name"]))
    out = {
        "schools": [[s, confs.index(conf[s]), divs.index(div_now[s][1]) if div_now[s][1] in divs else 0,
                     *colors.get(s, ("#777777", "#FFFFFF"))] for s in schools],
        "confs": confs, "divs": divs, "pos": POS_GROUPS, "towns": towns, "hs": hs_tab, "levels": LEVELS,
        # For the pages: the sport's name, which divisions are D1, and how divisions and positions are written
        "sport": sport.label or sport.name, "d1": list(sport.d1_divisions),
        "divLabels": {d: sport.division_label(d) for d in divs}, "posLabels": dict(sport.position_labels),
    }
    # Big sports (football, baseball) come in two files: map_data.json with the D1 schools' players, which the dot
    # map opens on, and map_data_more.json with everyone else, which it loads when a view needs them (Oct 28).
    # The players are put D1 schools first; names.txt follows the same order.
    if len(P["s"]) > SPLIT_ABOVE:
        d1_school = [div_now[sc][1] in sport.d1_divisions for sc in schools]
        order = sorted(range(len(P["s"])), key=lambda k: (not d1_school[P["s"][k]], k))
        P = {key: [col[k] for k in order] for key, col in P.items()}
        cut = sum(d1_school[sc] for sc in P["s"])
        first = {k: v[:cut] for k, v in P.items() if k != "n"}
        rest = {k: v[cut:] for k, v in P.items() if k != "n"}
        out["players"], out["more"] = pack_players(first), ["map_data_more.json"]
        with open(Path(dst).with_name("map_data_more.json"), "w", encoding="utf-8") as fh:
            json.dump({"players": pack_players(rest)}, fh, separators=(",", ":"))
    else:
        out["players"] = pack_players({k: v for k, v in P.items() if k != "n"})
        Path(dst).with_name("map_data_more.json").unlink(missing_ok=True)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    # The players' names, one per line in the same order (Oct 28: a file of their own, since only the dot map
    # uses them; the heatmap and transfer pages no longer download them, and the dot map draws before they arrive)
    Path(dst).with_name("names.txt").write_text("\n".join(n.replace("\n", " ") for n in P["n"]), encoding="utf-8")
    # The numbers on the front page (docs/index.html reads these instead of figures typed in by hand)
    seasons = sorted({f for f in P["f"]} | {l for l in P["l"]})
    summary = {"sport": sport.label or sport.name, "players": len(P["s"]), "schools": len(schools),
               "hometowns": len(towns), "first": 2000 + seasons[0] if seasons else None,
               "last": 2000 + seasons[-1] if seasons else None}
    Path(dst).with_name("summary.json").write_text(json.dumps(summary), encoding="utf-8")
    print(f"{len(rows)} players, {len(towns)} hometowns, {len(schools)} schools -> {dst}")
    print("position groups:", Counter(POS_GROUPS[i] for i in P["p"]).most_common())
    skipped = how.pop("not counted: class year untrustworthy that season", 0)
    print("transfers:", sum(P["x"]), "| counted because:", dict(how))
    if skipped:
        print(f"not counted as transfers: {skipped} newcomers listed as juniors or older in a season with untrustworthy class years")
    print("moves between two schools in the data (a known previous school):", sum(o >= 0 for o in P["o"]))
    print("other transfers by the level of the school they came from:",
          ", ".join(f"{lv} {level_count[lv]}" for lv in LEVELS))
    if matched:
        write_levels_report(matched, sport.rosters_dir / "transfer_levels.csv")


def write_levels_report(matched: Counter, path) -> None:
    """Every previous-school name of a transfer without a line, with the level it got, for checking by hand."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["level", "school", "players"])
        w.writerows([lv, name, n] for (lv, name), n in sorted(matched.items(), key=lambda x: (LEVELS.index(x[0][0]), -x[1], x[0][1])))
    print(f"previous schools and their levels -> {path}")


def build_map_data_main(argv=None):
    ap = argparse.ArgumentParser(description=BUILD_MAP_DATA_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, metavar="input.csv output.json",
                    help="default: the season files and hometowns.csv in rosters/<sport>/ -> docs/<sport>/map_data.json")
    add_sport_argument(ap)
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    if len(args.files) not in (0, 2):
        sys.exit(BUILD_MAP_DATA_DOC)
    src, dst = args.files or (None, sport.site_dir / "map_data.json")
    make_map_data(src, dst, sport)


# ==============================================================================================================
# Campus locations (locations)   (was scripts/build_school_locations.py)
# ==============================================================================================================

BUILD_SCHOOL_LOCATIONS_DOC = """Pack config/shared/school_locations.csv into docs/<sport>/school_locations.json for the website.

Each school's campus city, state and coordinates. The map pages use it for the campus marker,
home-state share and distance from campus. The CSV is shared by every sport; each sport's JSON only
holds that sport's schools (from config/<sport>/schools.csv) when that file exists. Run it after
editing the CSV:

    python scripts/build.py locations                 # football
    python scripts/build.py locations --sport mens-basketball
"""


def build_school_locations_main(argv=None):
    ap = argparse.ArgumentParser(description=BUILD_SCHOOL_LOCATIONS_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    sport = load_sport(ap.parse_args(argv).sport)
    wanted = {s["school"] for s in load_schools(sport.schools_csv)} if sport.schools_csv.exists() else None
    schools, bad = {}, []
    with sport.locations_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if wanted is None or row["school"] in wanted:
                try:
                    schools[row["school"]] = [row["city"], row["state"], float(row["lat"]), float(row["lon"])]
                except (TypeError, ValueError):     # a blank or typed-wrong lat/lon: skip that school, not the file
                    bad.append(row["school"])
    if bad:
        print(f"lat/lon not a number in {sport.locations_csv.name} (left out):", ", ".join(bad))
    out = sport.site_dir / "school_locations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"fields": ["city", "state", "lat", "lon"], "schools": schools}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(schools)} schools to {out.relative_to(ROOT)}")
    if wanted:
        missing = sorted(wanted - set(schools))
        if missing:
            Notes(sport.rosters_dir / "notes_locations.txt").listed(
                f"no campus in {sport.locations_csv.relative_to(ROOT)} for", missing)


# ==============================================================================================================
# Frozen class years (frozen)   (was scripts/check_frozen_classes.py)
# ==============================================================================================================

CHECK_FROZEN_CLASSES_DOC = 'Find school-seasons whose class labels don\'t advance from year to year.\n\nSome schools\' archive roster pages show every player\'s class as of a later\nseason (Ohio State 2017-2022, for one). Newcomers then look like juniors or\nolder, and build.py map\'s "arrived as a junior or older" rule reads them\nas transfers. This script finds those seasons.\n\nFor each pair of a school\'s consecutive seasons in the data (2019 -> 2021\ncounts as consecutive), it takes the players on both rosters and checks\nwhether their class moved up. Two measures are printed:\n\n  all     every returning player\n  no_sr   only players who were FR, SO or JR the season before, so seniors and\n          grads repeating a year (often the COVID free year) don\'t count\n\nA frozen archive scores ~90-100% on both. A season inflated by COVID repeats\nscores high on "all" but normal on "no_sr".\n\nRun:  python scripts/build.py frozen          # add --sport <name> for another sport\nReads the season files (rosters_<season>.csv) in rosters/<sport>/ and writes rosters/<sport>/frozen_class_seasons.csv\n(school, season, share) for the build.\n'


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
    """Every row of every season file (rosters_<season>.csv)."""
    return season_rows(rosters)


def check_frozen_classes_main(argv=None):
    ap = argparse.ArgumentParser(description=CHECK_FROZEN_CLASSES_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
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
        # Not an error: a new or small sport may have no pair to judge yet. Write an empty list, so the
        # build knows this step ran and trusts every season's class years.
        print("No season pairs had enough returning players to compare; no seasons flagged.")

    print(f"{len(results)} season pairs compared")
    if results:
        print(f"median stuck share, all players: {statistics.median(r[3] for r in results):.0%}")
    young_shares = [r[5] for r in results if r[5] is not None]
    if young_shares:   # none when every school has fewer than frozen_min_pairs returning underclassmen
        print(f"median stuck share, no SR/GR:    {statistics.median(young_shares):.0%}")
    if unreadable:
        top = sorted(unreadable.items(), key=lambda kv: -kv[1])[:10]
        print("class labels it couldn't read (ignored):", top)

    # The details (reference schools, likely COVID repeats, every flagged season) go to notes_frozen.txt, not the
    # terminal; frozen_class_seasons.csv has the flagged seasons too.
    details = []
    watched = [r for r in results if r[0] in WATCH]
    if watched:
        details.append("Reference schools (prev -> season: all / no SR-GR):")
    for school, prev, cur, sa, na, sy, ny in sorted(watched, key=lambda r: (r[0], r[2])):
        young_txt = f"{sy:4.0%} of {ny:3}" if sy is not None else f"  -- only {ny} underclassmen"
        details.append(f"  {school:12} {prev}->{cur}  {sa:4.0%} of {na:3}  /  {young_txt}")
    covid = [r for r in results if r[3] >= CUTOFF and r[5] is not None and r[5] < CUTOFF]
    details.append(f"\nPairs at or above {CUTOFF:.0%} on 'all' but below it once SR/GR are left out"
                   " (likely COVID repeats, not frozen):")
    details += [f"  {school} {prev}->{cur}  {sa:.0%} -> {sy:.0%}"
                for school, prev, cur, sa, na, sy, ny in sorted(covid, key=lambda r: -r[3])] or ["  none"]

    flagged = {}
    for school, prev, cur, sa, na, sy, ny in results:
        measure = sy if sy is not None else sa
        if measure >= CUTOFF:
            for key in ((school, prev), (school, cur)):
                flagged[key] = max(measure, flagged.get(key, 0))

    details.append(f"\n{len(flagged)} school-seasons flagged as frozen (stuck share >= {CUTOFF:.0%};"
                   " underclassmen only when there are enough of them):")
    details += [f"  {school} {season}  {sh:.0%}" for (school, season), sh in sorted(flagged.items())]
    notes = out.parent / "notes_frozen.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text("\n".join(details) + "\n", encoding="utf-8")
    per_season = defaultdict(int)
    for _, season in flagged:
        per_season[season] += 1
    print(f"{len(flagged)} school-seasons flagged as frozen; by season: {dict(sorted(per_season.items()))}"
          f" (details in {notes.name})")

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["school", "season", "share"])
        for (school, season), sh in sorted(flagged.items()):
            w.writerow([school, season, f"{sh:.3f}"])
    print(f"\nwrote {out}")


# ==============================================================================================================
# Checking the rosters (check)   (was scripts/check_rosters.py)
# ==============================================================================================================

CHECK_ROSTERS_DOC = """Check a sport's saved rosters after a run, and print where it stands.

    python scripts/build.py check --sport softball

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


def check_rosters_main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=CHECK_ROSTERS_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    bios: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
    for r in rows:
        k = (r["school"], int(r["season"]))
        url.setdefault(k, r.get("roster_url", ""))
        names[k].add(name_key(r["name"]))
        classes[k][name_key(r["name"])] = (r.get("class_norm") or "").upper()
        if r.get("bio_url"):
            bios[k][name_key(r["name"])] = r["bio_url"].replace(":443/", "/").split("?")[0].rstrip("/")
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
                # The same player pages (bio links) as the season before: the scraper read the other season's
                # page, a real error. Different bio pages: the school's own page for this season repeats last
                # season's roster (often after COVID, when class years weren't moved up). Rescraping can't fix
                # that, so it is only counted (Oct 30: 8 of 37 flagged were the first kind).
                ba, bb = bios[(school, prev)], bios[(school, cur)]
                with_bio = [n for n in both if n in ba and n in bb]
                same_page = (len(with_bio) >= 0.5 * len(both)
                             and sum(ba[n] == bb[n] for n in with_bio) >= 0.9 * len(with_bio)) \
                    or (url[(school, cur)] and url[(school, cur)].rstrip("/") == url[(school, prev)].rstrip("/"))
                detail = f"{len(both) / len(b):.0%} same names and {same_class:.0%} same class years as {prev}"
                if same_page:
                    found.append(("repeated", school, cur, size[(school, cur)], detail + ", same player pages",
                                  url[(school, cur)]))
                else:
                    found.append(("school_copy", school, cur, size[(school, cur)],
                                  detail + " (the school's own page for this season)", url[(school, cur)]))
    for kind, title in (("oversized", f"Rosters at least {OVERSIZED:g}x the school's usual size"),
                        ("repeated", "Rosters read from another season's page (same players and player pages as "
                                     "the season before)")):
        hits = sorted((f for f in found if f[0] == kind), key=lambda f: (f[1], f[2]))
        print(f"\n{title}: {len(hits) or 'none'}")
        for _, school, season, n, detail, _u in hits[:40]:
            print(f"  {school} {season}: {n} players ({detail})")
        if len(hits) > 40:
            print(f"  ... and {len(hits) - 40} more in roster_checks.csv")
    copies = sum(1 for f in found if f[0] == "school_copy")
    if copies:
        print(f"\n{copies} more school-seasons repeat the season before on the school's own page (class years not "
              "moved up); rescraping can't change them. Listed in roster_checks.csv as school_copy.")
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


# ==============================================================================================================
# Copying football's pages to every sport (sync)   (was scripts/sync_pages.py)
# ==============================================================================================================

SYNC_PAGES_DOC = 'Copy football\'s map pages to every other sport, so a fix made once reaches all of them.\n\n    python3 scripts/build.py sync           # write docs/<sport>/players-*.html for every sport but football\n    python3 scripts/build.py sync --check   # only say which pages differ from football\'s beyond their own words\n\ndocs/football/players-dotmap.html, players-heatmap.html and players-transfers.html are the masters (and\nstaff-moves.html and staff-directory.html, which are copied as they are): edit those,\nthen run this. Each other sport keeps its own words, taken from its current page: the <title>, the description,\nthe <h1> heading and the subtitle (id="sub"); women\'s sports also get she/her for he/his/him. Everything else comes\nfrom football\'s page. (Before Oct 28 the pages were edited one by one, and the other sports never got football\'s\nmulti-conference filter: picking two conferences there left the heading at "All-school stats".)\n'


PAGES = ["players-dotmap.html", "players-heatmap.html", "players-transfers.html"]
# The staff pages take their words from staff_data.json, so every sport gets football's file as it is (made if missing)
STAFF_PAGES = ["staff-moves.html", "staff-directory.html"]
MASTER = "football"
WOMEN = {"softball", "lacrosse-womens", "hockey-womens", "basketball-womens", "volleyball-womens", "soccer-womens"}
# The lines a sport keeps from its own page: one pattern per line, matched against the whole line
OWN_LINES = [re.compile(p) for p in (r"^\s*<title>.*</title>\s*$", r'^\s*<meta name="description" .*>\s*$',
                                      r"^\s*<h1>.*</h1>\s*$", r'^\s*<p class="sub" id="sub">.*</p>\s*$')]
_PRONOUNS = {"he": "she", "his": "her", "him": "her", "He": "She", "His": "Her"}


def build(master: str, own: str, women: bool) -> str:
    """The sport's page: the master's lines, with the sport's own title, description, heading and subtitle."""
    mine = {}
    for line in own.splitlines():
        for i, pat in enumerate(OWN_LINES):
            if i not in mine and pat.match(line):
                mine[i] = line
    out = []
    for line in master.splitlines():
        hit = next((i for i, pat in enumerate(OWN_LINES) if pat.match(line)), None)
        if hit is not None and hit in mine:
            line = mine[hit]
        elif women:
            line = re.sub(r"\b(he|his|him|He|His)\b", lambda m: _PRONOUNS[m.group(1)], line)
        out.append(line)
    return "\n".join(out) + ("\n" if master.endswith("\n") else "")


def sync_pages_main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=SYNC_PAGES_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="don't write: list the pages that differ and how many lines")
    args = ap.parse_args(argv)
    docs = ROOT / "docs"
    stale = 0
    for sport in available_sports():
        if sport == MASTER:
            continue
        for page in PAGES + STAFF_PAGES:
            master_path, path = docs / MASTER / page, docs / sport / page
            if not master_path.exists() or not (path.exists() or page in STAFF_PAGES):
                continue
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            master = master_path.read_text(encoding="utf-8")
            new = master if page in STAFF_PAGES else build(master, old, sport in WOMEN)
            if new == old:
                continue
            stale += 1
            changed = sum(1 for d in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
                          if d[:1] in "+-" and not d.startswith(("+++", "---")))
            print(f"{'differs' if args.check else 'updated'}: docs/{sport}/{page} ({changed} lines)")
            if not args.check:
                path.write_text(new, encoding="utf-8")
    if not stale:
        print("Every sport's pages match football's.")
    return 1 if (args.check and stale) else 0


COMMANDS = {"map": build_map_data_main, "locations": build_school_locations_main, "frozen": check_frozen_classes_main, "check": check_rosters_main, "sync": sync_pages_main}


def command_line(argv=None) -> int:
    """python3 scripts/build.py <command> [options]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        sys.argv[0] = f"{Path(sys.argv[0]).name} {argv[0]}"     # so --help says "build.py map"
        return COMMANDS[argv[0]](argv[1:]) or 0
    sys.exit("commands: " + ", ".join(COMMANDS) + " (add --help to one for its options)")


if __name__ == "__main__":
    raise SystemExit(command_line())
