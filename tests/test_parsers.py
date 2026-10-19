"""Run with:  python -m pytest tests -q"""
import json
from pathlib import Path

from scrape_rosters import normalize_class, parse_hometown, parse_roster, split_hometown_highschool

FIX = Path(__file__).parent / "fixtures"


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


def test_sidearm_nextgen_table():
    strategy, players = parse_roster((FIX / "sidearm_nextgen_table.html").read_text())
    assert strategy == "html_table"
    assert len(players) == 4  # coaching staff table ignored
    p = players[2]
    assert p["name"] == "Devan Thompkins"
    assert p["hometown"] == "Tracy, Calif." and p["high_school"] == "Edison"
    assert p["previous_school"] == "USC" and p["position"] == "DL" and p["height"] == "6-5"
    assert p["bio_url"].endswith("/devan-thompkins/17536")


def test_sidearm_classic():
    strategy, players = parse_roster((FIX / "sidearm_classic.html").read_text())
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


def test_hometown_parsing():
    assert parse_hometown("Mobile, Ala.") == {"city": "Mobile", "state": "AL", "country": "USA"}
    assert parse_hometown("St. Louis, MO") == {"city": "St. Louis", "state": "MO", "country": "USA"}
    assert parse_hometown("Washington, D.C.")["state"] == "DC"
    assert parse_hometown("Melbourne, Australia") == {"city": "Melbourne", "state": "", "country": "Australia"}
    assert parse_hometown("Toronto, Ont.")["country"] == "Canada"
    assert parse_hometown("Houston, Texas, USA")["state"] == "TX"
    assert parse_hometown("Fort Worth, Texas (Paschal HS)")["city"] == "Fort Worth"
    assert split_hometown_highschool("Tracy, Calif. / Edison") == ("Tracy, Calif.", "Edison")


def test_class_normalization():
    cases = {"Fr.": "FR", "R-Fr.": "R-FR", "Redshirt Sophomore": "R-SO", "Jr.": "JR", "Sr.": "SR",
             "Gr.": "GR", "5th": "GR", "2nd": "SO", "Graduate": "GR", "So.": "SO"}
    for raw, want in cases.items():
        assert normalize_class(raw) == want, raw


def test_old_sidearm_vue_roster_not_duplicated():
    # Shape from utahstateaggies.com: `roster: {...}` JS object with the same players listed twice
    # (players + players_by_gender.M) and a roster-level "title". Previously produced ~2x rows.
    players = [{"rp_id": i, "first_name": f"Kian{i} ", "last_name": "Test", "hometown": f"Town{i % 5}, Calif.",
                "highschool": "Dana Hills HS", "previous_school": "", "position_short": "WR",
                "academic_year_short": "Jr.", "jersey_number": str(i), "height_feet": 6, "height_inches": 1,
                "weight": 200} for i in range(40)]
    roster = {"id": 1, "title": "2026 Football Roster", "season": {"title": "2026"},
              "sport": {"title": "Football"}, "players": players,
              "coaches": [{"firstname": "Bronco", "lastname": "M", "title": "Head Coach"}],
              "players_by_gender": {"M": players}}
    html = ("<script>require(['vue'], function (Vue) { Vue.component('x', { data: () => ({ roster: "
            + json.dumps(roster) + " }) }) })</script>")
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


# --- regression tests for the October 2026 fixes ----------------------------

def test_hometown_with_school_attached():
    assert parse_hometown("Atlanta, Ga. / Westlake HS") == {"city": "Atlanta", "state": "GA", "country": "USA"}
    assert parse_hometown("Houston, Texas (Alief Taylor)")["state"] == "TX"
    assert parse_hometown("Houston, Texas - Lamar HS")["state"] == "TX"
    assert parse_hometown("Hometown/Last School: Mobile, Ala.")["city"] == "Mobile"
    assert parse_hometown("Winston-Salem, N.C.")["city"] == "Winston-Salem"


def test_more_class_spellings():
    cases = {"RS-Fr": "R-FR", "Fy.": "FR", "Sixth Year": "GR", "r so": "R-SO", "Senior": "SR"}
    for raw, want in cases.items():
        assert normalize_class(raw) == want, raw


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


# --- coaches and staff must never come through as players --------------------

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
