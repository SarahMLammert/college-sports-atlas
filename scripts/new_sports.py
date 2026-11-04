"""Writes config/<sport>/settings.json and schools.csv for the sports added on Nov 2, 2026, from the NCAA directory
and the schools files already here. Safe to run again: it only writes these sports' two files, and leaves a sport
alone once rosters/<sport>/ exists unless --force is given (a hand fix in its schools.csv would be lost).

    python3 scripts/new_sports.py                  # every sport below
    python3 scripts/new_sports.py wrestling-mens   # one sport
    python3 scripts/new_sports.py --report         # what would be written, nothing changed

How schools.csv is made:
- The NCAA directory's list for the sport says who has a team, in which division and conference. Its conference
  names are turned into the short names the other sports use, by majority vote over schools in both.
- Names are matched to this repo's names by athletics site, then by name. A school found nowhere here keeps a tidied
  directory name and is printed, because it needs a row in config/shared/ for its dot and colors.
- Every other college stays as a "level only" row, so a transfer's old school still gets a level. Division history
  rows come from the sport's base file (soccer-mens for fall sports, basketball-mens for the rest).
- NAIA and junior colleges: everyone with a site in any sport's file, for sports they commonly play. Those without
  the team show up as scrape failures and are given up on after three runs. Field hockey, water polo and rowing are
  NCAA only: hardly any NAIA or junior college has them, so trying all of them would only waste time.
- "left out" notes about a whole site (bot checks) carry over; notes about one sport's pages don't."""
from __future__ import annotations

import argparse
import collections
import copy
import csv
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
NCAA = ROOT / ".cache" / "ncaa"
URL = "https://web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode={}"
FIELDS = ["school", "division", "conference", "domain", "roster_url", "first_season", "last_season", "aliases", "note"]
DIV = {1: "D1", 2: "D2", 3: "D3"}


def paths(*codes: str) -> list[str]:
    return [f"/sports/{c}/roster" for c in codes]


def weight_classes(light: int, middle: int) -> dict:
    """A weight class as rosters write it ("125", "285", "HWT"): up to `light`, up to `middle`, or above."""
    return {"LW": " ".join(map(str, range(90, light + 1))), "MW": " ".join(map(str, range(light + 1, middle + 1))),
            "HW": " ".join(map(str, range(middle + 1, 300))) + " hwt hw heavyweight hvy"}


ONE_GROUP = dict(position_groups=["ALL"], position_abbreviations={}, position_words=[], position_fallback="ALL")
TRACK = dict(
    position_groups=["SPR", "DIST", "JUMP", "THROW", "MULTI", "UNK"],
    position_abbreviations={
        "SPR": "s sp spr sprint sprints sprinter sprinters h hur hurdle hurdles hurdler sh",
        "DIST": "d dist distance md mid mid-distance ld xc",
        "JUMP": "j jump jumps jumper jumps lj tj hj pv vault",
        "THROW": "t th throw throws thrower wt shot discus javelin hammer",
        "MULTI": "m multi multis mult multi-event multi-events combined heptathlon decathlon pentathlon"},
    position_words=[["sprint", "SPR"], ["hurdl", "SPR"], ["short", "SPR"], ["relay", "SPR"], ["distance", "DIST"],
                    ["middle", "DIST"], ["long distance", "DIST"], ["cross", "DIST"], ["jump", "JUMP"], ["long jump", "JUMP"],
                    ["high jump", "JUMP"], ["triple", "JUMP"], ["pole", "JUMP"], ["throw", "THROW"], ["shot", "THROW"],
                    ["discus", "THROW"], ["javelin", "THROW"], ["hammer", "THROW"], ["weight", "THROW"], ["multi", "MULTI"],
                    ["combined", "MULTI"], ["hept", "MULTI"], ["dec", "MULTI"]],
    position_fallback="UNK",
    position_labels={"SPR": "Sprints and hurdles", "DIST": "Distance", "JUMP": "Jumps", "THROW": "Throws",
                     "MULTI": "Multi-events", "UNK": "Other"})
SWIM = dict(
    position_groups=["FREE", "BACK", "BREAST", "FLY", "IM", "DIVE", "UNK"],
    position_abbreviations={"FREE": "fr free freestyle sprint distance mid-distance dist", "BACK": "bk back backstroke",
                            "BREAST": "br breast breaststroke", "FLY": "fl fly butterfly", "IM": "im ind",
                            "DIVE": "d dv dive diver diving"},
    position_words=[["free", "FREE"], ["sprint", "FREE"], ["distance", "FREE"], ["back", "BACK"], ["breast", "BREAST"],
                    ["fly", "FLY"], ["butterfly", "FLY"], ["individual", "IM"], ["div", "DIVE"]],
    position_fallback="UNK",
    position_labels={"FREE": "Freestyle", "BACK": "Backstroke", "BREAST": "Breaststroke", "FLY": "Butterfly",
                     "IM": "Individual medley", "DIVE": "Diving", "UNK": "Other"})
ROWING = dict(
    position_groups=["ROW", "COX", "UNK"],
    position_abbreviations={"ROW": "r rower port starboard stroke bow sweep scull sculler novice varsity", "COX": "c cox coxswain"},
    position_words=[["row", "ROW"], ["port", "ROW"], ["starboard", "ROW"], ["cox", "COX"]], position_fallback="UNK",
    position_labels={"ROW": "Rower", "COX": "Coxswain", "UNK": "Other"})
POLO = dict(
    position_groups=["GK", "FP", "UNK"],
    position_abbreviations={"GK": "g gk goalie goalkeeper", "FP": "u util utility d driver a att attacker cb hs hm center fp flat"},
    position_words=[["goal", "GK"], ["util", "FP"], ["driver", "FP"], ["attack", "FP"], ["center", "FP"], ["defen", "FP"],
                    ["field", "FP"], ["hole", "FP"]],
    position_fallback="UNK", position_labels={"GK": "Goalkeeper", "FP": "Field player", "UNK": "Other"})
FIELD_HOCKEY = dict(
    position_groups=["GK", "D", "M", "F", "UNK"],
    position_abbreviations={"GK": "gk g k", "D": "d b def fb", "M": "m mf mid", "F": "f fw fwd a att"},
    position_words=[["goal", "GK"], ["keeper", "GK"], ["defen", "D"], ["back", "D"], ["mid", "M"], ["forward", "F"],
                    ["attack", "F"]],
    position_fallback="UNK",
    position_labels={"GK": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward", "UNK": "Other"})


def wrestling(light: int, middle: int) -> dict:
    return dict(position_groups=["LW", "MW", "HW", "UNK"], position_abbreviations=weight_classes(light, middle),
                position_words=[["heavy", "HW"]], position_fallback="UNK",
                position_labels={"LW": f"Up to {light} lb", "MW": f"{light + 1} to {middle} lb", "HW": f"{middle + 1} lb and up",
                                 "UNK": "Other"})


def one_group(label: str) -> dict:
    return {**ONE_GROUP, "position_labels": {"ALL": label}}


# name, what the pages call it, NCAA codes, front page (disc, name, ring, order, sex, sub), spring-named seasons,
# who the pages are about, addresses, combined addresses, Presto addresses, roster sizes, positions, small colleges
def sport(name, title, codes, disc, disc_name, ring, order, sex, spring, noun, own, both, presto, size, pos, small=True, sub=""):
    return dict(name=name, title=title, codes=codes, disc=disc, disc_name=disc_name, ring=ring, order=order, sex=sex,
                spring=spring, noun=noun, own=own, both=both, presto=presto, size=size, pos=pos, small=small, sub=sub)


FALL_YEAR, SPRING_YEAR = "{season}-{next_yy}", "{prev_season}-{yy}"
SPORTS = [
    sport("wrestling-mens", "Wrestling", ["MWR"], "wrestling", "Wrestling", "winter", 13, "m", True, "wrestler",
          ["wrestling", "wrest", "m-wrestl", "mwrest"], [], ["wrest"], (10, 70, 12, 10), wrestling(141, 174)),
    sport("wrestling-womens", "Wrestling", ["WWR"], "wrestling", "Wrestling", "winter", 13, "w", True, "wrestler",
          ["womens-wrestling", "wwrest", "w-wrestl"], [], ["wwrest"], (5, 55, 8, 6), wrestling(130, 170)),
    sport("volleyball-mens", "Volleyball", ["MVB"], "volleyball", "Volleyball", "fall", 3, "m", True, "player",
          ["mens-volleyball", "mvball", "m-volley", "mvb"], [], ["mvball"], (8, 35, 10, 8), None),
    sport("field-hockey", "Field Hockey", ["WFH"], "field-hockey", "Field Hockey", "fall", 4, "", False, "player",
          ["field-hockey", "fhockey", "fh", "w-fieldh"], [], ["fh"], (12, 45, 15, 12), FIELD_HOCKEY, small=False),
    sport("water-polo-mens", "Water Polo", ["MWP"], "water-polo", "Water Polo", "fall", 6, "m", False, "player",
          ["mens-water-polo", "mwpolo", "m-wpolo", "mwaterpolo"], ["water-polo"], ["mwpolo"], (9, 45, 13, 10), POLO, small=False),
    sport("water-polo-womens", "Water Polo", ["WWP"], "water-polo", "Water Polo", "fall", 6, "w", True, "player",
          ["womens-water-polo", "wwpolo", "w-wpolo", "wwaterpolo"], ["water-polo"], ["wwpolo"], (9, 45, 13, 10), POLO, small=False),
    sport("rowing-mens", "Rowing", ["MCR"], "rowing", "Rowing", "spring", 25, "m", True, "rower",
          ["mens-rowing", "mrowing", "m-rowing", "mens-crew", "mrow"], ["rowing", "crew"], ["mrow"], (8, 120, 15, 10), ROWING, small=False),
    sport("rowing-womens", "Rowing", ["WCR"], "rowing", "Rowing", "spring", 25, "w", True, "rower",
          ["womens-rowing", "wrowing", "w-rowing", "womens-crew", "wrow"], ["rowing", "crew"], ["wrow"], (10, 150, 20, 15), ROWING, small=False),
    sport("tennis-mens", "Tennis", ["MTE"], "tennis", "Tennis", "spring", 26, "m", True, "player",
          ["mens-tennis", "mten", "m-tennis", "mtennis"], ["tennis"], ["mten"], (4, 22, 6, 4), one_group("All players")),
    sport("tennis-womens", "Tennis", ["WTE"], "tennis", "Tennis", "spring", 26, "w", True, "player",
          ["womens-tennis", "wten", "w-tennis", "wtennis"], ["tennis"], ["wten"], (4, 22, 6, 4), one_group("All players")),
    sport("golf-mens", "Golf", ["MGO"], "golf", "Golf", "spring", 27, "m", True, "golfer",
          ["mens-golf", "mgolf", "m-golf"], ["golf"], ["mgolf"], (3, 22, 5, 3), one_group("All golfers")),
    sport("golf-womens", "Golf", ["WGO"], "golf", "Golf", "spring", 27, "w", True, "golfer",
          ["womens-golf", "wgolf", "w-golf"], ["golf"], ["wgolf"], (3, 22, 5, 3), one_group("All golfers")),
    sport("cross-country-mens", "Cross Country", ["MCC"], "cross-country", "Cross Country", "fall", 5, "m", False, "runner",
          ["mens-cross-country", "mxc", "m-xc", "mcross"], ["cross-country", "xc", "c-xc", "cross"], ["mxc", "xc"], (3, 80, 6, 4), one_group("All runners")),
    sport("cross-country-womens", "Cross Country", ["WCC"], "cross-country", "Cross Country", "fall", 5, "w", False, "runner",
          ["womens-cross-country", "wxc", "w-xc", "wcross"], ["cross-country", "xc", "c-xc", "cross"], ["wxc", "xc"], (3, 80, 6, 4), one_group("All runners")),
    sport("track-mens", "Track & Field", ["MTI", "MTO"], "track", "Track & Field", "spring", 24, "m", True, "athlete",
          ["mens-track-and-field", "mtrack", "m-track", "mtf"], ["track-and-field", "track", "trackfield", "c-track"], ["mtrack", "track"],
          (5, 150, 12, 8), TRACK),
    sport("track-womens", "Track & Field", ["WTI", "WTO"], "track", "Track & Field", "spring", 24, "w", True, "athlete",
          ["womens-track-and-field", "wtrack", "w-track", "wtf"], ["track-and-field", "track", "trackfield", "c-track"], ["wtrack", "track"],
          (5, 150, 12, 8), TRACK),
    sport("swimming-mens", "Swimming & Diving", ["MSW"], "swimming", "Swimming", "winter", 14, "m", True, "swimmer",
          ["mens-swimming-and-diving", "mswim", "m-swim", "mswimdive", "mens-swimming"], ["swimming-and-diving", "swimming", "swim", "c-swim"],
          ["mswimdive", "mswim"], (5, 70, 8, 6), SWIM),
    sport("swimming-womens", "Swimming & Diving", ["WSW"], "swimming", "Swimming", "winter", 14, "w", True, "swimmer",
          ["womens-swimming-and-diving", "wswim", "w-swim", "wswimdive", "womens-swimming"], ["swimming-and-diving", "swimming", "swim", "c-swim"],
          ["wswimdive", "wswim"], (5, 70, 8, 6), SWIM),
]


def team_words(s: dict) -> tuple[str, str]:
    """('College Tennis (Men's)', "men's tennis")"""
    tag = {"m": " (Men's)", "w": " (Women's)"}.get(s["sex"], "")
    who = {"m": "men's ", "w": "women's "}.get(s["sex"], "")
    return f"College {s['title']}{tag}", f"{who}{s['title'].lower()}"


def site_words(s: dict) -> dict:
    head, sport_name = team_words(s)
    noun = s["noun"]
    levels = "Division I, II and III, NAIA and junior college" if s["small"] else "Division I, II and III"
    reach = "Division I to junior college" if s["small"] else "Division I to Division III"
    front = {"disc": s["disc"], "name": s["disc_name"], "icon": s["disc"], "ring": s["ring"], "order": s["order"]}
    if s["sex"]:
        front["sex"] = s["sex"]
    return {
        "front_page": front, "women": s["sex"] == "w" or s["name"] == "field-hockey",
        "players-dotmap": {"title": f"{head} Recruiting Map",
                           "description": f"Where every varsity college {sport_name} {noun} since 2016 comes from, mapped: {levels}.",
                           "h1": f"{head} <span>Recruiting Map</span>",
                           "sub": f"Hometowns of every varsity college {sport_name} {noun} since 2016"},
        "players-heatmap": {"title": f"{head} Recruiting Footprints",
                            "description": f"Compare where up to four college {sport_name} programs, from {reach}, find their {noun}s, state by state.",
                            "h1": f"{head} <span>Recruiting Footprints</span>"},
        "players-transfers": {"title": f"{head} Transfer Map",
                              "description": f"Where college {sport_name} {noun}s transferred, school to school, since 2016.",
                              "h1": f"{head} <span>Transfer Map</span>",
                              "sub": f"Where {noun}s moved from school to school since 2016"}}


def settings(s: dict, template: dict) -> dict:
    year = SPRING_YEAR if s["spring"] else FALL_YEAR
    low, high, thin, frozen = s["size"]
    tag = {"m": " (Men's)", "w": " (Women's)"}.get(s["sex"], "")
    out = {"label": f"{s['title']}{tag}", "roster_paths": paths(*s["own"], *s["both"]),
           "presto_paths": [f"/sports/{c}/{year}/roster" for c in s["presto"]],
           "min_players": low, "max_players": high, "junior_colleges": template["junior_colleges"]}
    if s["spring"]:
        out["spring_season"] = True
    if s["sex"]:
        out["roster_sex"] = s["sex"]
    if s["both"]:
        out["combined_paths"] = paths(*s["both"])
    pos = s["pos"] or {k: template[k] for k in ("position_groups", "position_abbreviations", "position_words", "position_fallback", "position_labels")}
    out.update({k: pos[k] for k in ("position_groups", "position_abbreviations", "position_words", "position_fallback")})
    out.update({"d1_divisions": ["D1"], "other_divisions": template["other_divisions"],
                "division_labels": template["division_labels"], "position_labels": pos["position_labels"],
                "thin_roster": thin, "frozen_min_pairs": frozen, "site": site_words(s)})
    return out


# ---- the NCAA directory and matching ---------------------------------------------------------------------------
def ncaa(code: str) -> list[dict]:
    path = NCAA / f"{code}.json"
    if not path.exists():
        NCAA.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL.format(code), headers={"Accept": "application/json", "User-Agent": "college-sports-atlas"})
        with urllib.request.urlopen(req, timeout=60) as fh:
            path.write_bytes(fh.read())
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        raise SystemExit(f"The NCAA directory gave no schools for {code}")
    return [r for r in rows if r.get("deactive") != "Y" and r.get("division") in DIV]


def host(url: str) -> str:
    url = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    return url[4:] if url.startswith("www.") else url


def name_key(name: str) -> str:
    n = name.lower().replace("&", " and ").replace("saint ", "st ").replace("st. ", "st ")
    n = re.sub(r"\b(the|university|college|of|at|and|main campus)\b", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def tidy_name(official: str) -> str:
    n = re.sub(r"^University of ", "", official.strip())
    n = re.sub(r",.*$", "", n)
    return re.sub(r" (University|College)$", "", n).strip()


def read_rows(sport_name: str) -> list[dict]:
    with open(CONFIG / sport_name / "schools.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Colleges:
    """Every college in every sport's file: its usual name, site, aliases and division."""

    def __init__(self):
        self.by_host, self.by_name, self.site, self.left_out, self.small = {}, {}, {}, {}, {}
        self.aliases = {}
        for folder in sorted(p for p in CONFIG.iterdir() if (p / "schools.csv").exists() and (p / "settings.json").exists()):
            if folder.name in NEW_NAMES:
                continue
            for r in read_rows(folder.name):
                name = r["school"]
                if r["division"] in ("HS", "CLUB", "none"):
                    continue
                self.by_name.setdefault(name_key(name), name)
                for a in filter(None, (r.get("aliases") or "").split("|")):
                    self.by_name.setdefault(name_key(a), name)
                if r.get("aliases"):
                    self.aliases.setdefault(name, r["aliases"])
                if r.get("domain"):
                    self.by_host.setdefault(host(r["domain"]), name)
                    self.site.setdefault(name, r["domain"])
                    if r["division"] in ("NAIA", "JUCO") and not r["first_season"] and not r["last_season"]:
                        self.small.setdefault(name, r)
                note = r.get("note") or ""
                if note.lower().startswith("left out") and re.search(r"refus|bot check|block|incapsula|imperva", note, re.I):
                    self.left_out.setdefault(name, note)

    def find(self, rec: dict) -> str:
        if rec["nameOfficial"] in BY_HAND:
            return BY_HAND[rec["nameOfficial"]]
        return self.by_host.get(host(rec.get("athleticWebUrl"))) or self.by_name.get(name_key(rec["nameOfficial"])) or ""


NEW_NAMES = {s["name"] for s in SPORTS}
BY_HAND = {"Wesleyan University (Connecticut)": "Wesleyan (CT)"}     # the directory's site is wesleyan.edu/athletics


def conference_names(colleges: Colleges) -> dict:
    """The directory's conference name -> the name the schools files use, by majority."""
    votes = collections.defaultdict(collections.Counter)
    rows = {r["school"]: r for r in read_rows("basketball-mens") + read_rows("soccer-mens") if r["conference"]}
    for code in ("MBB", "WBB", "MSO", "WSO"):
        for rec in ncaa(code):
            name = colleges.find(rec)
            if name in rows:
                votes[rec.get("conferenceName") or ""][rows[name]["conference"]] += 1
    return {k: v.most_common(1)[0][0] for k, v in votes.items() if k}


def school_rows(s: dict, colleges: Colleges, conferences: dict, new: dict) -> list[dict]:
    team = f"{team_words(s)[1]} team"
    listed = {}
    for code in s["codes"]:
        for rec in ncaa(code):
            name = colleges.find(rec)
            if not name:
                name = tidy_name(rec["nameOfficial"])
                new.setdefault(name, rec)
            listed.setdefault(name, rec)
    base = read_rows("basketball-mens" if s["spring"] else "soccer-mens")
    out, placed = [], set()
    level_only = f"level only: no {team} listed; listed so transfers from it get a level"

    def team_row(name: str, rec: dict | None, row: dict) -> dict:
        conf = row.get("conference", "")
        if rec:
            directory = rec.get("conferenceName") or ""
            conf = conferences.get(directory, directory)
        site = (colleges.site.get(name) or host(rec.get("athleticWebUrl") if rec else "")).strip()
        return {**{k: "" for k in FIELDS}, "school": name, "division": DIV[rec["division"]] if rec else row["division"],
                "conference": conf, "domain": site, "aliases": row.get("aliases") or colleges.aliases.get(name, ""),
                "note": colleges.left_out.get(name, "")}

    for r in base:
        name, ranged = r["school"], bool(r["first_season"] or r["last_season"])
        if r["division"] == "HS":
            out.append(dict(r))
        elif ranged:
            if not re.search(r"program|dropped|team|football from|started", r.get("note") or "", re.I):
                out.append({**r, "domain": "", "roster_url": ""})
        elif name in listed:
            out.append(team_row(name, listed[name], r))
            placed.add(name)
        elif s["small"] and name in colleges.small and r["division"] in ("NAIA", "JUCO"):
            out.append(team_row(name, None, r))
            placed.add(name)
        else:
            out.append({**r, "domain": "", "roster_url": "", "note": level_only})
            placed.add(name)
    for name, rec in sorted(listed.items()):
        if name not in placed:
            out.append(team_row(name, rec, {}))
            placed.add(name)
    if s["small"]:
        for name, r in sorted(colleges.small.items()):
            if name not in placed:
                out.append(team_row(name, None, r))
                placed.add(name)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sports", nargs="*", help="sports to write (default: all of them)")
    ap.add_argument("--report", action="store_true", help="print what would be written; change nothing")
    ap.add_argument("--force", action="store_true", help="write a sport even if it has been scraped")
    args = ap.parse_args(argv)
    colleges = Colleges()
    conferences = conference_names(colleges)
    women = json.loads((CONFIG / "volleyball-womens" / "settings.json").read_text(encoding="utf-8"))
    soccer = json.loads((CONFIG / "soccer-mens" / "settings.json").read_text(encoding="utf-8"))
    new: dict = {}
    for s in SPORTS:
        if args.sports and s["name"] not in args.sports:
            continue
        rows = school_rows(s, colleges, conferences, new)
        team = [r for r in rows if r["domain"]]
        by_div = collections.Counter(r["division"] for r in team)
        blocked = sum(1 for r in team if r["note"].lower().startswith("left out"))
        print(f"{s['name']:22} {len(team):5} programs {dict(sorted(by_div.items()))}, {blocked} left out")
        missing = [r["school"] for r in rows if r["division"] in DIV.values() and not r["domain"]
                   and not r["note"].startswith("level only") and not (r["first_season"] or r["last_season"])]
        if missing:
            print(f"    no site: {', '.join(missing)}")
        if args.report:
            continue
        folder = CONFIG / s["name"]
        if (ROOT / "rosters" / s["name"]).exists() and not args.force:
            print("    already scraped, left alone (--force to write it)")
            continue
        folder.mkdir(exist_ok=True)
        template = women if s["pos"] is None else soccer
        (folder / "settings.json").write_text(json.dumps(settings(s, copy.deepcopy(template)), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        with open(folder / "schools.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    if new:
        print(f"\nNot found in any schools file ({len(new)}): each needs a row in config/shared/")
        for name, rec in sorted(new.items()):
            print(f"  {name} | {rec['nameOfficial']} | D{rec['division']} | {rec.get('athleticWebUrl')} | {(rec.get('memberOrgAddress') or {}).get('state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
