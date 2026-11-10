"""Pro rosters with each player's college, matched to the college rosters (high school -> college -> pro).

    python3 scripts/pro_rosters.py nfl                  # this season's 32 NFL rosters
    python3 scripts/pro_rosters.py nfl --refresh        # download the pages again (they change every week)
    python3 scripts/pro_rosters.py nfl --match-only     # only redo the matching, from the saved roster file

Writes, in rosters/pro/:
  nfl_<season>.csv          every player on an NFL roster: team, name, number, position, status, height,
                            weight, experience, college, profile link
  nfl_<season>_matched.csv  the same players with what the college rosters know about them: the school
                            (as config/football/schools.csv names it) and its division, the seasons on
                            that roster, hometown and high school. matched = name found on that school's
                            football roster.

Pages come from the league's own site and are cached in .cache/html like the college pages; a site that
refuses automated visitors is left out, not worked around. A roster page lists the current players only,
so each run is a snapshot of one season.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter, defaultdict

from bs4 import BeautifulSoup

from core import CACHE, ROSTERS, Fetcher, Levels, clean, load_sport, name_key, read_csv, season_files, write_csv

PRO_DIR = ROSTERS / "pro"

NFL_TEAMS = [
    "arizona-cardinals", "atlanta-falcons", "baltimore-ravens", "buffalo-bills", "carolina-panthers",
    "chicago-bears", "cincinnati-bengals", "cleveland-browns", "dallas-cowboys", "denver-broncos",
    "detroit-lions", "green-bay-packers", "houston-texans", "indianapolis-colts", "jacksonville-jaguars",
    "kansas-city-chiefs", "las-vegas-raiders", "los-angeles-chargers", "los-angeles-rams", "miami-dolphins",
    "minnesota-vikings", "new-england-patriots", "new-orleans-saints", "new-york-giants", "new-york-jets",
    "philadelphia-eagles", "pittsburgh-steelers", "san-francisco-49ers", "seattle-seahawks",
    "tampa-bay-buccaneers", "tennessee-titans", "washington-commanders",
]
LEAGUES = {
    "nfl": {"teams": NFL_TEAMS, "url": "https://www.nfl.com/teams/{team}/roster", "college_sport": "football",
            "site": "https://www.nfl.com",
            # the league's own spellings that fit more than one school: NFL.com writes Miami (OH) as "Miami (Ohio)"
            "colleges": {"Miami": "Miami (FL)"}},
}
ROSTER_FIELDS = ["league", "season", "team", "name", "number", "position", "status", "height", "weight",
                 "experience", "college", "profile_url"]
MATCH_FIELDS = ROSTER_FIELDS + ["college_school", "college_level", "matched", "college_name", "college_first",
                                "college_last", "hometown", "home_state", "home_country", "high_school"]
# The roster table's columns, by header text
_COLUMNS = {"player": "name", "name": "name", "no": "number", "#": "number", "pos": "position",
            "position": "position", "status": "status", "height": "height", "ht": "height", "weight": "weight",
            "wt": "weight", "experience": "experience", "exp": "experience", "college": "college"}
_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$", re.I)


def season_now(today: dt.date | None = None) -> int:
    """The NFL season a roster page shows: the fall's year (rosters from March on belong to the coming season)."""
    today = today or dt.date.today()
    return today.year if today.month >= 3 else today.year - 1


def parse_roster_page(html: str, site: str = "") -> list[dict]:
    """The players in a league roster page: the table with Player and College columns."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        head = table.find("thead") or table.find("tr")
        if not head:
            continue
        headers = [_COLUMNS.get(clean(th.get_text(" ")).lower().strip(" .:"), "") for th in head.find_all(["th", "td"])]
        if "name" not in headers or "college" not in headers:
            continue
        for tr in (table.find("tbody") or table).find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(headers) or tr is head:
                continue
            rec = {}
            for field, cell in zip(headers, cells):
                if not field:
                    continue
                if field == "name":
                    link = cell.find("a", href=True)
                    rec["name"] = clean((link or cell).get_text(" "))
                    href = link["href"] if link else ""
                    rec["profile_url"] = (site + href) if href.startswith("/") else href
                else:
                    rec[field] = clean(cell.get_text(" "))
            if rec.get("name"):
                out.append(rec)
    return out


def scrape(league: str, season: int, refresh: bool) -> list[dict]:
    conf = LEAGUES[league]
    fetcher = Fetcher(cache_dir=CACHE, refresh=refresh, delay=2.0)
    rows, problems = [], []
    for team in conf["teams"]:
        url = conf["url"].format(team=team)
        try:
            status, _, html = fetcher.get(url, remember_miss=False)
        except Exception as exc:  # noqa: BLE001  (network trouble: say which team, keep going)
            problems.append(f"{team}: {exc}")
            continue
        players = parse_roster_page(html, conf["site"]) if status == 200 else []
        if not players:
            problems.append(f"{team}: HTTP {status}, no players read")
        for p in players:
            rows.append({"league": league.upper(), "season": season, "team": team.replace("-", " ").title(),
                         **{f: p.get(f, "") for f in ROSTER_FIELDS if f not in ("league", "season", "team")}})
        print(f"  {team:24} {len(players):3} players")
    for p in problems:
        print("  problem:", p)
    return rows


def _last_name_key(name: str) -> str:
    parts = _SUFFIX.sub("", clean(name)).split()
    return name_key(parts[-1]) if parts else ""


def college_index(sport_name: str) -> dict[tuple[str, str], dict]:
    """(school, name key) -> first/last season, hometown and high school, from the sport's season files."""
    sport = load_sport(sport_name)
    idx: dict[tuple[str, str], dict] = {}
    for season, path in sorted(season_files(sport.rosters_dir).items()):
        for r in read_csv(path):
            k = (r["school"], name_key(_SUFFIX.sub("", r["name"])))
            got = idx.get(k)
            if got is None:
                idx[k] = got = {"college_first": season, "hometown": "", "home_state": "", "home_country": "",
                                "high_school": "", "college_name": r["name"], "last_key": _last_name_key(r["name"])}
            got["college_last"] = season
            for f in ("hometown", "home_state", "home_country", "high_school"):
                if r.get(f):
                    got[f] = r[f]          # the latest season that has it
    return idx


def _first_names_fit(pro: str, college: str) -> bool:
    """Could these be the same person's first names? Same first letter (Pat/Patrick, Mike/Michael), one inside
    the other (Riq/Tariq, Cobie/Decobie), or the pro name written into the college one (Ahmad "Sauce")."""
    a = name_key(clean(pro).split()[0]) if clean(pro) else ""
    whole = name_key(college)
    b = name_key(clean(college).split()[0]) if clean(college) else ""
    if not a or not b:
        return False
    return a[0] == b[0] or a in b or b in a or (len(a) >= 3 and a in whole[:-len(_last_name_key(college)) or None])


def _pro_years(experience: str) -> int | None:
    """NFL.com's Experience column: 'R' for a rookie, else seasons in the league."""
    e = (experience or "").strip().upper()
    return 0 if e == "R" else int(e) if e.isdigit() else None


def match(rows: list[dict], league: str) -> list[dict]:
    """Find each pro player on his college's roster.

    matched = "yes": the same name on that school's roster. "likely": the same last name at that school and
    first names that fit (_first_names_fit: "Sauce Gardner" is Ahmad "Sauce" Gardner, "Pat Surtain II" Patrick
    Surtain, "Riq Woolen" Tariq Woolen), taken only when exactly one such player's last college season fits his
    years in the league (he left college the year before his rookie season, give or take). Nicknames unlike the
    name ("Bam" for Zonovan Knight) stay unmatched rather than risk a wrong person."""
    conf = LEAGUES[league]
    sport = load_sport(conf["college_sport"])
    levels = Levels.load(sport)
    idx = college_index(sport.name)
    by_last = defaultdict(list)
    for (school, _nk), info in idx.items():
        by_last[(school, info["last_key"])].append(info)
    out = []
    for r in rows:
        season = int(r["season"])
        college = conf.get("colleges", {}).get(r["college"], r["college"])
        level, school = levels.level(college, season - 1) if college else ("", "")
        nk = name_key(_SUFFIX.sub("", r["name"]))
        hit = idx.get((school, nk)) if school else None
        how = "yes" if hit else ""
        years = _pro_years(r.get("experience", ""))
        if school and not hit and years is not None:
            left = season - years - 1                      # his last college season, if he went straight in
            fits = [i for i in by_last.get((school, _last_name_key(r["name"])), [])
                    if left - 2 <= i["college_last"] <= left + 1 and _first_names_fit(r["name"], i["college_name"])]
            if len(fits) == 1:
                hit, how = fits[0], "likely"
        info = {k: v for k, v in (hit or {}).items() if k != "last_key"}
        out.append({**r, "college_school": school, "college_level": level if school else "", "matched": how, **info})
    return out


def summary(rows: list[dict]) -> None:
    n = len(rows)
    with_college = sum(1 for r in rows if r["college"])
    known = sum(1 for r in rows if r["college_school"])
    matched = sum(1 for r in rows if r["matched"])
    likely = sum(1 for r in rows if r["matched"] == "likely")
    print(f"{n} players; {with_college} list a college; {known} of those colleges are in schools.csv; "
          f"{matched} found on that college's roster ({matched / max(1, known):.0%} of the known colleges; "
          f"{likely} of them by last name, as 'likely')")
    print("  by division:", dict(Counter(r["college_level"] or "?" for r in rows if r["college_school"]).most_common()))
    print("  with a hometown:", sum(1 for r in rows if r.get("hometown")),
          "| with a high school:", sum(1 for r in rows if r.get("high_school")))
    missing = Counter(r["college"] for r in rows if r["college"] and not r["college_school"])
    if missing:
        print("  colleges not in schools.csv (most players first):", missing.most_common(15))
    unmatched = Counter(r["college_school"] for r in rows if r["college_school"] and not r["matched"])
    if unmatched:
        print("  known college, name not on its roster (most first):", unmatched.most_common(10))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("league", choices=sorted(LEAGUES))
    ap.add_argument("--season", type=int, default=season_now())
    ap.add_argument("--refresh", action="store_true", help="download the roster pages again")
    ap.add_argument("--match-only", action="store_true", help="redo the matching from the saved roster file")
    args = ap.parse_args(argv)
    PRO_DIR.mkdir(parents=True, exist_ok=True)
    roster_path = PRO_DIR / f"{args.league}_{args.season}.csv"
    if args.match_only:
        rows = read_csv(roster_path)
    else:
        print(f"{args.league.upper()} {args.season}: reading {len(LEAGUES[args.league]['teams'])} roster pages")
        rows = scrape(args.league, args.season, args.refresh)
        if not rows:
            print("No players read; nothing saved.")
            return 1
        write_csv(roster_path, ROSTER_FIELDS, rows)
        print(f"-> {roster_path}")
    matched = match(rows, args.league)
    out_path = PRO_DIR / f"{args.league}_{args.season}_matched.csv"
    write_csv(out_path, MATCH_FIELDS, matched)
    summary(matched)
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
