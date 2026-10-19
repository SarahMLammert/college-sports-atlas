#!/usr/bin/env python3
"""Pack players_unique_geocoded.csv into the JSON the map site (docs/index.html) loads.

    python build_map_data.py                      # data/players_unique_geocoded.csv -> docs/data/map_data.json
    python build_map_data.py <input.csv> <output.json>

Run it again whenever you re-scrape or re-geocode, then commit docs/data/map_data.json.
Dot colors come from config/school_colors.csv (school, primary, secondary hex colors).
"""
import csv
from pathlib import Path
import json
import re
import sys
from collections import Counter

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


# A previous school that looks like a high school / prep school isn't a transfer. Don't add
# words like "North" or "Central" here: "North Texas" and "Central Michigan" are colleges.
HS_LIKE = re.compile(r"\b(hs|high school|prep|academy)\b", re.I)


def is_transfer(prev: str, high_school: str) -> int:
    prev = (prev or "").strip()
    if not prev or prev.lower() == (high_school or "").strip().lower():
        return 0
    return 0 if HS_LIKE.search(prev) else 1


COLORS_CSV = Path(__file__).resolve().parent / "config" / "school_colors.csv"
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

    towns, tidx = [], {}
    hs_tab, hidx = [], {}
    P = {k: [] for k in ("s", "t", "p", "f", "l", "x", "d", "h", "n")}
    for r in rows:
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
        hs = (r["high_school"] or "").strip()
        if hs not in hidx:
            hidx[hs] = len(hs_tab)
            hs_tab.append(hs)
        transfer = is_transfer(r["previous_school"], r["high_school"])
        P["s"].append(sidx[r["school"]])
        P["t"].append(t)
        P["p"].append(pos_group(r["position"]))
        P["f"].append(int(r["first_season"]) - 2000)
        P["l"].append(int(r["last_season"]) - 2000)
        P["x"].append(transfer)
        P["d"].append(divs.index(r["division_first_season"]) if r["division_first_season"] in divs else 0)
        P["h"].append(hidx[hs])
        P["n"].append(r["name"])
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
    print("transfers:", sum(P["x"]))


if __name__ == "__main__":
    args = sys.argv[1:] or ["data/players_unique_geocoded.csv", "docs/data/map_data.json"]
    if len(args) != 2:
        sys.exit(__doc__)
    main(*args)
