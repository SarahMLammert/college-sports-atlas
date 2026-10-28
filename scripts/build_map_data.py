#!/usr/bin/env python3
"""Pack a sport's players into the JSON its pages (docs/<sport>/) load.

    python scripts/build_map_data.py                # rosters/football/ -> docs/football/map_data.json
    python scripts/build_map_data.py --sport lacrosse-mens
    python scripts/build_map_data.py <input.csv> <output.json>   # a geocoded CSV instead (older runs)

By default it reads the season files (rosters_<season>.csv), makes one row per player per school from
them, and places each hometown with hometowns.csv from geocode_hometowns.py, so run the geocoder first.

Run it again whenever you re-scrape or re-geocode, then commit docs/<sport>/map_data.json.
Dot colors come from config/school_colors.csv (school, primary, secondary hex colors), shared by every
sport; position groups, divisions and their labels from config/<sport>.json.

Transfers: many roster pages never list a previous school, so a player counts as a transfer if
  1. the roster lists a college as his previous school, or
  2. he was on another college's roster in this data first (same name and hometown), or
  3. he's new to a roster whose previous season is also (nearly fully) in the data, and he's already a junior, senior or grad.
(2) also records the school he came from, so the site can show where transfers moved.

Every other transfer gets the level of the school he came from (scripts/levels.py, with the colleges in
config/<sport>_schools.csv): a D1 school he wasn't found on, Division II or III, NAIA, junior
college, or unknown (no school named, or a name that fits two levels).

It reads frozen_class_seasons.csv from rosters/<sport>/ and writes transfer_levels.csv there.
"""
import argparse
import csv
from pathlib import Path
import json
import re
import sys
from collections import Counter

# The scraper's rules for telling a previous college from a high school, so both steps agree.
import sidearm
from levels import LEVELS, Levels, is_major
from paths import add_sport_argument, d1_schools, load_sport
from seasons import players
from sidearm import clean_name, load_known_colleges, sort_schools

# Position groups come from the sport's settings (config/<sport>.json): the groups, the roster
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
    """(school, season) pairs whose roster pages show the wrong class year (made by check_frozen_classes.py)."""
    if not Path(path).exists():
        print(f"{path} not found; run check_frozen_classes.py first, or the class-year rule trusts every season")
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
    (geocode_hometowns.py): its corrected city/state/country, lat/lon and precision. A town given without
    a state is looked up for the player's school first, since the geocoder guesses those per school."""
    path = sport.rosters_dir / "hometowns.csv"
    if not path.exists():
        sys.exit(f"{path} not found: run geocode_hometowns.py first.")
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
        print(f"{unplaced} players have a hometown that isn't in {path.name} yet: run geocode_hometowns.py again")
    return rows


def main(src, dst, sport):
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
        print(f"divisions not in config/{sport.name}.json (shown as {divs[0]}):", ", ".join(o or "(blank)" for o in odd))
    colors = load_colors(sport.colors_csv)
    missing = [x for x in schools if x not in colors]
    if missing:
        print("no colors in config/school_colors.csv for:", ", ".join(missing))
    prec_codes = {"city": 0, "city_guess": 1, "county": 2, "region": 3, "country": 3}

    came_from = find_moves(rows)
    have = roster_seasons(rows)
    all_seasons = sorted({y for _, y in have})
    thin = sorted(f"{s} {y}" for (s, y), n in have.items() if n < sport.thin_roster)
    if thin:
        print(f"thin rosters (fewer than {sport.thin_roster} players; the class-year transfer rule skips the season after each):",
              ", ".join(thin))
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
        "players": {k: v for k, v in P.items() if k != "n"},
    }
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, metavar="input.csv output.json",
                    help="default: the season files and hometowns.csv in rosters/<sport>/ -> docs/<sport>/map_data.json")
    add_sport_argument(ap)
    args = ap.parse_args()
    sport = load_sport(args.sport)
    if len(args.files) not in (0, 2):
        sys.exit(__doc__)
    src, dst = args.files or (None, sport.site_dir / "map_data.json")
    main(src, dst, sport)
