#!/usr/bin/env python3
"""Pack players_unique_geocoded.csv into the JSON the football pages (docs/football/) load.

    python build_map_data.py                      # data/players_unique_geocoded.csv -> docs/football/data/map_data.json
    python build_map_data.py <input.csv> <output.json>

Run it again whenever you re-scrape or re-geocode, then commit docs/football/data/map_data.json.
Dot colors come from config/school_colors.csv (school, primary, secondary hex colors).

Transfers: many roster pages never list a previous school, so a player counts as a transfer if
  1. the roster lists a college as his previous school, or
  2. he was on another D1 roster in this data first (same name and hometown), or
  3. he's new to a roster whose previous season is also (nearly fully) in the data, and he's already a junior, senior or grad.
(2) also records the school he came from, so the site can show where transfers moved.
"""
import csv
from pathlib import Path
import json
import re
import sys
from collections import Counter

# The scraper's rules for telling a previous college from a high school, so both steps agree.
from scrape_rosters import load_known_colleges, load_schools, sort_schools

POS_GROUPS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "DEF", "ST", "ATH"]
ABBR = {
    "QB": "qb", "RB": "rb hb tb fb ab", "WR": "wr sb", "TE": "te y h",
    "OL": "ol ot og oc c g t iol ol/dl", "DL": "dl de dt nt ng edge di dle dli",
    "LB": "lb ilb olb mlb wlb slb will mike sam jack star ban buck", "DB": "db cb s fs ss saf nb nik spr sa",
    "ST": "k p pk ls ds k/p p/k kos sn",
}
ABBR = {a: g for g, v in ABBR.items() for a in v.split()}
WORDS = [("quarterback", "QB"), ("running", "RB"), ("half", "RB"), ("tail", "RB"), ("full", "RB"),
         ("wide", "WR"), ("receiver", "WR"), ("slot", "WR"), ("tight", "TE"), ("offensive", "OL"),
         ("center", "OL"), ("guard", "OL"), ("tackle", "OL"), ("linebacker", "LB"), ("corner", "DB"),
         ("safety", "DB"), ("nickel", "DB"), ("kick", "ST"), ("punt", "ST"), ("long", "ST"),
         ("snap", "ST"), ("place", "ST"), ("deep snap", "ST"), ("edge", "DL"), ("nose", "DL"), ("athlete", "ATH"),
         ("outside", "LB"), ("inside", "LB"), ("bandit", "LB"), ("spur", "DB")]


def pos_group(p: str) -> int:
    p = re.sub(r"^pos\.?:\s*", "", (p or "").strip().lower())
    first = re.split(r"[\s,/-]+", p)[0] if p else ""
    if p in ABBR:
        g = ABBR[p]
    elif first in ABBR:
        g = ABBR[first]
    elif p.startswith("defensive"):
        g = ("DL" if re.search(r"line|end|tackle", p) else "DB" if "back" in p else "DEF")
    else:
        g = next((grp for w, grp in WORDS if p.startswith(w)), "ATH")
    return POS_GROUPS.index(g)


def is_transfer(prev: str, high_school: str) -> int:
    """1 if the roster names a college he came from. Uses the scraper's sort_schools(), so a high school
    filed as "previous school" ('Pickerington Central', 'Menard' next to 'Menard HS', 'IMG Academy') isn't one."""
    p = sort_schools({"high_school": high_school or "", "previous_school": prev or ""})
    return int(bool(p["previous_school"]))


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def person(r: dict) -> tuple:
    """Name + hometown, loose enough to match one player across two schools' rosters."""
    name = display_name(r["name"])      # some sites put the jersey number in the name
    name = re.sub(r"[^a-z]", "", _SUFFIX.sub("", name.lower()))
    city = re.sub(r"[^a-z]", "", (r.get("home_city") or "").lower())
    return name, city, r.get("home_state") or r.get("home_country") or ""


def find_moves(rows: list[dict]) -> dict[int, str]:
    """Row index -> the school he played for before, for players found on two D1 rosters in turn.

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


_JERSEY = re.compile(r"^\s*#?\d+(?:[a-z]|[/-]\w{0,3})?\s+(?=\D)", re.I)   # "89 ", "#7 ", "13d ", "16/33 ", "12/DB ", "1-O ", "10030 "


def display_name(name: str) -> str:
    """The player's name as shown on the site, without a jersey number some sites put in front."""
    return _JERSEY.sub("", name or "").strip()


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
                             frozen: set[tuple[str, int]] = frozenset()) -> bool:
    """New to this roster, and already a junior/senior/grad: almost always a transfer (junior college,
    Division II, or a D1 school this data doesn't cover). Only trusted when this school's roster for the
    season before is in the data and close to full: a failed or partial scrape (Ohio State 2016 has 3
    players) would make every returning junior look new. Also skipped for seasons whose class labels
    can't be trusted: some archives show each player's later class (Ohio State 2017-2022), which makes
    freshmen look like juniors."""
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
    return n_before >= 40 and n_before >= 0.6 * n_now


COLORS_CSV = Path(__file__).resolve().parent / "config" / "school_colors.csv"
SCHOOLS_CSV = Path(__file__).resolve().parent / "config" / "schools.csv"
FROZEN_CSV = Path(__file__).resolve().parent / "data" / "frozen_class_seasons.csv"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_colors(path=COLORS_CSV):
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


def main(src, dst):
    with open(src, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if SCHOOLS_CSV.exists():
        load_known_colleges(load_schools(SCHOOLS_CSV))   # so "Wake Forest" counts as a college
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
    divs = ["FBS", "FCS", "D2", "D3"]
    colors = load_colors()
    missing = [x for x in schools if x not in colors]
    if missing:
        print("no colors in config/school_colors.csv for:", ", ".join(missing))
    prec_codes = {"city": 0, "city_guess": 1, "county": 2, "region": 3, "country": 3}

    came_from = find_moves(rows)
    have = roster_seasons(rows)
    all_seasons = sorted({y for _, y in have})
    thin = sorted(f"{s} {y}" for (s, y), n in have.items() if n < 40)
    if thin:
        print("thin rosters (fewer than 40 players; the class-year transfer rule skips the season after each):", ", ".join(thin))
    prev_season = dict(zip(all_seasons[1:], all_seasons))   # 2021 -> 2019: there's no 2020 data
    frozen = load_frozen_class_seasons(FROZEN_CSV)
    if frozen:
        print(f"{len(frozen)} school-seasons with untrustworthy class years (the class-year transfer rule skips them)")
    how = Counter()

    towns, tidx = [], {}
    hs_tab, hidx = [], {}
    hs_name = hs_spellings(rows)   # hs_key -> the spelling shown on the site
    spellings = len({(r["high_school"] or "").strip() for r in rows})
    if spellings > len(hs_name):
        print(f"high schools: {spellings} spellings merged into {len(hs_name)} names ('HS' / 'High School' / 'H.S.')")
    jersey_names = sum(display_name(r["name"]) != (r["name"] or "").strip() for r in rows)
    if jersey_names:
        print(f"removed a jersey number from {jersey_names} player names")
    P = {k: [] for k in ("s", "t", "p", "f", "l", "x", "o", "d", "h", "n")}
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
        listed, moved, upper = (is_transfer(r["previous_school"], r["high_school"]), i in came_from,
                                arrived_as_upperclassman(r, have, prev_season, frozen))
        transfer = int(listed or moved or upper)
        how["previous school on the roster"] += listed
        how["found on an earlier D1 roster"] += moved and not listed
        how["arrived as a junior/senior/grad"] += upper and not (listed or moved)
        if (not transfer and frozen and (r["school"], int(r["first_season"])) in frozen
                and arrived_as_upperclassman(r, have, prev_season)):
            how["not counted: class year untrustworthy that season"] += 1
        P["s"].append(sidx[r["school"]])
        P["t"].append(t)
        P["p"].append(pos_group(r["position"]))
        P["f"].append(int(r["first_season"]) - 2000)
        P["l"].append(int(r["last_season"]) - 2000)
        P["x"].append(transfer)
        P["o"].append(sidx[came_from[i]] if i in came_from else -1)   # the D1 school he transferred from, if known
        P["d"].append(divs.index(r["division_first_season"]) if r["division_first_season"] in divs else 0)
        P["h"].append(hidx[hs])
        P["n"].append(display_name(r["name"]))
    out = {
        "schools": [[s, confs.index(conf[s]), divs.index(div_now[s][1]) if div_now[s][1] in divs else 0,
                     *colors.get(s, ("#777777", "#FFFFFF"))] for s in schools],
        "confs": confs, "divs": divs, "pos": POS_GROUPS, "towns": towns, "hs": hs_tab,
        "players": {k: v for k, v in P.items() if k != "n"}, "names": "\n".join(P["n"]),
    }
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(rows)} players, {len(towns)} hometowns, {len(schools)} schools -> {dst}")
    print("position groups:", Counter(POS_GROUPS[i] for i in P["p"]).most_common())
    skipped = how.pop("not counted: class year untrustworthy that season", 0)
    print("transfers:", sum(P["x"]), "| counted because:", dict(how))
    if skipped:
        print(f"not counted as transfers: {skipped} newcomers listed as juniors or older in a season with untrustworthy class years")
    print("D1-to-D1 moves with a known previous school:", sum(o >= 0 for o in P["o"]))


if __name__ == "__main__":
    args = sys.argv[1:] or ["data/players_unique_geocoded.csv", "docs/football/data/map_data.json"]
    if len(args) != 2:
        sys.exit(__doc__)
    main(*args)
