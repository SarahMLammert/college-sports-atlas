"""All the tests, in one file. Run them from the project folder:

    python3 -m pytest tests -q

Sections: hometowns (parser, geocoder, fixer); roster pages; hometown labels and school levels; running a
scrape (sizes, addresses, seasons, downloads, the lock, pipeline.py, the checks); staff; hockey. conftest.py puts
scripts/ on the import path.

What's tested (Oct 28 review): behaviour that would quietly put wrong data on the maps if it broke (parsing pages
and hometowns, levels, transfers, seasons, which pages count) and the pipeline's own rules. Not tested: the wording
of messages, settings files' contents, and one-time fixes for files from before a change.
"""
import csv
import json
import logging
import zipfile
from datetime import date
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

import core
import geocode as geo
import build
import hometown_fixes
import scrape_rosters as sr
import sidearm
import hometown_fixes as sug
from geocode import not_a_place, parse_hometown, split_labeled_hometown
from core import Levels, is_major, key
from core import load_sport
from scrape_rosters import normalize_class, parse_roster, split_hometown_highschool
from sidearm import parse_sidearm_classic


# ==================================================================================================
# Hometowns: parsing, the geocoder, the fixer
# ==================================================================================================

def home(city, state, country):
    return {"city": city, "state": state, "country": country}


# ---------------------------------------------------------------------------
# parse_hometown

@pytest.mark.parametrize("raw, want", [
    # US: AP abbreviations, misspellings and stray punctuation
    ("Mobile, Ala.", home("Mobile", "AL", "USA")),
    ("St. Louis, MO", home("St. Louis", "MO", "USA")),
    ("Washington, D.C.", home("Washington", "DC", "USA")),
    ("Darien, III.", home("Darien", "IL", "USA")),
    ("Purcellville, Virg.", home("Purcellville", "VA", "USA")),
    ("Randleman, N,C,", home("Randleman", "NC", "USA")),
    ("St, Joseph, Mo.", home("St. Joseph", "MO", "USA")),
    ("Rockledge, Fla. USA", home("Rockledge", "FL", "USA")),
    ("Syosset, Long Island", home("Syosset", "NY", "USA")),
    ("Kona, Hawai‘i", home("Kona", "HI", "USA")),
    ("Maui", home("Maui", "HI", "USA")),
    # territories
    ("St. Croix, USVI", home("St. Croix", "VI", "USA")),
    ("Puerto Rico", home("", "PR", "USA")),
    ("Cidra PR", home("Cidra", "PR", "USA")),
    ("Pago Pago (AS)", home("Pago Pago", "AS", "USA")),
    # Canada, never California
    ("Winnipeg, MB", home("Winnipeg", "MB", "Canada")),
    ("Brandon, Manitoba, CA", home("Brandon", "MB", "Canada")),
    ("Bolton, Ontario Canada", home("Bolton", "ON", "Canada")),
    ("Calgary AB", home("Calgary", "AB", "Canada")),
    ("Montreal, Quebec, Canada", home("Montreal", "QC", "Canada")),
    ("Laval, PQ", home("Laval", "QC", "Canada")),
    ("Paradise, N.L.", home("Paradise", "NL", "Canada")),
    ("Spijkenisse, NL", home("Spijkenisse", "", "NL")),        # plain NL: the geocoder decides (Newfoundland or Dutch)
    # abroad: names, codes and misspellings
    ("Sydney, Australia", home("Sydney", "", "Australia")),
    ("Santo Domingo DR", home("Santo Domingo", "", "Dominican Republic")),
    ("Tokyo, JPN", home("Tokyo", "", "Japan")),
    ("Stockholm, SWE", home("Stockholm", "", "Sweden")),
    ("Zlin, Cze.", home("Zlin", "", "Czech Republic")),
    ("Paderno Dugnano, Lombardia Italy", home("Paderno Dugnano", "", "Italy")),
    ("Bogota, Columbia", home("Bogota", "", "Colombia")),
    # left alone: a town alone, a town that is also a country or a state
    ("Saint Louis", home("Saint Louis", "", "")),
    ("Lebanon", home("Lebanon", "", "")),
    ("Las Cruces New Mexico", home("Las Cruces New Mexico", "", "")),
    # school, label or bats/throws text around the town
    ("Atlanta, Ga. / Westlake HS", home("Atlanta", "GA", "USA")),
    ("Fort Worth, Texas (Paschal HS)", home("Fort Worth", "TX", "USA")),
    ("Hometown/Previous School(s): Omaha, Neb.", home("Omaha", "NE", "USA")),
    ("HS City (State): Long Beach Wilson HS / Long Beach (CA)", home("Long Beach", "CA", "USA")),
    ("HS City (State): Mayfair", home("", "", "")),
    ("MSJC / R/R", home("MSJC", "", "")),
    ("&quot;Fort Worth,", home("Fort Worth", "", "")),
])
def test_parse_hometown(raw, want):
    assert parse_hometown(raw) == want


@pytest.mark.parametrize("raw", ["R/R", "S/R", "R", "Manager", "5-7", "5'7\""])
def test_not_a_place(raw):
    assert not_a_place(raw)
    assert parse_hometown(raw) == home("", "", "")


@pytest.mark.parametrize("raw", ["Rome", "Roseland", "Left Hand, W.Va."])
def test_real_towns_are_places(raw):
    assert not not_a_place(raw)


def test_bats_throws_never_kept_as_hometown_or_position():
    p = {f: "" for f in sidearm.FIELDS}
    p.update(name="Jane Doe", hometown="R/R")
    assert sidearm.tidy_players([p])[0]["hometown"] == ""
    row = {"name": "Jane Doe", "hometown": "L/L", "position": "OF R/R", "high_school": "", "previous_school": "",
           "class_year": ""}
    assert (sr.clean_row(row)["hometown"], sr.clean_row(row)["position"]) == ("", "OF")
    assert sidearm.strip_bats_throws("LHP/OF") == "LHP/OF"


# ---------------------------------------------------------------------------
# geocode.py: suggestions, fallbacks, retry

def test_suggest_correction():
    assert geo.suggest_correction("Brandon, Manitoba, CA")[:4] == ("Brandon", "MB", "Canada", "fixed")
    assert geo.suggest_correction("Darien, III.")[:4] == ("Darien", "IL", "USA", "fixed")
    assert geo.suggest_correction("R/R")[3] == "unfixable"


def _zip(path: Path, name: str, text: str):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, text)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A tiny offline copy of the geocoder's downloads."""
    c = tmp_path / ".cache"
    c.mkdir()
    head = "USPS\tGEOID\tANSICODE\tNAME\tALAND\tINTPTLAT\tINTPTLONG\n"
    _zip(c / geo.GAZ_PLACES, "places.txt", head + "CO\t1\t1\tThornton city\t100\t39.9\t-104.9\n"
         "TX\t2\t2\tDallas city\t100\t32.8\t-96.8\n")
    _zip(c / geo.GAZ_COUSUBS, "cousubs.txt", head + "NY\t3\t3\tCortlandt town\t100\t41.2\t-73.9\n")
    _zip(c / geo.GAZ_COUNTIES, "counties.txt", head + "TX\t4\t4\tDallas County\t100\t32.7\t-96.7\n")
    _zip(c / "PopulatedPlaces_National_Text.zip", "gnis.txt",
         "FEATURE_ID|FEATURE_NAME|STATE_NAME|PRIM_LAT_DEC|PRIM_LONG_DEC\n1|Arleta|California|34.24|-118.43\n")
    (c / "us_cities.csv").write_text("ID,STATE_CODE,STATE_NAME,CITY,COUNTY,LATITUDE,LONGITUDE\n"
                                     "1,GA,Georgia,Ellenwood,Clayton,33.62,-84.27\n"
                                     "2,CA,California,Murrieta,Riverside,33.55,-117.21\n", encoding="utf-8")
    monkeypatch.setattr(geo, "CACHE", c)
    monkeypatch.setattr(geo, "_download", lambda url, local, label: local if local.exists() else
                        (_ for _ in ()).throw(OSError("offline")))
    return c


def test_us_town_lists(cache):
    gaz = geo.Gazetteer()
    assert gaz.lookup_us("Ellenwood", "GA")[2:] == ("us_towns", "city")
    assert gaz.lookup_us("Thornton", "CO")[2] == "census"           # the Census list still comes first
    assert gaz.lookup_us("Arleta", "CA")[2] == "usgs"
    assert gaz.lookup_us("Long Island", "NY")[2:] == ("area", "region")
    assert gaz.lookup_us("Nowhere", "GA") is None


def test_province_and_territory_fallbacks(cache, monkeypatch):
    monkeypatch.setattr(geo, "_WORLD", geo.WorldCities.__new__(geo.WorldCities))   # as without geonamescache
    geo._WORLD.ok = False
    gaz = geo.Gazetteer()
    assert geo.resolve(home("Teulon", "MB", "Canada"), gaz, None)[2:] == ("province", "region")
    assert geo.resolve(home("Trullio Alto", "PR", "USA"), gaz, None)[2:] == ("territory", "region")
    assert geo.resolve(home("Willemstad", "", "Curacao"), gaz, None)[2:] == ("country_centroid", "country")


def _season_file(path: Path, hometowns: list[str]):
    fields = ["season", "division", "current_conference", "school", "name", "hometown", "home_city", "home_state",
              "home_country", "high_school", "previous_school", "class_norm", "position"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for i, h in enumerate(hometowns):
            w.writerow({"season": 2026, "division": "D1", "school": "Test U", "name": f"Player {chr(65 + i)}", "hometown": h})


@pytest.fixture
def sport(tmp_path, monkeypatch, cache):
    config, rosters = tmp_path / "config", tmp_path / "rosters"
    config.mkdir()
    (rosters / "softball").mkdir(parents=True)
    (config / "softball").mkdir()
    (config / "softball" / "settings.json").write_text(json.dumps({"label": "Softball", "d1_divisions": ["D1"]}))
    monkeypatch.setattr(core, "CONFIG", config)
    monkeypatch.setattr(core, "ROSTERS", rosters)
    return core.load_sport("softball")


def test_geocoder_retries_when_the_parser_reads_a_hometown_differently(sport):
    _season_file(sport.rosters_dir / "rosters_2026.csv", ["Winnipeg, MB", "Dallas, Texas", "R/R"])
    # hometowns.csv from a run before Oct 27: "Winnipeg, MB" read with "MB" as a country, not placed
    with open(sport.rosters_dir / "hometowns.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=geo.LOOKUP_FIELDS)
        w.writeheader()
        w.writerow({"hometown": "Winnipeg, MB", "school": "", "city": "Winnipeg", "state": "", "country": "MB",
                    "players": 1})
    geo.main(["--sport", "softball"])
    rows = {r["hometown"]: r for r in csv.DictReader(open(sport.rosters_dir / "hometowns.csv", encoding="utf-8"))}
    assert rows["Winnipeg, MB"]["country"] == "Canada" and rows["Winnipeg, MB"]["lat"]
    assert rows["Dallas, Texas"]["source"] == "census"
    unmatched = list(csv.DictReader(open(sport.rosters_dir / "unmatched_hometowns.csv", encoding="utf-8")))
    assert [r["hometown_raw"] for r in unmatched] == []       # "R/R" counts as no hometown, not an unplaced one


def test_geocoder_looks_up_every_hometown_again_but_keeps_manual_ones(sport):
    # Oct 28: a hometown unplaced (or on a coarse dot) last time is looked up again, since the town lists and
    # the parser may know it now: Ellenwood GA was never retried after the US town list was added.
    _season_file(sport.rosters_dir / "rosters_2026.csv", ["Ellenwood, Ga.", "Dallas, Texas"])
    with open(sport.rosters_dir / "hometowns.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=geo.LOOKUP_FIELDS)
        w.writeheader()
        w.writerow({"hometown": "Ellenwood, Ga.", "school": "", "city": "Ellenwood", "state": "GA", "country": "USA",
                    "players": 1})
        w.writerow({"hometown": "Dallas, Texas", "school": "", "city": "Dallas", "state": "TX", "country": "USA",
                    "lat": "1", "lon": "2", "source": "manual", "precision": "city", "players": 1})
    geo.main(["--sport", "softball"])
    rows = {r["hometown"]: r for r in csv.DictReader(open(sport.rosters_dir / "hometowns.csv", encoding="utf-8"))}
    assert rows["Ellenwood, Ga."]["lat"] and rows["Ellenwood, Ga."]["source"] == "us_towns"
    assert (rows["Dallas, Texas"]["lat"], rows["Dallas, Texas"]["source"]) == ("1", "manual")


def test_abbreviations_in_town_names():
    assert geo.norm_city("E. Setauket") == geo.norm_city("East Setauket")
    assert geo.norm_city("Stone Mtn") == geo.norm_city("Stone Mountain")
    assert geo.norm_city("Essex Jct.") == geo.norm_city("Essex Junction")
    assert geo.norm_city("Pt. Pleasant") == geo.norm_city("Point Pleasant")


def test_world_towns(cache):
    pytest.importorskip("geonamescache")
    w = geo.WorldCities()
    lat, lon, src, prec = w.lookup("Toronto", "Canada", "ON")
    assert (src, prec) == ("geonames", "city") and 43 < lat < 44 and -80 < lon < -79      # not Toronto, Australia
    assert w.lookup("Victoria", "Canada", "BC")[1] < -120          # Victoria BC, not a Victoria elsewhere in Canada
    assert w.lookup("Amsterdam", "Netherlands")[0] > 52            # GeoNames says "The Netherlands"
    assert w.lookup_big("Tokyo")[0] > 35 and w.lookup_big("Southington") is None
    gaz = geo.Gazetteer()
    lat, lon, src, _ = geo.resolve(parse_hometown("Kahnawake Mohawk Territory"), gaz, None)
    assert src == "geonames" and 45 < lat < 46
    # plain "NL": a Newfoundland town of that name, else a Dutch one
    assert geo.resolve(home("St. John's", "", "NL"), gaz, None)[1] < -50
    assert geo.resolve(home("Spijkenisse", "", "NL"), gaz, None)[1] > 0


# ---------------------------------------------------------------------------
# hometown_fixes.py suggest

@pytest.fixture
def towns():
    t, s = {}, {}
    import collections
    t, s = collections.defaultdict(dict), collections.defaultdict(set)
    for st, city in [("CA", "Murrieta"), ("IL", "Darien"), ("CO", "Thornton"), ("NJ", "Rockaway"), ("NY", "Rockaway"),
                     ("MA", "Southwick")]:
        t[st][sug.norm(city)] = city
        s[sug.norm(city)].add(st)
    sug.load_places()
    return t, s


def row(raw, city="", state="", country="", status="review"):
    return {"hometown_raw": raw, "city": city, "state": state, "country": country, "status": status}


def test_fixer(towns):
    what, new = sug.suggest(row("Brandon, Manitoba, CA", "Brandon, Manitoba", "CA", "USA", "fixed"), *towns)
    assert what == "fixed: place abroad" and (new["city"], new["state"], new["country"]) == ("Brandon", "MB", "Canada")
    assert sug.suggest(row("Teulon, MB", "Teulon", "MB", "Canada", "fixed"), *towns) is None   # already right
    what, new = sug.suggest(row("Darien, III.", "Darien", "", "III."), *towns)
    assert (new["city"], new["state"], new["status"]) == ("Darien", "IL", "fixed")
    assert sug.suggest(row("R/R", "R", "", "", "fixed"), *towns)[1]["status"] == "unfixable"


def test_fixer_wrong_state(towns):
    what, new = sug.suggest(row("Murrieta, GA", "Murrieta", "GA", "USA", "fixed"), *towns)
    assert new["status"] == "review" and "CA" in new["note"]
    assert sug.suggest(row("Rockaway, Pa.", "Rockaway", "PA", "USA", "fixed"), *towns) is None   # two states
    assert sug.suggest(row("Darie, GA", "Darie", "GA", "USA", "fixed"), *towns) is None           # too short
    # --accept-likely fixes it only when the state is a neighbour or a near-miss abbreviation
    assert sug.suggest(row("Murrieta, Ariz.", "Murrieta", "AZ", "USA"), *towns, accept=True)[1]["state"] == "CA"
    assert sug.suggest(row("Murrieta, GA", "Murrieta", "GA", "USA"), *towns, accept=True)[1]["status"] == "review"


# ---------------------------------------------------------------------------
# scrape_rosters.py


# ---------------------------------------------------------------------------
# bats/throws in the position box of classic Sidearm pages (Asbury 2024, Bluefield 2019, Jackson State 2024)

def _classic_page(position_html: str) -> str:
    return ('<ul><li class="sidearm-roster-player"><div class="sidearm-roster-player-position">' + position_html +
            '</div><div class="sidearm-roster-player-name"><h3><a href="/x">Jane Doe</a></h3></div>'
            '<span class="sidearm-roster-player-hometown">Austin, Texas</span></li></ul>')


@pytest.mark.parametrize("position_html, want", [
    ('<span class="sidearm-roster-player-custom1">R/R</span>', ""),                                    # Asbury
    ('<span class="text-bold"> OF </span> <span class="sidearm-roster-player-height">5\'8"</span> '
     '<span class="sidearm-roster-player-custom1">L/R</span>', "OF"),                                   # Jackson State
    ('<span class="text-bold"><span class="sidearm-roster-player-position-long-short hide-on-small-down"> R/R </span>'
     '<span class="sidearm-roster-player-position-long-short hide-on-medium"> P/OF </span></span>', "P/OF"),
])
def test_classic_position_without_bats_throws(position_html, want):
    html = _classic_page(position_html)
    players = sidearm.parse_sidearm_classic(html, BeautifulSoup(html, "lxml"))
    assert sidearm.tidy_players(players)[0]["position"] == want


def test_state_only_gets_the_states_middle(cache):
    gaz = geo.Gazetteer()
    lat, lon, src, prec = geo.resolve(parse_hometown("TX"), gaz, None)
    assert (src, prec) == ("state", "region") and (lat, lon) == (32.8, -96.8)   # the tiny list's one TX town
    assert geo.resolve({"city": "Texas", "state": "", "country": ""}, gaz, None)[2] == "state"


# ==================================================================================================
# Roster pages: parsing Sidearm, WMT, Presto and Nuxt pages (football settings)
# ==================================================================================================

HERE = Path(__file__).parent


@pytest.fixture
def football():
    """Football's settings and junior colleges (so "Iowa Western" counts as a college) for every test in this section,
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

@pytest.mark.usefixtures("football")
def test_sidearm_nextgen_table():
    strategy, players = parse_roster((HERE / "sidearm_nextgen_table.html").read_text())
    assert strategy == "html_table"
    assert len(players) == 4  # coaching staff table ignored
    p = players[2]
    assert p["name"] == "Devan Thompkins"
    assert p["hometown"] == "Tracy, Calif." and p["high_school"] == "Edison"
    assert p["previous_school"] == "USC" and p["position"] == "DL" and p["height"] == "6-5"
    assert p["bio_url"].endswith("/devan-thompkins/17536")


@pytest.mark.usefixtures("football")
def test_sidearm_classic():
    strategy, players = parse_roster((HERE / "sidearm_classic.html").read_text())
    assert strategy == "sidearm_classic"
    a, b = players
    assert (a["name"], a["jersey"], a["position"], a["class_year"]) == ("John Smith", "7", "QB", "R-Jr.")
    assert (a["hometown"], a["high_school"], a["previous_school"]) == ("Fargo, N.D.", "Fargo South", "Iowa State")
    assert a["height"] == "6-2" and a["weight"] == "210"
    assert b["hometown"] == "Stockholm, Sweden"


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
def test_embedded_json_fallback():
    data = {"props": {"pageProps": {"roster": [
        {"name": "Joe Tester", "hometown": "Austin, Texas", "position": "WR", "class": "So."}]}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    strategy, out = parse_roster(html)
    assert strategy == "embedded_json" and out[0]["hometown"] == "Austin, Texas"


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
def test_classic_long_position_kept_whole():
    html = """<ul><li class="sidearm-roster-player">
      <div class="sidearm-roster-player-name"><h3><a href="/x">Pat Long</a></h3></div>
      <div class="sidearm-roster-player-position"><span>Defensive Back 6'0" 190 lbs</span></div>
      <span class="sidearm-roster-player-hometown">Tulsa, Okla.</span></li></ul>"""
    _, out = parse_roster(html)
    assert out[0]["position"] == "Defensive Back"


@pytest.mark.usefixtures("football")
def test_bad_height_does_not_drop_roster():
    players = [{"firstName": f"P{i}", "lastName": "X", "hometown": "Ames, Iowa",
                "heightFeet": "6'2\"" if i == 0 else 6, "heightInches": 1} for i in range(30)]
    strategy, out = parse_roster(nuxt_page({"pinia": {"roster": {"players": players}}}))
    assert strategy == "nuxt_data" and len(out) == 30


@pytest.mark.usefixtures("football")
def test_deep_devalue_payload_no_recursion():
    from scrape_rosters import decode_devalue
    raw = [[1]] + [[i + 1] for i in range(1, 100_000)] + ["end"]
    decode_devalue(raw)  # used to need a huge recursion limit


# ---------------------------------------------------------------------------- class years

@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
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


# ---------------------------------------------------------------------------- coaches, staff and names

@pytest.mark.usefixtures("football")
def test_nuxt_coaches_with_hometowns_dropped():
    players = [{"firstName": f"P{i}", "lastName": "X", "hometown": "Ames, Iowa", "positionShort": "WR",
                "jerseyNumber": str(i)} for i in range(30)]
    coaches = [{"firstName": "Tim", "lastName": "Coach", "hometown": "Fargo, N.D.", "title": "Head Coach"}]
    strategy, out = parse_roster(nuxt_page({"pinia": {"roster": {"players": players, "coaches": coaches}}}))
    assert strategy == "nuxt_data" and len(out) == 30
    assert all(p["name"] != "Tim Coach" for p in out)


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
def test_staff_table_with_hometown_column_ignored():
    html = """<table><thead><tr><th>Name</th><th>Title</th><th>Hometown</th></tr></thead>
      <tbody><tr><td>Sam Boss</td><td>Head Coach</td><td>Tulsa, Okla.</td></tr></tbody></table>"""
    _, out = parse_roster(html)
    assert out == []


@pytest.mark.usefixtures("football")
def test_clean_name_strips_numbers_and_captain_marks():
    from scrape_rosters import clean_name
    for raw in ("89 Mason Thomas", "#89 Mason Thomas", "Mason Thomas 89", "C Mason Thomas", "C 89 Mason Thomas",
                "Mason Thomas (C)", "Mason Thomas ©", "Mason Thomas*", "Mason Thomas Mason Thomas"):
        assert clean_name(raw) == "Mason Thomas", raw
    for keep in ("C.J. Stroud", "CJ Stroud", "C J Stroud", "Charles Woodson", "Tre' Harbison"):
        assert clean_name(keep) == keep, keep


# ---------------------------------------------------------------------------- previous school vs. high school

@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
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


@pytest.mark.usefixtures("football")
def test_sidearm_classic_combined_school_field():
    html = """<ul><li class="sidearm-roster-player"><div class="sidearm-roster-player-name"><h3><a href="/bio/1">Pat Mover</a></h3></div>
      <span class="sidearm-roster-player-position">LB</span><span class="sidearm-roster-player-hometown">Lubbock, Texas</span>
      <span class="sidearm-roster-player-highschool">Coronado HS / Texas Tech</span></li></ul>"""
    p = roster(html)["Pat Mover"]
    assert p["high_school"] == "Coronado HS" and p["previous_school"] == "Texas Tech"


# ==================================================================================================
# Labels in hometown fields, and the levels of previous schools
# ==================================================================================================

# ---------------------------------------------------------------------------- roster labels in hometowns
# Labels saved with the hometown ("Hometown/Prev. School: ...") are taken off before the town is read,
# so they never reach the geocoder as a place called "Hometown".

@pytest.mark.parametrize("raw, town, school", [
    ("Hometown/Prev. School: Wilson, NC / Beddingfield", "Wilson, NC", "Beddingfield"),
    ("Hometown/Previous School(s): Omaha, Neb.", "Omaha, Neb.", ""),
    ("Hometown/Prev. School: / East Bladen", "", "East Bladen"),
    ("HS City (State): Mayfair HS / Lakewood (CA)", "Lakewood, CA", "Mayfair HS"),
    ("HS City (State): Lakewood/University of Nevada", "", "Lakewood / University of Nevada"),
    ("ICC Grad Date:", "", ""),
    ("Atlanta, Ga. / Westlake HS", "Atlanta, Ga. / Westlake HS", ""),      # no label: unchanged
    ("Twitter:", "Twitter:", ""),
])
def test_split_labeled_hometown(raw, town, school):
    assert split_labeled_hometown(raw) == (town, school)


# ---------------------------------------------------------------------------- transfer levels

@pytest.fixture(scope="module")
def lv():
    return Levels.load(load_sport("football"))


@pytest.mark.parametrize("text, year, level", [
    ("Valdosta St.", 2018, "D2"),
    ("UW-Whitewater", 2020, "D3"),
    ("Hutchinson (Kan.) CC", 2022, "JUCO"),
    ("Some Town Junior College", 2019, "JUCO"),            # generic two-year wording
    ("Lindsey Wilson College", 2019, "NAIA"),
    ("Notre Dame", 2019, "D1"),
    ("Notre Dame College", 2019, "D2"),                    # Ohio, Division II until it closed
    ("Miami (Fla.)", 2019, "D1"),
    ("N.C. State", 2019, "D1"),
])
def test_levels(lv, text, year, level):
    assert lv.level(text, year)[0] == level


def test_schools_that_changed_level(lv):
    assert lv.level("Tarleton State", 2018)[0] == "D2"      # FCS from 2020
    assert lv.level("Tarleton State", 2021)[0] == "D1"
    assert lv.level("Texas A&M-Commerce", 2019) == ("D2", "East Texas A&M")
    assert lv.level("Savannah State", 2017)[0] == "D1"      # left D1 after 2018
    assert lv.level("Savannah State", 2022)[0] == "D2"
    assert [lv.level("Thomas More", y)[0] for y in (2017, 2020, 2024)] == ["D3", "NAIA", "D2"]
    assert lv.level("St. Cloud State", 2022)[0] == "D2"     # program dropped in 2019: keeps its last level


def test_names_at_two_levels_stay_unknown(lv):
    for text in ("Bethel", "Concordia", "Butler", "Saint Francis", "Augustana"):
        assert lv.level(text, 2019)[0] == "unknown", text
    assert lv.level("Butler CC", 2019)[0] == "JUCO"


def test_not_colleges(lv):
    for text in ("Business", "Sport Management", "St. John's College", "St. John's College (H.S.)",
                 "Gonzaga College", "Boston College High", ""):
        assert lv.level(text, 2019)[0] == "unknown", text


def test_several_schools_in_one_field(lv):
    assert lv.level("Wawasee | Ball State | Bethel (Tenn.)", 2019)[0] == "NAIA"
    assert lv.level("Lyons (College of the Sequoias)", 2019)[0] == "JUCO"


def test_key_and_majors():
    assert key("Lincoln University (Mo.)") == "lincoln (mo)"
    assert key("Mt. San Antonio") == "mount san antonio"
    assert key("St. Olaf") == "saint olaf"
    assert is_major("Mechanical Engineering") and not is_major("North Dakota State College of Science")


# ==================================================================================================
# Running a scrape: sizes, addresses, seasons, reasons, downloads, the lock, pipeline.py, checks
# ==================================================================================================

def use(name):
    sidearm.configure(core.load_sport(name))


# ---------------------------------------------------------------------------- a tiny sport in tmp_path

SETTINGS = {
    "label": "Softball", "roster_paths": ["/sports/softball/roster"], "min_players": 10, "max_players": 55,
    "position_groups": ["P", "C", "IF", "OF", "UT", "UNK"], "position_abbreviations": {"P": "p rhp"},
    "position_fallback": "UNK", "spring_season": True, "d1_divisions": ["D1"],
    "other_divisions": ["D2", "D3", "NAIA", "JUCO"], "thin_roster": 16, "frozen_min_pairs": 12,
}
FIELDS = sr.OUT_FIELDS


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    """A project folder with config/softball/settings.json and an empty rosters/softball/."""
    monkeypatch.setattr(core, "ROOT", tmp_path)
    monkeypatch.setattr(core, "CONFIG", tmp_path / "config")
    monkeypatch.setattr(core, "ROSTERS", tmp_path / "rosters")
    (tmp_path / "config" / "softball").mkdir(parents=True)
    (tmp_path / "rosters" / "softball").mkdir(parents=True)
    (tmp_path / "config" / "softball" / "settings.json").write_text(json.dumps(SETTINGS))
    with open(tmp_path / "config" / "softball" / "schools.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["school", "division", "conference", "domain", "roster_url", "first_season", "last_season",
                    "aliases", "note"])
        w.writerow(["Alpha", "D1", "X", "alpha.com", "", "", "", "", ""])
        w.writerow(["Blocked", "D3", "Y", "blocked.edu", "", "", "", "", "left out: bot check every season"])
    sport = core.load_sport("softball")
    sidearm.configure(sport)
    yield sport
    core.SPRING_SEASON = False


def write_season(sport, season, rows):
    with open(sport.rosters_dir / f"rosters_{season}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({"season": season, "division": "D1", "current_conference": "X", **r})


def player(school, name, cls="FR", town="Austin, TX"):
    return {"school": school, "name": name, "class_norm": cls, "class_year": cls, "hometown": town,
            "home_city": town.split(",")[0], "home_state": "TX", "home_country": "USA", "position": "P",
            "high_school": "", "previous_school": "", "roster_url": f"https://{school.lower()}.com/roster"}


# ---------------------------------------------------------------------------- roster size per sport

def test_each_sport_has_its_own_normal_size():
    use("softball")
    assert sidearm.normal_size(22) and not sidearm.normal_size(8) and not sidearm.normal_size(60)
    use("football")
    assert sidearm.normal_size(110) and not sidearm.normal_size(22)
    use("baseball")      # saved rosters are judged by the same sizes
    season = lambda n: [{"school": "A", "division": "D1", "hometown": "X"} for _ in range(n)]
    assert [sr.saved_reports(season(n))["A"]["status"] for n in (38, 8, 130)] == ["ok", "partial", "partial"]


def test_a_slow_school_stops_after_its_time_limit():
    use("baseball")
    old = sr.SCHOOL_MINUTES
    sr.SCHOOL_MINUTES = 0          # already past the limit: nothing is downloaded
    try:
        out = sr.scrape_school_all({"school": "A", "division": "D1", "domain": "a.edu"}, [2024, 2025], None, {},
                                   render=False, skip=set())
    finally:
        sr.SCHOOL_MINUTES = old
    assert [r["status"] for _, _, r in out] == ["failed", "failed"]
    assert all(r["error"].startswith("timed out") for _, _, r in out)


# ---------------------------------------------------------------------------- seasons

def test_current_season_fall_and_spring():
    core.SPRING_SEASON = False
    assert core.current_season(date(2026, 10, 27)) == 2026      # football in the autumn: this fall
    assert core.current_season(date(2027, 2, 1)) == 2026
    core.SPRING_SEASON = True
    try:
        assert core.current_season(date(2026, 10, 27)) == 2027  # softball in the autumn: next spring
        assert core.current_season(date(2026, 4, 1)) == 2026
        assert core.current_season(date(2026, 7, 31)) == 2026
        assert core.current_season(date(2026, 8, 1)) == 2027
    finally:
        core.SPRING_SEASON = False


def test_default_seasons():
    oct26, jul26, feb27 = date(2026, 10, 28), date(2026, 7, 1), date(2027, 2, 1)
    assert core.Sport(name="football").default_seasons(oct26) == "2016-2019,2021-2026"
    assert core.Sport(name="football").default_seasons(feb27) == "2016-2019,2021-2026"
    # spring sports: from August the current season is the next spring's (the 2026-27 team is 2027)
    assert core.Sport(name="softball", spring_season=True).default_seasons(oct26) == "2016-2027"
    assert core.Sport(name="lacrosse-womens", spring_season=True).default_seasons(jul26) == "2016-2026"
    assert core.Sport(name="softball", seasons="2018-2026").default_seasons() == "2018-2026"


def test_main_page_still_showing_last_season_is_not_this_seasons_roster(monkeypatch):
    # October: the main roster page (no year on it) can still show last spring's team
    use("lacrosse-womens")
    last = {f"player {i}" for i in range(30)}
    def fake(school, fetcher, season, division, render, prefer, save_dir=None, bios=False):
        names = sorted(last) if season == 2027 else []
        rows = [{"name": n.title()} for n in names]
        return rows, {"season": season, "school": "A", "status": "ok", "season_check": "current", "players": len(rows),
                      "with_hometown": len(rows), "error": ""}, None
    monkeypatch.setattr(sr, "scrape_school_season", fake)
    monkeypatch.setattr(core, "current_season", lambda today=None: 2027)
    out = sr.scrape_school_all({"school": "A", "division": "D1", "domain": "a.edu"}, [2027], None, {}, render=False,
                               skip=set(), reference=(2026, last))
    (season, rows, report), = out
    assert season == 2027 and rows == [] and report["status"] == "failed"


# ---------------------------------------------------------------------------- addresses and reasons

def test_presto_links_follow_the_sport():
    for name, page, want in [
        ("football", 'href="/sports/fball/2026-27/roster"', "2024-25"),
        ("baseball", 'href="/sports/m-basebl/2025-26/roster"', "2023-24"),
        ("softball", 'href="/sports/sball/2025-26/roster"', "2023-24"),
    ]:
        use(name)
        assert sr.roster_link_re().search(page), name
        assert sr.presto_season(2024) == want, name
    use("baseball")
    assert not sr.roster_link_re().search('href="/sports/fball/2025-26/roster"')
    use("football")
    assert not sr.roster_link_re().search('href="/sports/flagfball/2025-26/roster"')


def test_spring_archives_also_try_the_fall_year():
    use("baseball")
    urls = sidearm.candidate_urls("clemsontigers.com", season=2024)
    assert "https://clemsontigers.com/sports/baseball/roster/2024" in urls
    assert "https://clemsontigers.com/sports/baseball/roster/2023" in urls
    assert urls.index("https://clemsontigers.com/sports/baseball/roster/2024") < urls.index("https://clemsontigers.com/sports/baseball/roster/2023")
    assert sidearm.detect_season("<title>2023-24 Baseball Roster</title>") == 2024
    use("football")
    assert "https://x.com/sports/football/roster/2023" not in sidearm.candidate_urls("x.com", season=2024)


def test_two_year_label_beats_a_bare_year():
    # Samford: the title says "2026 ... Roster" (the year the season starts), the heading "2026-27"
    use("basketball-mens")
    page = "<title>2026 Men's Basketball Roster - Samford</title><h1>2026-27 Men's Basketball Roster</h1>"
    assert sidearm.detect_season(page) == 2027
    assert sidearm.detect_season("<title>2025-26 Men's Basketball Roster</title>") == 2026
    # a news headline (h2) doesn't count as the page's label
    assert sidearm.detect_season("<title>2026 Softball Roster</title><h2>2026-27 schedule out</h2>") == 2026
    use("football")
    assert sidearm.detect_season("<title>2026 Football Roster</title><h1>2026-27 Football</h1>") == 2026


def test_current_page_that_is_still_last_seasons_team(monkeypatch):
    monkeypatch.setattr(sr, "current_season", lambda: 2027)
    up = {"FR": "SO", "SO": "JR", "JR": "SR", "SR": "GR"}
    old = [{"name": f"P{i}", "class_norm": c} for i, c in enumerate(["FR", "SO", "JR", "SR"] * 5)]
    saved = {r["name"].lower(): r["class_norm"] for r in old}
    rep = lambda: {"status": "ok", "players": 20, "with_hometown": 20, "error": ""}
    # a copy: same players, same class years (read in this run, or saved earlier)
    out = sr.check_current_is_new([(2027, [dict(r) for r in old], rep()), (2026, old, rep())], {})
    assert out[0][1] == [] and "still shows the 2026 roster" in out[0][2]["error"]
    assert out[1][1] == old
    assert sr.check_current_is_new([(2027, [dict(r) for r in old], rep())], saved)[0][1] == []
    # exactly the same players with some class years changed is still a copy (Kansas softball)
    half = [dict(r, class_norm=up[r["class_norm"]] if i % 2 else r["class_norm"]) for i, r in enumerate(old)]
    assert sr.check_current_is_new([(2027, half, rep())], saved)[0][1] == []
    # a real new roster: returning players moved up a class, seniors gone, freshmen in
    new = [dict(r, class_norm=up[r["class_norm"]]) for r in old if r["class_norm"] != "SR"]
    new += [{"name": f"N{i}", "class_norm": "FR"} for i in range(4)]
    assert sr.check_current_is_new([(2027, new, rep())], saved)[0][1] == new
    # other seasons aren't touched
    assert sr.check_current_is_new([(2025, [dict(r) for r in old], rep())], saved)[0][1] != []


def test_missing_rosters_lists_left_out_once(tiny):
    reports = [
        {"season": 2025, "school": "Alpha", "division": "D1", "status": "failed", "error": "https://alpha.com/r: HTTP 404"},
        {"season": 2025, "school": "Blocked", "division": "D3", "status": "failed", "error": "left out: bot check every season"},
        {"season": 2026, "school": "Blocked", "division": "D3", "status": "left_out", "error": "left out: bot check every season"},
    ]
    for season in (2025, 2026):
        with open(tiny.rosters_dir / f"scrape_report_{season}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sr.REPORT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(r for r in reports if r["season"] == season)
    path = sr.write_missing_rosters(tiny.rosters_dir, tiny.schools_csv, "Softball", [],
                                    division_order=["D1", "D2", "D3", "NAIA", "JUCO"])
    text = path.read_text()
    assert "| division | ok | partial | failed | left out |" in text
    assert "| D3 | 0 | 0 | 0 | 2 |" in text
    assert "## Left out on purpose (1 school)" in text
    assert text.count("**Blocked**") == 1
    assert "### Failed" in text and "**Alpha**" in text


# ---------------------------------------------------------------------------- downloads

def test_dead_host_is_tried_once(tmp_path, monkeypatch):
    f = core.Fetcher(tmp_path, delay=0)
    calls = []

    def boom(url):
        calls.append(url)
        raise requests.exceptions.ConnectionError("HTTPSConnectionPool(host='gone.edu'): NewConnectionError: "
                                                  "Failed to resolve 'gone.edu'")
    monkeypatch.setattr(f, "_download", boom)
    for path in ("/a", "/b", "/c"):
        with pytest.raises(requests.exceptions.ConnectionError):
            f.get(f"https://gone.edu{path}")
    assert calls == ["https://gone.edu/a"]


def test_broken_connection_is_not_a_dead_host(tmp_path, monkeypatch):
    f = core.Fetcher(tmp_path, delay=0)
    calls = []

    def reset(url):
        calls.append(url)
        raise requests.exceptions.ConnectionError("('Connection aborted.', ConnectionResetError(54))")
    monkeypatch.setattr(f, "_download", reset)
    for path in ("/a", "/b"):
        with pytest.raises(requests.exceptions.ConnectionError):
            f.get(f"https://flaky.edu{path}")
    assert len(calls) == 2


# ---------------------------------------------------------------------------- lock

def test_second_run_of_a_sport_is_refused(tiny):
    with core.sport_lock(tiny, "first run"):
        with pytest.raises(core.SportBusy, match="first run"):
            with core.sport_lock(tiny, "second run"):
                pass
    with core.sport_lock(tiny, "after"):      # free again once the first is done
        pass


def test_pipeline_steps_share_its_lock(tiny, monkeypatch):
    monkeypatch.setenv(core.LOCK_ENV, "softball")
    with core.sport_lock(tiny, "pipeline"):
        with core.sport_lock(tiny, "its scrape step"):
            pass


# ---------------------------------------------------------------------------- pipeline plan

def plan(tiny, *argv):
    import pipeline
    ns = pipeline.argparse.Namespace(
        steps=None, from_step=None, skip=None, only=None, division=None, seasons=None, rescrape=False,
        no_refresh=False, workers=16, retry_workers=8, first_minutes=2, school_minutes=5, use_review=False, test=False,
        give_up_after=None, retry_given_up=False,
        redo_current=False, keep_going=False, dry_run=True)
    for a in argv:
        k, _, v = a.partition("=")
        setattr(ns, k, v if v else True)
    return pipeline.plan_for(tiny, ns)


def test_pipeline_step_choice(tiny):
    assert plan(tiny).steps == ["scrape", "retry", "geocode", "fix-hometowns", "frozen", "build", "locations", "staff",
                                "check"]
    assert plan(tiny, "from_step=geocode").steps[0] == "geocode"
    assert "scrape" not in plan(tiny, "skip=scrape,retry").steps
    assert plan(tiny, "steps=check,build").steps == ["build", "check"]
    assert "redo-current" in plan(tiny, "redo_current").steps
    with pytest.raises(SystemExit):
        plan(tiny, "steps=bild")


def test_pipeline_first_pass_only_fills_gaps_once_rosters_exist(tiny):
    first = plan(tiny).commands["scrape"][0]
    assert "--retry-failed" not in first and tiny.default_seasons() in first and "--report" in first
    write_season(tiny, 2025, [player("Alpha", "Ann Lee")])
    assert "--retry-failed" in plan(tiny).commands["scrape"][0]
    assert "--retry-failed" not in plan(tiny, "rescrape").commands["scrape"][0]
    only = plan(tiny, "only=Alpha").commands["scrape"][0]
    assert "--retry-failed" not in only and "Alpha" in only
    retry = plan(tiny).commands["retry"][0]
    assert {"--retry-failed", "--render", "--bios", "--refresh", "--report"} <= set(retry)


def test_redo_current_picks_main_page_seasons(tiny):
    with open(tiny.rosters_dir / "scrape_report_2026.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sr.REPORT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"season": 2026, "school": "Alpha", "status": "ok", "season_check": "current"})
        w.writerow({"season": 2026, "school": "Beta", "status": "ok", "season_check": "verified"})
    cmds = plan(tiny, "redo_current").commands["redo-current"]
    assert len(cmds) == 1 and "Alpha" in cmds[0] and "Beta" not in " ".join(cmds[0]) and "2026" in cmds[0]


# ---------------------------------------------------------------------------- checks after a run

def test_check_rosters_finds_oversized_and_copied_seasons(tiny, capsys):
    names = [f"Ann {a}{b}son" for a in "abcdefgh" for b in "abcdefgh"][:60]
    write_season(tiny, 2023, [player("Alpha", n, "FR") for n in names[:15]])
    write_season(tiny, 2024, [player("Alpha", n, "SO") for n in names[:15]] + [player("Alpha", n) for n in names[15:50]])
    write_season(tiny, 2025, [player("Alpha", n, "JR") for n in names[:15]])
    write_season(tiny, 2026, [player("Alpha", n, "JR") for n in names[:15]])   # 2025's page again
    assert build.check_rosters_main(["--sport", "softball"]) == 0
    rows = list(csv.DictReader(open(tiny.rosters_dir / "roster_checks.csv")))
    assert {(r["check"], r["season"]) for r in rows} == {("oversized", "2024"), ("repeated", "2026")}


def test_frozen_check_with_too_few_players_doesnt_crash(tiny, capsys):
    write_season(tiny, 2025, [player("Alpha", "Ann Lee", "FR")])
    write_season(tiny, 2026, [player("Alpha", "Ann Lee", "SO")])
    build.check_frozen_classes_main(["--sport", "softball"])
    assert (tiny.rosters_dir / "frozen_class_seasons.csv").exists()


def test_spelling_fixes_read_the_geocoders_table(tiny):
    with open(tiny.rosters_dir / "hometowns.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["hometown", "school", "city", "state", "country", "lat", "lon",
                                          "source", "precision", "players"])
        w.writeheader()
        w.writerow({"hometown": "Baton Rogue, La.", "city": "Baton Rogue", "state": "LA", "country": "USA",
                    "lat": "30.5", "lon": "-91.1", "source": "usgs", "precision": "city", "players": 3})
        w.writerow({"hometown": "Baton Rouge, La.", "city": "Baton Rouge", "state": "LA", "country": "USA",
                    "lat": "30.45", "lon": "-91.15", "source": "census", "precision": "city", "players": 40})
    hometown_fixes.fix_hometown_spellings_main(["--sport", "softball"])
    fixes = {r["hometown_raw"]: r for r in csv.DictReader(open(tiny.hometown_corrections_csv))}
    assert fixes["Baton Rogue, La."]["city"] == "Baton Rouge" and fixes["Baton Rogue, La."]["players"] == "3"
    table = {r["hometown"]: r for r in csv.DictReader(open(tiny.rosters_dir / "hometowns.csv"))}
    assert table["Baton Rogue, La."]["city"] == "Baton Rouge" and table["Baton Rogue, La."]["lat"] == "30.45"


def test_cache_pages_are_saved_compressed_and_old_ones_still_read(tmp_path):
    f = core.Fetcher(tmp_path, delay=0)
    url = "https://a.edu/sports/softball/roster/2019"
    path = f._cache_path(url, rendered=False)
    path.write_text("<html>saved before Oct 28</html>")                # an old, uncompressed page
    assert f.get(url)[2] == "<html>saved before Oct 28</html>"
    assert not path.exists() and core.Fetcher.gz_path(path).exists()  # compressed the first time it's read
    assert f.get(url)[2] == "<html>saved before Oct 28</html>"
    old = f._cache_path(url + "x", rendered=False)
    old.write_text("<html>another</html>")
    (tmp_path / "junk.html.part").write_text("")
    core.compress_cache_main(["--cache", str(tmp_path)])
    assert core.Fetcher.read_cached(old) == "<html>another</html>" and not old.exists()
    assert not (tmp_path / "junk.html.part").exists()


def test_another_sports_page_is_never_a_roster():
    use("lacrosse-womens")
    assert sidearm.other_sport_page("https://curryathletics.com/sports/fball/2017-18/roster") == "fball"
    assert sidearm.other_sport_page("https://x.edu/roster.aspx?path=mbkb&season=2019") == "mbkb"
    assert sidearm.other_sport_page("https://x.edu/sports/womens-lacrosse/roster/2019") == ""
    assert sidearm.other_sport_page("https://x.edu/sports/lacrosse/roster/2019") == ""      # shared name: ours
    assert sidearm.other_sport_page("https://x.edu/sports/sb/roster/2019") == ""           # unknown code: not judged
    use("football")
    assert sidearm.other_sport_page("https://x.edu/sports/fball/2019-20/roster") == ""
    assert sidearm.other_sport_page("https://x.edu/sports/flagfball/2019-20/roster") == "flagfball"
    use("softball")
    rows = [{"name": "A", "roster_url": "https://x.edu/sports/womens-volleyball/roster/2019", "hometown": ""},
            {"name": "B", "roster_url": "https://x.edu/sports/softball/roster/2019", "hometown": ""}]
    assert [r["name"] for r in sr.clean_rows(rows)] == ["B"]


def test_saved_rows_from_another_sport_are_scraped_again(tiny, monkeypatch):
    # Before Oct 28 a lacrosse (here: softball) season could be saved from the football page; a --retry-failed run
    # must not count it as done, and the save drops it.
    write_season(tiny, 2025, [{**player("Alpha", f"P{i}"), "roster_url": "https://alpha.com/sports/fball/2025-26/roster"}
                              for i in range(30)])
    seen = []
    monkeypatch.setattr(sr, "scrape_school_all", lambda school, seasons, *a, **k: seen.append(school["school"]) or [])
    sr.main(["--sport", "softball", "--seasons", "2025", "--retry-failed", "--threads"])
    assert "Alpha" in seen
    assert list(csv.DictReader(open(tiny.rosters_dir / "rosters_2025.csv", encoding="utf-8"))) == []


def test_wrong_seasons_are_left_out_and_their_rows_dropped(tiny, monkeypatch):
    (core.CONFIG / "softball" / "wrong_seasons.csv").write_text("school,season,reason\nAlpha,2024,same roster as 2025\n")
    write_season(tiny, 2024, [player("Alpha", f"P{i}") for i in range(30)])
    sr.main(["--sport", "softball", "--seasons", "2024", "--threads", "--report"])
    assert list(csv.DictReader(open(tiny.rosters_dir / "rosters_2024.csv", encoding="utf-8"))) == []
    report = {r["school"]: r for r in csv.DictReader(open(tiny.rosters_dir / "scrape_report_2024.csv", encoding="utf-8"))}
    assert report["Alpha"]["status"] == "left_out" and "same roster as 2025" in report["Alpha"]["error"]
    sr.WRONG_SEASONS.clear()


def test_season_pages_list_the_page_to_use(tiny, monkeypatch):
    page = "https://alpha.com/sports/softball/roster/2023"
    (core.CONFIG / "softball" / "season_pages.csv").write_text(f"school,season,url,note\nAlpha,2024,{page},filed a year early\n")
    write_season(tiny, 2024, [{**player("Alpha", f"Old{i}"), "roster_url": "https://alpha.com/sports/softball/roster/2024"}
                              for i in range(30)])
    asked = []

    def fake_get(self, url, remember_miss=True):
        asked.append(url)
        cards = "".join(f'<li class="sidearm-roster-player"><div class="sidearm-roster-player-name"><h3><a href="/b/{i}">'
                        f'New{i}</a></h3></div><span class="sidearm-roster-player-hometown">Austin, TX</span></li>'
                        for i in range(30))
        return 200, url, f"<html><title>2023 Softball Roster</title><ul>{cards}</ul></html>"
    monkeypatch.setattr(core.Fetcher, "get", fake_get)
    sr.main(["--sport", "softball", "--seasons", "2024", "--threads", "--retry-failed", "--only", "Alpha"])
    assert asked == [page]                                   # only the listed page, and its "2023" is accepted
    rows = list(csv.DictReader(open(tiny.rosters_dir / "rosters_2024.csv", encoding="utf-8")))
    assert rows and all(r["roster_url"] == page for r in rows) and not any(r["name"].startswith("Old") for r in rows)
    sr.SEASON_PAGES.clear()


def test_every_sports_pages_match_footballs():
    # docs/football/players-*.html are the masters; scripts/build.py sync copies them to the other sports.
    # A page edited for one sport only fails here: edit football's and run the script.
    assert build.sync_pages_main(["--check"]) == 0


def test_map_data_packing_round_trip():
    P = {"s": [0, 0, 0, 1, 1], "t": [3, 1, 4, 1, 5], "p": [0, 1, 2, 0, 1], "f": [16, 16, 17, 17, 17], "l": [19, 16, 17, 20, 18],
         "x": [0, 1, 0, 0, 1], "o": [-1, 1, -1, -1, 0], "v": [0, 0, 0, 2, 0], "d": [1, 1, 1, 0, 0], "h": [0, 1, 2, 3, 4]}
    assert build.unpack_players(build.pack_players(P)) == P


def test_map_data_names_and_summary_files(tiny, tmp_path):
    # Oct 28: names in names.txt (only the dot map loads them), front-page numbers in summary.json
    write_season(tiny, 2025, [player("Alpha", "Ann Lee"), player("Alpha", "Bea Diaz", town="Dallas, TX")])
    with open(tiny.rosters_dir / "hometowns.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=geo.LOOKUP_FIELDS)
        w.writeheader()
        for town, lat, lon in (("Austin, TX", 30.27, -97.74), ("Dallas, TX", 32.78, -96.80)):
            w.writerow({"hometown": town, "school": "", "city": town.split(",")[0], "state": "TX", "country": "USA",
                        "lat": lat, "lon": lon, "source": "census", "precision": "city", "players": 1})
    dst = tmp_path / "site" / "map_data.json"
    build.make_map_data(None, dst, tiny)
    data = json.loads(dst.read_text())
    assert "names" not in data and data["players"]["packed"] and len(build.unpack_players(data["players"])["s"]) == 2
    assert dst.with_name("names.txt").read_text().split("\n") == ["Ann Lee", "Bea Diaz"]
    summary = json.loads(dst.with_name("summary.json").read_text())
    assert (summary["players"], summary["schools"], summary["first"], summary["last"]) == (2, 1, 2025, 2025)


# ---------------------------------------------------------------------------- staff pages (Oct 28)
def test_staff_parsed_from_roster_page():
    from staff import parse_staff
    html = """<div class="s-person-card"><a href="/sports/football/roster/coaches/jane-doe/12"><img alt="x"></a>
      <h3><a href="/sports/football/roster/coaches/jane-doe/12">Jane Doe</a></h3><div class="s-person-details__position">Head Coach</div></div>
      <div class="s-person-card"><a href="/sports/football/roster/coaches/bob-ray/13">Full Bio for Bob Ray</a>
      <h3><a href="/sports/football/roster/coaches/bob-ray/13">Bob Ray</a></h3><div class="s-person-details__position">Offensive Coordinator/Quarterbacks</div></div>"""
    got = parse_staff(html, "https://x.edu/sports/football/roster/2024")
    assert [(p["name"], p["title"]) for p in got] == [("Jane Doe", "Head Coach"), ("Bob Ray", "Offensive Coordinator/Quarterbacks")]


def test_staff_roles():
    from staff import role_of
    cases = {
        ("Head Coach", "Football"): "head",
        ("Interim Head Coach", "Football"): "head",
        ("Co-Head Softball Coach", "Softball"): "head",
        ("Head Women's Lacrosse Coach, Assistant Field Hockey Coach", "Lacrosse (Women's)"): "head",
        ("Associate Head Coach/Pitching", "Baseball"): "associate",
        ("Assistant Head Coach/Running Backs", "Football"): "assistant",
        ("Special Assistant to Head Coach", "Football"): "support",
        ("Head Football Equipment Manager", "Football"): "support",
        ("Head Coach, Strength & Conditioning", "Lacrosse (Men's)"): "support",
        ("Head Coach - Women's Lacrosse", "Lacrosse (Men's)"): "assistant",
        ("Defensive Coordinator | Head Women's Flag Football Coach", "Football"): "coordinator",
        ("JV Baseball Head Coach", "Baseball"): "assistant",
        ("Tight Ends", "Football"): "assistant",
    }
    for (title, sport), want in cases.items():
        assert role_of(title, sport) == want, title


def test_staff_packing_round_trip():
    from staff import pack_stints, unpack_stints
    st = {"p": [0, 0, 0, 1, 2, 2], "s": [5, 5, 7, 1, 2, 2], "y": [2016, 2017, 2019, 2024, 2020, 2021],
          "r": [2, 2, 0, 1, 6, 6], "t": [0, 0, 3, 1, 4, 5]}
    assert unpack_stints(pack_stints(st)) == st


def test_staff_moves_between_schools():
    from staff import build, person_key
    assert person_key("Mike Smith Jr.") == person_key("mike smith")
    row = lambda y, school, name, role="assistant": {"season": str(y), "school": school, "name": name, "title": role.title(), "role": role}
    rows = [row(2019, "A", "Kalen Dee", "coordinator"), row(2021, "A", "Kalen Dee", "coordinator"),
            row(2022, "B", "Kalen Dee", "head"), row(2023, "B", "Kalen Dee", "head"),
            row(2016, "A", "Deion Prime Sanders", "head"), row(2016, "C", "Deion Sanders", "head"),   # one season at two: fine
            # a common name: at A and C in the same two seasons, so two people and no moves
            row(2017, "A", "John Smith"), row(2017, "C", "John Smith"), row(2018, "A", "John Smith"), row(2018, "C", "John Smith"),
            row(2025, "C", "John Smith"),
            # four seasons apart is too long for a move
            row(2016, "B", "Pat Lee"), row(2020, "C", "Pat Lee")]
    out = build(rows, ["A", "B", "C"])
    people = out["people"].split("\n")
    moves = {(people[p], a, b, y) for p, a, b, y in zip(out["moves"]["p"], out["moves"]["a"], out["moves"]["b"], out["moves"]["y"])}
    assert moves == {("Kalen Dee", 0, 1, 2022)}
    assert people.count("John Smith") == 2 and out["shared"] == 1
    assert sum(1 for n in people if "Sanders" in n) == 1


# ---------------------------------------------------------------------------- men's hockey (Oct 28)


def test_junior_hockey_teams_are_not_colleges():
    from sidearm import looks_like_college, sort_schools
    for team in ["Omaha Lancers (USHL)", "Dubuque Fighting Saints (USHL)", "Maine Nordiques (NAHL)",
                 "Penticton Vees (BCHL)", "Youngstown Phantoms (USHL)", "Djurgardens IF J20 (J20 Nationell)"]:
        assert not looks_like_college(team), team
    assert sort_schools({"high_school": "", "previous_school": "St. Cloud Norsemen (NAHL)"})["previous_school"] == ""
    assert looks_like_college("Boston College")


