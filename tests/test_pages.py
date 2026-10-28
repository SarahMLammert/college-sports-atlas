"""Reading roster pages: the parsers, class years, names, staff, and sorting high school from previous school
(scripts/sidearm.py and scripts/scrape_rosters.py)."""
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import scrape_rosters as sr
from paths import load_sport
from scrape_rosters import normalize_class, parse_hometown, parse_roster, split_hometown_highschool
from sidearm import parse_sidearm_classic

HERE = Path(__file__).parent


@pytest.fixture(autouse=True)
def football():
    """Football's settings and junior colleges (so "Iowa Western" counts as a college) for every test here,
    whatever an earlier test configured."""
    sr.sidearm.configure(load_sport("football"))
    sr.load_known_colleges([{"school": n} for n in
                            ["Wake Forest", "Notre Dame", "SMU", "Texas", "Miami (FL)", "Duke", "Alabama", "Texas Tech"]])


# ---------------------------------------------------------------------------- page builders

def devalue_flatten(value) -> list:
    """Minimal devalue encoder (inverse of decode_devalue) to build realistic __NUXT_DATA__ payloads."""
    out: list = []
    ids: dict[int, int] = {}

    def add(v):
        if isinstance(v, (dict, list)) and id(v) in ids:
            return ids[id(v)]
        idx = len(out)
        out.append(None)
        if isinstance(v, dict):
            ids[id(v)] = idx
            out[idx] = {k: add(x) for k, x in v.items()}
        elif isinstance(v, list):
            ids[id(v)] = idx
            out[idx] = [add(x) for x in v]
        else:
            out[idx] = v
        return idx

    # Nuxt wraps the root in ["ShallowReactive", 1]
    out.append(["ShallowReactive", 1])
    add(value)
    return out


def nuxt_page(tree) -> str:
    payload = json.dumps(devalue_flatten(tree))
    return f'<html><body><div id="__nuxt"></div><script type="application/json" id="__NUXT_DATA__" data-ssr="true">{payload}</script></body></html>'


def roster(html):
    return {p["name"]: p for p in sr.parse_roster(html)[1]}


# ---------------------------------------------------------------------------- parsers

def test_sidearm_nextgen_table():
    strategy, players = parse_roster((HERE / "sidearm_nextgen_table.html").read_text())
    assert strategy == "html_table"
    assert len(players) == 4  # coaching staff table ignored
    p = players[2]
    assert p["name"] == "Devan Thompkins"
    assert p["hometown"] == "Tracy, Calif." and p["high_school"] == "Edison"
    assert p["previous_school"] == "USC" and p["position"] == "DL" and p["height"] == "6-5"
    assert p["bio_url"].endswith("/devan-thompkins/17536")


def test_sidearm_classic():
    strategy, players = parse_roster((HERE / "sidearm_classic.html").read_text())
    assert strategy == "sidearm_classic"
    a, b = players
    assert (a["name"], a["jersey"], a["position"], a["class_year"]) == ("John Smith", "7", "QB", "R-Jr.")
    assert (a["hometown"], a["high_school"], a["previous_school"]) == ("Fargo, N.D.", "Fargo South", "Iowa State")
    assert a["height"] == "6-2" and a["weight"] == "210"
    assert b["hometown"] == "Stockholm, Sweden"


def test_sidearm_nuxt_payload():
    # Shape copied from gobison.com (Sidearm nextgen): pinia.roster.roster.<id>.players[]
    players = [
        {"playerId": 7018, "firstName": "Preston", "lastName": "Brown", "hometown": "Hillsboro, Mo.",
         "highSchool": "Hillsboro HS", "previousSchool": "", "positionShort": "QB", "positionLong": "Quarterback",
         "heightFeet": 6, "heightInches": 1, "weight": 215, "academicYearShort": "2nd", "jerseyNumber": "0",
         "image": {"title": "Preston Brown"}, "sport": {"title": "Football"}, "position": None,
         "call_to_action": "/sports/football/roster/preston-brown/24396"},
        {"playerId": 7019, "firstName": "Cam", "lastName": "Miller", "hometown": "Rosemount, Minn.",
         "highSchool": "Rosemount", "previousSchool": "", "positionShort": "QB", "heightFeet": 6,
         "heightInches": 0, "weight": 214, "academicYearShort": "Sr.", "jerseyNumber": "6"},
    ]
    coaches = [{"firstName": "Tim", "lastName": "Polasek", "title": "Head Coach"}]
    tree = {"data": {}, "pinia": {"roster": {"roster": {"2316": {"players": players, "coaches": coaches}}}}}
    strategy, out = parse_roster(nuxt_page(tree))
    assert strategy == "nuxt_data"
    assert [p["name"] for p in out] == ["Preston Brown", "Cam Miller"]
    p = out[0]
    assert (p["position"], p["class_year"], p["height"], p["weight"], p["jersey"]) == ("QB", "2nd", "6-1", "215", "0")
    assert p["high_school"] == "Hillsboro HS" and p["bio_url"].endswith("/24396")


def test_wmt_nuxt_payload():
    # Shape copied from clemsontigers.com (WMT): data.roster-<id>-players-list[] -> {player:{...}, class_level, player_position}
    sport = {"id": 20, "name": "Football"}
    pos_de, pos_s = {"id": 45, "abbreviation": "DE", "name": "DE"}, {"id": 50, "abbreviation": "S", "name": "S"}
    fr = {"abbreviation": None, "id": 2, "name": "Fr.", "order": 0}
    p1 = {"id": 3478, "first_name": "Michael", "last_name": "Foster", "full_name": "Michael Foster",
          "weight": 240, "height_feet": 6, "height_inches": 1, "jersey_number": 32, "player_position": pos_de,
          "hometown": "Charlotte, N.C.", "high_school": "Indian Land (S.C.) HS", "previous_school": None,
          "class_level": fr, "short_master_biography": "<p>bio</p>"}
    p2 = {"id": 3479, "first_name": "Polo", "last_name": "Anderson", "full_name": "Polo Anderson",
          "weight": 190, "height_feet": 6, "height_inches": 2, "jersey_number": 11, "player_position": pos_s,
          "hometown": "Spartanburg, S.C.", "high_school": "Dorman", "previous_school": None, "class_level": fr}
    lst = [
        {"id": 7553, "player": p1, "roster": {"id": 276, "sport": sport}, "jersey_number": 32,
         "player_position": pos_de, "class_level": fr, "relative_url": "/sports/football/roster/player/michael-foster"},
        {"id": 7554, "player": p2, "roster": {"id": 276, "sport": sport}, "jersey_number": 11,
         "player_position": pos_s, "class_level": fr},
    ]
    tree = {"data": {"sport-view-football": {"name": "Football"}, "roster-276-players-list": lst}}
    strategy, out = parse_roster(nuxt_page(tree))
    assert strategy == "nuxt_data"
    assert len(out) == 2
    f = out[0]
    assert (f["name"], f["position"], f["class_year"], f["jersey"], f["height"]) == ("Michael Foster", "DE", "Fr.", "32", "6-1")
    assert f["hometown"] == "Charlotte, N.C." and f["high_school"] == "Indian Land (S.C.) HS"
    assert f["bio_url"] == "/sports/football/roster/player/michael-foster"


def test_embedded_json_fallback():
    data = {"props": {"pageProps": {"roster": [
        {"name": "Joe Tester", "hometown": "Austin, Texas", "position": "WR", "class": "So."}]}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    strategy, out = parse_roster(html)
    assert strategy == "embedded_json" and out[0]["hometown"] == "Austin, Texas"


def test_old_sidearm_vue_roster_not_duplicated():
    # Shape from utahstateaggies.com: `roster: {...}` JS object with the same players listed twice
    # (players + players_by_gender.M) and a roster-level "title". Previously produced ~2x rows.
    players = [{"rp_id": i, "first_name": f"Kian{i} ", "last_name": "Test", "hometown": f"Town{i % 5}, Calif.",
                "highschool": "Dana Hills HS", "previous_school": "", "position_short": "WR",
                "academic_year_short": "Jr.", "jersey_number": str(i), "height_feet": 6, "height_inches": 1,
                "weight": 200} for i in range(40)]
    roster_obj = {"id": 1, "title": "2026 Football Roster", "season": {"title": "2026"},
                  "sport": {"title": "Football"}, "players": players,
                  "coaches": [{"firstname": "Bronco", "lastname": "M", "title": "Head Coach"}],
                  "players_by_gender": {"M": players}}
    html = ("<script>require(['vue'], function (Vue) { Vue.component('x', { data: () => ({ roster: "
            + json.dumps(roster_obj) + " }) }) })</script>")
    strategy, out = parse_roster(html)
    assert strategy == "embedded_json"
    assert len(out) == 40
    assert out[0]["name"] == "Kian0 Test" and out[0]["high_school"] == "Dana Hills HS"
    assert out[0]["position"] == "WR" and out[0]["class_year"] == "Jr."


def test_table_hs_previous_split_and_link_name_fallback():
    html = """<table><thead><tr><th>No.</th><th>Name</th><th>Pos.</th><th>Cl.</th><th>Hometown</th>
    <th>High School/Previous School</th></tr></thead><tbody>
    <tr><td>1</td><td><a href="/sports/fball/2026-27/bios/john_doe_x7k2p" aria-label="John Doe: jersey 1: full bio"></a></td>
        <td>WR</td><td>Gr.</td><td>Trussville, Ala.</td><td>Hewitt-Trussville HS / Virginia</td></tr>
    <tr><td>2</td><td><a href="/sports/fball/2026-27/bios/sam_lee"></a></td>
        <td>QB</td><td>Fr.</td><td>Newark, NJ</td><td>Weequahic</td></tr>
    </tbody></table>"""
    _, out = parse_roster(html)
    assert out[0]["name"] == "John Doe"
    assert (out[0]["high_school"], out[0]["previous_school"]) == ("Hewitt-Trussville HS", "Virginia")
    assert out[1]["name"] == "Sam Lee" and out[1]["high_school"] == "Weequahic"


def test_classic_long_position_kept_whole():
    html = """<ul><li class="sidearm-roster-player">
      <div class="sidearm-roster-player-name"><h3><a href="/x">Pat Long</a></h3></div>
      <div class="sidearm-roster-player-position"><span>Defensive Back 6'0" 190 lbs</span></div>
      <span class="sidearm-roster-player-hometown">Tulsa, Okla.</span></li></ul>"""
    _, out = parse_roster(html)
    assert out[0]["position"] == "Defensive Back"


def test_bad_height_does_not_drop_roster():
    players = [{"firstName": f"P{i}", "lastName": "X", "hometown": "Ames, Iowa",
                "heightFeet": "6'2\"" if i == 0 else 6, "heightInches": 1} for i in range(30)]
    strategy, out = parse_roster(nuxt_page({"pinia": {"roster": {"players": players}}}))
    assert strategy == "nuxt_data" and len(out) == 30


def test_deep_devalue_payload_no_recursion():
    from scrape_rosters import decode_devalue
    raw = [[1]] + [[i + 1] for i in range(1, 100_000)] + ["end"]
    decode_devalue(raw)  # used to need a huge recursion limit


# ---------------------------------------------------------------------------- class years

def test_class_normalization():
    cases = {"Fr.": "FR", "R-Fr.": "R-FR", "Redshirt Sophomore": "R-SO", "Jr.": "JR", "Sr.": "SR",
             "Gr.": "GR", "5th": "GR", "2nd": "SO", "Graduate": "GR", "So.": "SO",
             "RS-Fr": "R-FR", "Fy.": "FR", "Sixth Year": "GR", "r so": "R-SO", "Senior": "SR"}
    for raw, want in cases.items():
        assert normalize_class(raw) == want, raw


CARD_PAGE = """
<ul class="sidearm-roster-players">
  <li class="sidearm-roster-player" data-player-id="20891">
    <div class="sidearm-roster-player-name"><h3><a href="/sports/football/roster/xavier-coleman/20891">Xavier Coleman</a></h3></div>
    <span class="sidearm-roster-player-position-long-short">Running Back</span>
    <div class="sidearm-roster-player-class-hometown">
      <span class="sidearm-roster-player-hometown">Willingboro, N.J.</span>
      <span class="sidearm-roster-player-highschool">Lenape HS</span>
    </div>
  </li>
  <li class="sidearm-roster-player" data-player-id="20900">
    <div class="sidearm-roster-player-name"><h3><a href="/sports/football/roster/sam-lee/20900">Sam Lee</a></h3></div>
    <div class="sidearm-roster-player-class-hometown">
      <span class="sidearm-roster-player-hometown">Beaumont, Texas</span>
    </div>
  </li>
  <li class="sidearm-roster-player" data-player-id="20950">
    <div class="sidearm-roster-player-name"><h3><a href="/sports/football/roster/joe-ray/20950">Joe Ray</a></h3></div>
    <span class="sidearm-roster-player-academic-year">Sr.</span>
  </li>
</ul>
<ul class="sidearm-list-card-template-1">
  <li class="sidearm-list-card-item" data-player-id="20891">
    <a class="sidearm-roster-player-name" href="/sports/football/roster/xavier-coleman/20891">Xavier Coleman</a>
    <span class="sidearm-roster-player-academic-year">Jr.</span>
  </li>
  <li class="sidearm-list-card-item">
    <a class="sidearm-roster-player-name" href="/sports/football/roster/sam-lee/20900/">Sam Lee</a>
    <span class="sidearm-roster-player-academic-year">Fy.</span>
  </li>
  <li class="sidearm-list-card-item" data-player-id="20950">
    <a class="sidearm-roster-player-name" href="/sports/football/roster/joe-ray/20950">Joe Ray</a>
    <span class="sidearm-roster-player-academic-year">Jr.</span>
  </li>
</ul>
"""


def test_class_year_from_card_view():
    """Sidearm pages that hold the roster twice (Lamar, Linfield, Bates, Hamilton, Puget Sound): the classic
    list has no class year, the card view further down does. The classic parser takes the year from the cards."""
    players = {p["name"]: p for p in parse_sidearm_classic(CARD_PAGE, BeautifulSoup(CARD_PAGE, "lxml"))}
    assert players["Xavier Coleman"]["class_year"] == "Jr."      # matched by player id
    assert players["Sam Lee"]["class_year"] == "Fy."             # matched by page link
    assert players["Joe Ray"]["class_year"] == "Sr."             # the list's own year is kept
    assert players["Xavier Coleman"]["hometown"] == "Willingboro, N.J."
    assert "_player_id" not in players["Xavier Coleman"]


# ---------------------------------------------------------------------------- hometowns on the page

def test_hometown_parsing():
    assert parse_hometown("Mobile, Ala.") == {"city": "Mobile", "state": "AL", "country": "USA"}
    assert parse_hometown("St. Louis, MO") == {"city": "St. Louis", "state": "MO", "country": "USA"}
    assert parse_hometown("Washington, D.C.")["state"] == "DC"
    assert parse_hometown("Melbourne, Australia") == {"city": "Melbourne", "state": "", "country": "Australia"}
    assert parse_hometown("Toronto, Ont.")["country"] == "Canada"
    assert parse_hometown("Houston, Texas, USA")["state"] == "TX"
    assert parse_hometown("Fort Worth, Texas (Paschal HS)")["city"] == "Fort Worth"
    assert split_hometown_highschool("Tracy, Calif. / Edison") == ("Tracy, Calif.", "Edison")


def test_hometown_with_school_attached():
    assert parse_hometown("Atlanta, Ga. / Westlake HS") == {"city": "Atlanta", "state": "GA", "country": "USA"}
    assert parse_hometown("Houston, Texas (Alief Taylor)")["state"] == "TX"
    assert parse_hometown("Houston, Texas - Lamar HS")["state"] == "TX"
    assert parse_hometown("Hometown/Last School: Mobile, Ala.")["city"] == "Mobile"
    assert parse_hometown("Winston-Salem, N.C.")["city"] == "Winston-Salem"


# ---------------------------------------------------------------------------- coaches, staff and names

def test_nuxt_coaches_with_hometowns_dropped():
    players = [{"firstName": f"P{i}", "lastName": "X", "hometown": "Ames, Iowa", "positionShort": "WR",
                "jerseyNumber": str(i)} for i in range(30)]
    coaches = [{"firstName": "Tim", "lastName": "Coach", "hometown": "Fargo, N.D.", "title": "Head Coach"}]
    strategy, out = parse_roster(nuxt_page({"pinia": {"roster": {"players": players, "coaches": coaches}}}))
    assert strategy == "nuxt_data" and len(out) == 30
    assert all(p["name"] != "Tim Coach" for p in out)


def test_staff_titles_in_player_fields_dropped():
    from scrape_rosters import drop_staff, is_staff
    assert is_staff({"position": "Student Manager"})
    assert is_staff({"class_year": "Head Coach"})
    assert is_staff({"position": "Director of Football Operations"})
    assert not is_staff({"position": "WR", "class_year": "Medical Redshirt"})
    assert not is_staff({"position": "LS", "class_year": "Gr."})
    rows = [{"name": f"P{i}", "position": "OL", "jersey": str(i)} for i in range(20)]
    rows.append({"name": "Pat Helper", "position": "", "jersey": "", "hometown": "Waco, Texas"})
    assert len(drop_staff(rows)) == 20


def test_staff_table_with_hometown_column_ignored():
    html = """<table><thead><tr><th>Name</th><th>Title</th><th>Hometown</th></tr></thead>
      <tbody><tr><td>Sam Boss</td><td>Head Coach</td><td>Tulsa, Okla.</td></tr></tbody></table>"""
    _, out = parse_roster(html)
    assert out == []


def test_clean_name_strips_numbers_and_captain_marks():
    from scrape_rosters import clean_name
    for raw in ("89 Mason Thomas", "#89 Mason Thomas", "Mason Thomas 89", "C Mason Thomas", "C 89 Mason Thomas",
                "Mason Thomas (C)", "Mason Thomas ©", "Mason Thomas*", "Mason Thomas Mason Thomas"):
        assert clean_name(raw) == "Mason Thomas", raw
    for keep in ("C.J. Stroud", "CJ Stroud", "C J Stroud", "Charles Woodson", "Tre' Harbison"):
        assert clean_name(keep) == keep, keep


# ---------------------------------------------------------------------------- previous school vs. high school

def test_looks_like_college():
    for v in ["Texas Tech", "Wake Forest", "Blinn College", "Butler CC", "Univ. of Iowa", "University of Miami",
              "Penn State", "Prairie View A&M", "Miami (FL)", "SMU", "Naval Academy", "Saddleback College"]:
        assert sr.looks_like_college(v), v
    for v in ["Lamar HS", "IMG Academy", "Mater Dei", "College Park High School", "Fork Union Military Academy",
              "C.C. Winn", "St. Thomas Aquinas", "Bishop Gorman", "", "Westlake H.S.", "Tech High School"]:
        assert not sr.looks_like_college(v), v


def sort(hs, prev):
    p = sr.sort_schools({"high_school": hs, "previous_school": prev})
    return p["high_school"], p["previous_school"]


def test_sort_schools():
    assert sort("Lamar HS / Texas Tech", "") == ("Lamar HS", "Texas Tech")      # combined field
    assert sort("Wake Forest", "") == ("", "Wake Forest")                       # "Last School" = a college
    assert sort("Mater Dei", "") == ("Mater Dei", "")                           # a high school stays put
    assert sort("Mater Dei", "Saddleback") == ("Mater Dei", "Saddleback")       # two fields: trust the site
    assert sort("Duke", "Lamar HS") == ("Lamar HS", "Duke")                     # swapped
    assert sort("", "IMG Academy") == ("IMG Academy", "")                       # a prep school isn't a transfer
    assert sort("", "Pickerington Central") == ("Pickerington Central", "")     # only school listed, not a college
    assert sort("", "Iowa Western") == ("", "Iowa Western")                     # a junior college stays
    assert sort("", "Hutchinson CC") == ("", "Hutchinson CC")
    assert sort("Menard HS", "Menard") == ("Menard HS", "")                     # the same school twice
    assert sort("Rancho Cucamonga", "Rancho Cucamonga High School (Calif.)") == ("Rancho Cucamonga", "")
    assert sort("Rockwall", "Rockwall HS") == ("Rockwall", "")
    assert sort("Steilacoom", "Lakes High School") == ("Steilacoom", "")        # a different high school: still not a transfer
    assert sort("Coronado HS", "Blinn College") == ("Coronado HS", "Blinn College")
    assert sort("Blinn College / Texas Tech", "") == ("", "Texas Tech")         # most recent college last
    assert sort("Lamar HS", "Blinn College / Texas Tech") == ("Lamar HS", "Texas Tech")
    assert sort("Lamar HS", "Texas") == ("Lamar HS", "Texas")
    assert sort("", "") == ("", "")


def test_nuxt_last_school_and_parent_entry():
    data = {"roster": [
        {"firstName": "Sam", "lastName": "Hartman", "hometown": "Charlotte, N.C.", "lastSchool": "Wake Forest", "position": "QB"},
        {"firstName": "Joe", "lastName": "Freshman", "hometown": "Austin, Texas", "lastSchool": "Westlake HS", "position": "WR"},
        # WMT: season entry (parent) carries the previous school, the nested player record the hometown
        {"position": "RB", "previousSchool": "Duke", "player": {"firstName": "Riley", "lastName": "Leonard",
                                                                 "hometown": "Fairhope, Ala.", "highSchool": "Fairhope HS"}},
    ]}
    html = f'<script id="__NUXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    r = roster(html)
    assert r["Sam Hartman"]["previous_school"] == "Wake Forest" and r["Sam Hartman"]["high_school"] == ""
    assert r["Joe Freshman"]["high_school"] == "Westlake HS" and r["Joe Freshman"]["previous_school"] == ""
    assert r["Riley Leonard"]["previous_school"] == "Duke" and r["Riley Leonard"]["high_school"] == "Fairhope HS"


def test_table_last_school_and_college_columns():
    html = """<table><thead><tr><th>No.</th><th>Name</th><th>Pos.</th><th>Hometown / Last School</th></tr></thead><tbody>
      <tr><td>10</td><td>Sam Hartman</td><td>QB</td><td>Charlotte, N.C. / Wake Forest</td></tr>
      <tr><td>11</td><td>Joe Freshman</td><td>WR</td><td>Austin, Texas / Westlake HS</td></tr></tbody></table>
      <table><thead><tr><th>#</th><th>Name</th><th>Pos</th><th>Hometown</th><th>High School</th><th>College</th></tr></thead><tbody>
      <tr><td>1</td><td>Al Transfer</td><td>DB</td><td>Miami, Fla.</td><td>Central HS</td><td>Miami (FL)</td></tr></tbody></table>"""
    soup = sr.BeautifulSoup(html, "lxml")
    rows = {p["name"]: p for p in sr.tidy_players(sr.parse_html_tables(html, soup))}
    assert rows["Sam Hartman"]["hometown"] == "Charlotte, N.C." and rows["Sam Hartman"]["previous_school"] == "Wake Forest"
    assert rows["Joe Freshman"]["high_school"] == "Westlake HS" and not rows["Joe Freshman"]["previous_school"]
    # the second table is smaller, so check its header mapping directly
    assert sr._header_field("College") == "previous_school"
    assert sr._header_field("Former School") == "previous_school"


def test_sidearm_classic_combined_school_field():
    html = """<ul><li class="sidearm-roster-player"><div class="sidearm-roster-player-name"><h3><a href="/bio/1">Pat Mover</a></h3></div>
      <span class="sidearm-roster-player-position">LB</span><span class="sidearm-roster-player-hometown">Lubbock, Texas</span>
      <span class="sidearm-roster-player-highschool">Coronado HS / Texas Tech</span></li></ul>"""
    p = roster(html)["Pat Mover"]
    assert p["high_school"] == "Coronado HS" and p["previous_school"] == "Texas Tech"


def test_recombine_fixes_saved_rows():
    """Rows saved by the old version (college stuck in high_school) are fixed when the files are rebuilt."""
    row = {"high_school": "Wake Forest", "previous_school": ""}
    sr.sort_schools(row)
    assert row == {"high_school": "", "previous_school": "Wake Forest"}
