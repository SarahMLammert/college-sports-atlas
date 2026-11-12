"""Pro rosters with each player's college, matched to the college rosters (high school -> college -> pro).

    python3 scripts/pro_rosters.py nfl                  # this season's 32 NFL rosters
    python3 scripts/pro_rosters.py nba mlb nhl          # several leagues, one after the other
    python3 scripts/pro_rosters.py all                  # every league
    python3 scripts/pro_rosters.py nfl --refresh        # download the rosters again (they change every week)
    python3 scripts/pro_rosters.py nfl --match-only     # only redo the matching, from the saved roster file

Leagues and where their rosters come from (each league's own site):
  nfl   nfl.com team roster pages (a table with a College column)                    -> football
  nba   nba.com team pages (the roster in the page's data, with each player's school)  -> basketball-mens
  mlb   MLB's stats API, 40-man rosters with each player's high school and colleges     -> baseball
  nhl   the NHL's API: rosters, then each player's career, whose NCAA seasons name his college -> hockey-mens

Writes, in rosters/pro/:
  <league>_<season>.csv          every player on a roster: team, name, number, position, status, height, weight,
                                 experience, college, birthplace (MLB, NHL), high school (MLB), profile link, and
                                 college_until: his last college season as the college sport numbers it, worked
                                 out from his years in the league (NFL, NBA), his draft year (MLB) or his NCAA
                                 seasons (NHL)
  <league>_<season>_matched.csv  the same players with what the college rosters know about them: the school
                                 (as config/<sport>/schools.csv names it) and its division, the seasons on that
                                 roster, hometown and high school. matched = "yes" (same name on that school's
                                 roster), "likely" (last name and first names that fit), "hometown" (same name
                                 at another school, born in the town that roster gives as his hometown).

A roster lists the current players only, so each run is a snapshot of one season. A site that refuses
automated visitors is left out, not worked around (wnba.com did on Nov 9).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
NBA_TEAMS = {   # nba.com team id -> the name in its address
    1610612737: "hawks", 1610612738: "celtics", 1610612739: "cavaliers", 1610612740: "pelicans",
    1610612741: "bulls", 1610612742: "mavericks", 1610612743: "nuggets", 1610612744: "warriors",
    1610612745: "rockets", 1610612746: "clippers", 1610612747: "lakers", 1610612748: "heat", 1610612749: "bucks",
    1610612750: "timberwolves", 1610612751: "nets", 1610612752: "knicks", 1610612753: "magic", 1610612754: "pacers",
    1610612755: "sixers", 1610612756: "suns", 1610612757: "blazers", 1610612758: "kings", 1610612759: "spurs",
    1610612760: "thunder", 1610612761: "raptors", 1610612762: "jazz", 1610612763: "grizzlies",
    1610612764: "wizards", 1610612765: "pistons", 1610612766: "hornets",
}
MLB_TEAMS = {   # MLB stats API team id -> name
    108: "Los Angeles Angels", 109: "Arizona Diamondbacks", 110: "Baltimore Orioles", 111: "Boston Red Sox",
    112: "Chicago Cubs", 113: "Cincinnati Reds", 114: "Cleveland Guardians", 115: "Colorado Rockies",
    116: "Detroit Tigers", 117: "Houston Astros", 118: "Kansas City Royals", 119: "Los Angeles Dodgers",
    120: "Washington Nationals", 121: "New York Mets", 133: "Athletics", 134: "Pittsburgh Pirates",
    135: "San Diego Padres", 136: "Seattle Mariners", 137: "San Francisco Giants", 138: "St. Louis Cardinals",
    139: "Tampa Bay Rays", 140: "Texas Rangers", 141: "Toronto Blue Jays", 142: "Minnesota Twins",
    143: "Philadelphia Phillies", 144: "Atlanta Braves", 145: "Chicago White Sox", 146: "Miami Marlins",
    147: "New York Yankees", 158: "Milwaukee Brewers",
}
NHL_TEAMS = {
    "ANA": "Anaheim Ducks", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres", "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets", "CGY": "Calgary Flames", "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars", "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers", "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montreal Canadiens", "NJD": "New Jersey Devils",
    "NSH": "Nashville Predators", "NYI": "New York Islanders", "NYR": "New York Rangers", "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers", "PIT": "Pittsburgh Penguins", "SEA": "Seattle Kraken", "SJS": "San Jose Sharks",
    "STL": "St. Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs", "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights", "WPG": "Winnipeg Jets", "WSH": "Washington Capitals",
}
# The leagues an NHL player's college seasons are filed under: "NCAA" in recent seasons, the conference before
NHL_COLLEGE_LEAGUES = {"NCAA", "H-East", "Hockey East", "ECAC", "NCHC", "Big Ten", "Big-10", "WCHA", "CCHA", "AHA",
                       "Atlantic Hockey", "CHA"}

LEAGUES = {
    "nfl": {"teams": NFL_TEAMS, "url": "https://www.nfl.com/teams/{team}/roster", "college_sport": "football",
            "site": "https://www.nfl.com", "new_season_month": 3,
            # the league's own spellings that fit more than one school: NFL.com writes Miami (OH) as "Miami (Ohio)"
            "colleges": {"Miami": "Miami (FL)"}},
    "nba": {"teams": list(NBA_TEAMS), "url": "https://www.nba.com/team/{team}/{slug}", "college_sport": "basketball-mens",
            "new_season_month": 7, "colleges": {"Miami": "Miami (FL)", "St. Mary's": "Saint Mary's (CA)"}},
    "mlb": {"teams": list(MLB_TEAMS), "college_sport": "baseball", "new_season_month": 11,
            "colleges": {"Miami": "Miami (FL)"},
            "url": "https://statsapi.mlb.com/api/v1/teams/{team}/roster?rosterType=40Man&hydrate=person(education)"},
    "nhl": {"teams": list(NHL_TEAMS), "url": "https://api-web.nhle.com/v1/roster/{team}/current",
            "player_url": "https://api-web.nhle.com/v1/player/{id}/landing", "college_sport": "hockey-mens",
            "new_season_month": 7, "colleges": {"Miami U.": "Miami (OH)"}},
}
ROSTER_FIELDS = ["league", "season", "team", "name", "number", "position", "status", "height", "weight",
                 "experience", "college", "college_until", "birth_city", "birth_state", "birth_country",
                 "pro_high_school", "profile_url"]
MATCH_FIELDS = ROSTER_FIELDS + ["college_school", "college_level", "matched", "college_name", "college_first",
                                "college_last", "hometown", "home_state", "home_country", "high_school"]
# The roster table's columns, by header text
_COLUMNS = {"player": "name", "name": "name", "no": "number", "#": "number", "pos": "position",
            "position": "position", "status": "status", "height": "height", "ht": "height", "weight": "weight",
            "wt": "weight", "experience": "experience", "exp": "experience", "college": "college"}
_SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv|v)\.?$", re.I)


def season_now(today: dt.date | None = None, league: str = "nfl") -> int:
    """The season a league's rosters show now, named by the year it starts: NFL rosters from March on belong to
    the coming fall, NBA and NHL ones from July (2026-27 = 2026), MLB's 40-man rosters from November to next
    year's season."""
    today = today or dt.date.today()
    month = LEAGUES[league]["new_season_month"]
    if month == 11:
        return today.year + 1 if today.month >= 11 else today.year
    return today.year if today.month >= month else today.year - 1


def _int(v) -> int | None:
    s = str(v or "").strip()
    return int(s) if s.isdigit() else None


# ---- reading each league's rosters ---------------------------------------------------------------------------

def parse_roster_page(html: str, site: str = "") -> list[dict]:
    """The players in a league roster page: the table with Player and College columns (NFL)."""
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


def parse_nba_page(html: str) -> list[dict]:
    """The roster in an nba.com team page's data (the __NEXT_DATA__ script): name, number, position, height,
    weight, years in the league ("R" for a rookie) and school."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    try:
        roster = json.loads(tag.string)["props"]["pageProps"]["team"]["roster"] if tag and tag.string else []
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for p in roster or []:
        name = clean(p.get("PLAYER"))
        if not name:
            continue
        slug, pid = p.get("PLAYER_SLUG") or "", p.get("PLAYER_ID") or ""
        out.append({"name": name, "number": clean(p.get("NUM")), "position": clean(p.get("POSITION")),
                    "height": clean(p.get("HEIGHT")), "weight": clean(p.get("WEIGHT")),
                    "experience": clean(p.get("EXP")), "college": clean(p.get("SCHOOL")),
                    "profile_url": f"https://www.nba.com/player/{pid}/{slug}" if pid else ""})
    return out


def parse_mlb_roster(text: str) -> list[dict]:
    """A team's 40-man roster from MLB's stats API, with each player's education: his colleges (several when he
    went to a junior college first, joined with " | "), his high school and his draft year."""
    try:
        roster = json.loads(text).get("roster", [])
    except ValueError:
        return []
    out = []
    for e in roster:
        p = e.get("person") or {}
        name = clean(p.get("fullName"))
        if not name:
            continue
        edu = p.get("education") or {}
        colleges = [clean(c.get("name")) for c in edu.get("colleges", []) if clean(c.get("name"))]
        hs = (edu.get("highschools") or [{}])[0]
        high_school = ", ".join(x for x in (clean(hs.get("name")), clean(hs.get("city")), clean(hs.get("state"))) if x)
        out.append({"name": name, "number": clean(e.get("jerseyNumber")),
                    "position": clean((e.get("position") or {}).get("abbreviation")),
                    "status": clean((e.get("status") or {}).get("description")),
                    "height": clean(p.get("height")), "weight": clean(p.get("weight")),
                    "debut": _int(clean(p.get("mlbDebutDate"))[:4]), "college": " | ".join(colleges),
                    # drafted out of college in June: his last college season is the spring of his draft year
                    "college_until": (p.get("draftYear") or "") if colleges else "",
                    "birth_city": clean(p.get("birthCity")), "birth_state": clean(p.get("birthStateProvince")),
                    "birth_country": clean(p.get("birthCountry")), "pro_high_school": high_school,
                    "profile_url": f"https://www.mlb.com/player/{p['id']}" if p.get("id") else ""})
    return out


def _default(v) -> str:
    return clean(v.get("default") if isinstance(v, dict) else v)


def parse_nhl_roster(text: str) -> list[dict]:
    """A team's roster from the NHL's API (forwards, defensemen, goalies). 'id' is for the player's own page."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for group in ("forwards", "defensemen", "goalies"):
        for p in data.get(group, []):
            name = f"{_default(p.get('firstName'))} {_default(p.get('lastName'))}".strip()
            if not name:
                continue
            inches = _int(p.get("heightInInches"))
            out.append({"id": p.get("id"), "name": name, "number": clean(p.get("sweaterNumber")),
                        "position": clean(p.get("positionCode")),
                        "height": f"{inches // 12}-{inches % 12}" if inches else "",
                        "weight": clean(p.get("weightInPounds")), "birth_city": _default(p.get("birthCity")),
                        "birth_state": _default(p.get("birthStateProvince")),
                        "birth_country": clean(p.get("birthCountry")),
                        "profile_url": f"https://www.nhl.com/player/{p['id']}" if p.get("id") else ""})
    return out


def nhl_college(text: str) -> tuple[str, int | None, int | None]:
    """(college, his last college season, his first NHL season) from a player's career in the NHL's API. College
    seasons are the regular seasons filed under NCAA or a college conference; "20152016" is season 2016 as
    college hockey numbers it. Several colleges (a transfer) are joined with " | ", the last one last."""
    try:
        seasons = json.loads(text).get("seasonTotals", [])
    except ValueError:
        return "", None, None
    colleges, last, first_nhl = [], None, None
    for s in sorted((s for s in seasons if s.get("gameTypeId") == 2), key=lambda s: (s.get("season", 0), s.get("sequence", 0))):
        year = _int(str(s.get("season", ""))[4:])
        league = clean(s.get("leagueAbbrev"))
        if league in NHL_COLLEGE_LEAGUES:
            team = _default(s.get("teamName"))
            if team and team not in colleges:
                colleges.append(team)
            last = year
        elif league == "NHL" and first_nhl is None:
            first_nhl = year
    return " | ".join(colleges), last, first_nhl


def _years_in_league(experience: str) -> int | None:
    """NFL.com's and nba.com's experience: 'R' for a rookie, else seasons in the league."""
    e = (experience or "").strip().upper()
    return 0 if e == "R" else int(e) if e.isdigit() else None


def college_until(league: str, season: int, experience: str) -> int | None:
    """His last college season, as the college sport numbers it, if he went straight to the league. Football
    names a season by its fall (an NFL rookie of 2026 last played college football in 2025); basketball by its
    spring (an NBA rookie of 2026-27 last played in 2025-26, season 2026)."""
    years = _years_in_league(experience)
    if years is None:
        return None
    return season - years - 1 if league == "nfl" else season - years


def scrape(league: str, season: int, refresh: bool) -> list[dict]:
    conf = LEAGUES[league]
    fetcher = Fetcher(cache_dir=CACHE, refresh=refresh, delay=2.0)
    careers = Fetcher(cache_dir=CACHE, refresh=False, delay=1.0)     # an NHL player's past seasons don't change
    rows, problems = [], []
    for team in conf["teams"]:
        url = conf["url"].format(team=team, slug=NBA_TEAMS.get(team, ""))
        label = {"nba": f"{NBA_TEAMS.get(team, '')}".title(), "mlb": MLB_TEAMS.get(team, ""),
                 "nhl": NHL_TEAMS.get(team, "")}.get(league) or str(team).replace("-", " ").title()
        try:
            status, _, text = fetcher.get(url, remember_miss=False)
        except Exception as exc:  # noqa: BLE001  (network trouble: say which team, keep going)
            problems.append(f"{label}: {exc}")
            continue
        if status != 200:
            players = []
        elif league == "nfl":
            players = parse_roster_page(text, conf["site"])
        elif league == "nba":
            players = parse_nba_page(text)
        elif league == "mlb":
            players = parse_mlb_roster(text)
        else:
            players = parse_nhl_roster(text)
        if not players:
            problems.append(f"{label}: HTTP {status}, no players read")
        for p in players:
            if league == "nhl" and p.get("id"):
                try:
                    st, _, career = careers.get(conf["player_url"].format(id=p["id"]), remember_miss=False)
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{label}, {p['name']}: {exc}")
                    st, career = 0, ""
                if st == 200:
                    p["college"], until, first_nhl = nhl_college(career)
                    p["college_until"] = until or ""
                    p["experience"] = season - first_nhl if first_nhl else ""
            elif league == "mlb":
                p["experience"] = season - p["debut"] if p.get("debut") else ""      # seasons since his debut
            elif league in ("nfl", "nba"):
                p["college_until"] = college_until(league, season, p.get("experience", "")) or ""
            rows.append({"league": league.upper(), "season": season, "team": label,
                         **{f: p.get(f, "") for f in ROSTER_FIELDS if f not in ("league", "season", "team")}})
        print(f"  {label:24} {len(players):3} players")
    for p in problems:
        print("  problem:", p)
    return rows


# ---- matching to the college rosters ---------------------------------------------------------------------------

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
                idx[k] = got = {"college_first": season, "hometown": "", "home_city": "", "home_state": "",
                                "home_country": "", "high_school": "", "college_name": r["name"],
                                "last_key": _last_name_key(r["name"]), "school": r["school"]}
            got["college_last"] = season
            for f in ("hometown", "home_city", "home_state", "home_country", "high_school"):
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


def _born_there(r: dict, info: dict) -> bool:
    """Is the town the pro league gives as his birthplace the hometown on the college roster?"""
    city, home = name_key(r.get("birth_city", "")), name_key(info.get("home_city", ""))
    if not city or city != home:
        return False
    a, b = (r.get("birth_state") or "").upper(), (info.get("home_state") or "").upper()
    return not a or not b or a == b


def _fits(until: int | None, info: dict) -> bool:
    return until is None or until - 2 <= int(info["college_last"]) <= until + 1


def match(rows: list[dict], league: str) -> list[dict]:
    """Find each pro player on his college's roster.

    matched = "yes": the same name on that school's roster (with several colleges listed, the one he's found
    at). "likely": the same last name at that school and first names that fit (_first_names_fit: "Sauce Gardner"
    is Ahmad "Sauce" Gardner, "Pat Surtain II" Patrick Surtain), taken only when exactly one such player's last
    college season fits the one worked out for him (college_until, give or take). "hometown": the league's
    college isn't found or his name isn't on its roster, but exactly one player with his name, at any school,
    lists the town he was born in as his hometown, in seasons that fit. Nicknames unlike the name ("Bam" for
    Zonovan Knight) stay unmatched rather than risk a wrong person."""
    conf = LEAGUES[league]
    sport = load_sport(conf["college_sport"])
    levels = Levels.load(sport)
    idx = college_index(sport.name)
    by_last, by_name = defaultdict(list), defaultdict(list)
    for (school, nk), info in idx.items():
        by_last[(school, info["last_key"])].append(info)
        by_name[nk].append(info)
    out = []
    for r in rows:
        season = int(r["season"])
        until = _int(r.get("college_until"))
        if until is None and league == "nfl":            # roster files saved before college_until existed
            until = college_until(league, season, r.get("experience", ""))
        nk = name_key(_SUFFIX.sub("", r["name"]))
        listed = [x.strip() for x in (r.get("college") or "").split("|") if x.strip()]
        schools = []
        for text in listed:
            text = conf.get("colleges", {}).get(text, text)
            lvl, school = levels.level(text, (until or season - 1))
            if school:
                schools.append((lvl, school))
        level, school = schools[-1] if schools else ("", "")
        hit, how = None, ""
        for lvl, sch in schools:
            if (sch, nk) in idx:
                (level, school), hit, how = (lvl, sch), idx[(sch, nk)], "yes"
        if not hit and schools:
            fits = [i for lvl, sch in schools for i in by_last.get((sch, _last_name_key(r["name"])), [])
                    if until is not None and _fits(until, i) and _first_names_fit(r["name"], i["college_name"])]
            if len(fits) == 1:
                hit, how = fits[0], "likely"
                level, school = next((lvl, sch) for lvl, sch in schools if sch == hit["school"])
        if not hit and listed and r.get("birth_city"):
            fits = [i for i in by_name.get(nk, []) if _born_there(r, i) and _fits(until, i)]
            if len(fits) == 1:
                hit, how = fits[0], "hometown"
                school = hit["school"]
                level = levels.level(school, int(hit["college_last"]))[0]
        info = {k: v for k, v in (hit or {}).items() if k not in ("last_key", "school", "home_city")}
        out.append({**r, "college_school": school, "college_level": level if school else "", "matched": how, **info})
    return out


def summary(rows: list[dict]) -> None:
    n = len(rows)
    with_college = sum(1 for r in rows if r["college"])
    known = sum(1 for r in rows if r["college_school"])
    matched = Counter(r["matched"] for r in rows if r["matched"])
    total = sum(matched.values())
    print(f"{n} players; {with_college} list a college; {known} of those colleges are in schools.csv; "
          f"{total} found on a college roster ({total / max(1, with_college):.0%} of those with a college; "
          f"{matched['yes']} by name, {matched['likely']} by last name, {matched['hometown']} by hometown)")
    print("  by division:", dict(Counter(r["college_level"] or "?" for r in rows if r["matched"]).most_common()))
    print("  with a hometown:", sum(1 for r in rows if r.get("hometown")),
          "| with a high school:", sum(1 for r in rows if r.get("high_school") or r.get("pro_high_school")))
    missing = Counter(c for r in rows if r["college"] and not r["college_school"] for c in [r["college"]])
    if missing:
        print("  colleges not in schools.csv (most players first):", missing.most_common(15))
    unmatched = Counter(r["college_school"] for r in rows if r["college_school"] and not r["matched"])
    if unmatched:
        print("  known college, name not on its roster (most first):", unmatched.most_common(10))


def run(league: str, season: int | None, refresh: bool, match_only: bool) -> int:
    season = season or season_now(league=league)
    roster_path = PRO_DIR / f"{league}_{season}.csv"
    if match_only:
        rows = read_csv(roster_path)
        if not rows:
            print(f"{roster_path} not found or empty: run without --match-only first.")
            return 1
    else:
        print(f"{league.upper()} {season}: reading {len(LEAGUES[league]['teams'])} rosters")
        rows = scrape(league, season, refresh)
        if not rows:
            print("No players read; nothing saved.")
            return 1
        write_csv(roster_path, ROSTER_FIELDS, rows)
        print(f"-> {roster_path}")
    matched = match(rows, league)
    out_path = PRO_DIR / f"{league}_{season}_matched.csv"
    write_csv(out_path, MATCH_FIELDS, matched)
    summary(matched)
    print(f"-> {out_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("leagues", nargs="+", choices=sorted(LEAGUES) + ["all"], metavar="league",
                    help=f"{', '.join(LEAGUES)} or all")
    ap.add_argument("--season", type=int, help="default: the season each league's rosters show now")
    ap.add_argument("--refresh", action="store_true", help="download the rosters again")
    ap.add_argument("--match-only", action="store_true", help="redo the matching from the saved roster file")
    args = ap.parse_args(argv)
    PRO_DIR.mkdir(parents=True, exist_ok=True)
    leagues = list(LEAGUES) if "all" in args.leagues else list(dict.fromkeys(args.leagues))
    failed = [lg for lg in leagues if run(lg, args.season, args.refresh, args.match_only)]
    if failed:
        print("No result for:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
