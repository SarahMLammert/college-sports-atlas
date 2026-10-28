"""All the tests, in one file (Oct 28, 2026; before, four files). Run them from the project folder:

    python3 -m pytest tests -q

Sections: hometowns (parser, geocoder, fixer); roster pages; hometown labels and school levels; running a
scrape (sizes, addresses, seasons, reasons, downloads, the lock, pipeline.py, the checks). conftest.py puts
scripts/ on the import path.
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

import fetch
import geocode_hometowns as geo
import paths
import scrape_rosters as sr
import sidearm
import suggest_hometown_fixes as sug
from hometowns import not_a_place, parse_hometown, split_labeled_hometown
from levels import Levels, is_major, key
from paths import load_sport
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
    ("Winnipeg, MB", home("Winnipeg", "MB", "Canada")),
    ("Saskatoon, SK", home("Saskatoon", "SK", "Canada")),
    ("Truro, NS", home("Truro", "NS", "Canada")),
    ("Pleasant Grove, PEI", home("Pleasant Grove", "PE", "Canada")),
    ("Brandon, Manitoba, CA", home("Brandon", "MB", "Canada")),          # not California
    ("Bolton, Ontario Canada", home("Bolton", "ON", "Canada")),
    ("Chilliwack, B.C. Canada", home("Chilliwack", "BC", "Canada")),
    ("Sundre, Alberta-Canada", home("Sundre", "AB", "Canada")),
    ("Calgary AB", home("Calgary", "AB", "Canada")),
    ("Okotoks Alberta", home("Okotoks", "AB", "Canada")),
    ("Chillliwack British Columbia", home("Chillliwack", "BC", "Canada")),
    ("Montreal. Quebec", home("Montreal", "QC", "Canada")),
    ("Darien, III.", home("Darien", "IL", "USA")),
    ("Lockport, lll.", home("Lockport", "IL", "USA")),
    ("Pinckneyville, Illi.", home("Pinckneyville", "IL", "USA")),
    ("Purcellville, Virg.", home("Purcellville", "VA", "USA")),
    ("Ooltewah, Ten.", home("Ooltewah", "TN", "USA")),
    ("Louisville, Kent.", home("Louisville", "KY", "USA")),
    ("Brandywine, Mary.", home("Brandywine", "MD", "USA")),
    ("Hamlin, West Va.", home("Hamlin", "WV", "USA")),
    ("Randleman, N,C,", home("Randleman", "NC", "USA")),
    ("Artesia, N,M.", home("Artesia", "NM", "USA")),
    ("New Ulm, Minn,.", home("New Ulm", "MN", "USA")),
    ("St, Joseph, Mo.", home("St. Joseph", "MO", "USA")),
    ("St. Croix, USVI", home("St. Croix", "VI", "USA")),
    ("Saipan, Mariana Islands", home("Saipan", "MP", "USA")),
    ("Puerto Rico", home("", "PR", "USA")),
    ("Trullio Alto, Puerto Rico", home("Trullio Alto", "PR", "USA")),
    ("Willemstad, Curacao", home("Willemstad", "", "Curacao")),
    ("Kowloon, Hong Kong", home("Kowloon", "", "Hong Kong")),
    ("Paderno Dugnano, Lombardia Italy", home("Paderno Dugnano", "", "Italy")),
    ("Trinidad & Tobago", home("", "", "Trinidad and Tobago")),
    ("&quot;Fort Worth,", home("Fort Worth", "", "")),
    ("Kona, Hawai‘i", home("Kona", "HI", "USA")),
    # unchanged
    ("Mobile, Ala.", home("Mobile", "AL", "USA")),
    ("Sydney, Australia", home("Sydney", "", "Australia")),
    ("Montreal, Quebec, Canada", home("Montreal", "QC", "Canada")),
    ("Saint Louis", home("Saint Louis", "", "")),          # no comma: a US state name isn't split off
    ("Port Washington", home("Port Washington", "", "")),
    ("Atlanta, Ga. / Westlake HS", home("Atlanta", "GA", "USA")),
])
def test_parse_hometown(raw, want):
    assert parse_hometown(raw) == want


@pytest.mark.parametrize("raw", ["R/R", "L/R", "R/L", "L/L", "S/R", "R", "L", "Right", "Manager", "5-7", "5'7\""])
def test_not_a_place(raw):
    assert not_a_place(raw)
    assert parse_hometown(raw) == home("", "", "")


@pytest.mark.parametrize("raw", ["Rome", "Lyons, Ga.", "Roseland", "Lake Placid", "Left Hand, W.Va."])
def test_real_towns_are_places(raw):
    assert not not_a_place(raw)


def test_bats_throws_after_a_school():
    assert parse_hometown("MSJC / R/R")["city"] == "MSJC"


def test_scraper_drops_bats_throws_hometown():
    p = {f: "" for f in sidearm.FIELDS}
    p.update(name="Jane Doe", hometown="R/R")
    assert sidearm.tidy_players([p])[0]["hometown"] == ""
    row = {"name": "Jane Doe", "hometown": "L/L", "high_school": "", "previous_school": "", "class_year": ""}
    assert sr.clean_row(row)["hometown"] == ""


# ---------------------------------------------------------------------------
# geocode_hometowns: suggestions, fallbacks, retry

def test_suggest_correction_reads_canada_not_california():
    assert geo.suggest_correction("Brandon, Manitoba, CA")[:4] == ("Brandon", "MB", "Canada", "fixed")
    assert geo.suggest_correction("Winnipeg, MB")[:4] == ("Winnipeg", "MB", "Canada", "fixed")
    assert geo.suggest_correction("Willemstad, Curacao")[:4] == ("Willemstad", "", "Curacao", "fixed")


def test_suggest_correction_more_states_and_not_a_place():
    assert geo.suggest_correction("Darien, III.")[:4] == ("Darien", "IL", "USA", "fixed")
    assert geo.suggest_correction("Purcellville, Virg.")[:4] == ("Purcellville", "VA", "USA", "fixed")
    assert geo.suggest_correction("R/R")[3] == "unfixable"
    assert geo.suggest_correction("Dallas, Texas")[:4] == ("Dallas", "TX", "USA", "fixed")   # unchanged


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


def test_us_town_list_fallback(cache):
    gaz = geo.Gazetteer()
    assert gaz.lookup_us("Ellenwood", "GA")[2:] == ("us_towns", "city")
    assert gaz.lookup_us("Thornton", "CO")[2] == "census"           # the Census list still comes first
    assert gaz.lookup_us("Arleta", "CA")[2] == "usgs"
    assert gaz.lookup_us("Nowhere", "GA") is None


def test_us_town_list_is_optional(cache):
    (cache / "us_cities.csv").unlink()
    gaz = geo.Gazetteer()
    assert gaz.lookup_us("Ellenwood", "GA") is None
    assert gaz.lookup_us("Thornton", "CO")


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
    (config / "softball.json").write_text(json.dumps({"label": "Softball", "d1_divisions": ["D1"]}))
    monkeypatch.setattr(paths, "CONFIG", config)
    monkeypatch.setattr(paths, "ROSTERS", rosters)
    return paths.load_sport("softball")


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


@pytest.mark.parametrize("raw, want", [
    ("Santo Domingo, DR", ("Santo Domingo", "", "Dominican Republic")),
    ("Santo Domingo DR", ("Santo Domingo", "", "Dominican Republic")),
    ("Santiago, Dominican Repub", ("Santiago", "", "Dominican Republic")),
    ("Caracas, VZ", ("Caracas", "", "Venezuela")),
    ("Tokyo, JPN", ("Tokyo", "", "Japan")),
    ("Cidra PR", ("Cidra", "PR", "USA")),
    ("San Juan Puerto Rico", ("San Juan", "PR", "USA")),
    ("Pago Pago. AS", ("Pago Pago", "AS", "USA")),
    ("Leone American Samoa", ("Leone", "AS", "USA")),
    ("Chitre Panama", ("Chitre", "", "Panama")),
    ("Calgary, Alb.", ("Calgary", "AB", "Canada")),
    ("Rockledge, Fla. USA", ("Rockledge", "FL", "USA")),
    ("Hilo, Hawai`i \\ Waiakea HS", ("Hilo", "HI", "USA")),
    ("Las Cruces New Mexico", ("Las Cruces New Mexico", "", "")),     # left for the fixer: not split
    ("Cidra pr", ("Cidra pr", "", "")),
])
def test_parse_hometown_oct28(raw, want):
    h = parse_hometown(raw)
    assert (h["city"], h["state"], h["country"]) == want


def test_abbreviations_in_town_names():
    assert geo.norm_city("E. Setauket") == geo.norm_city("East Setauket")
    assert geo.norm_city("Stone Mtn") == geo.norm_city("Stone Mountain")
    assert geo.norm_city("Essex Jct.") == geo.norm_city("Essex Junction")
    assert geo.norm_city("Pt. Pleasant") == geo.norm_city("Point Pleasant")


def test_areas_and_new_aliases(cache):
    gaz = geo.Gazetteer()
    assert gaz.lookup_us("Long Island", "NY")[2:] == ("area", "region")
    assert gaz.lookup_us("Kent Island", "MD")[2:] == ("area", "region")


def test_world_towns():
    pytest.importorskip("geonamescache")
    w = geo.WorldCities()
    lat, lon, src, prec = w.lookup("Toronto", "Canada", "ON")
    assert (src, prec) == ("geonames", "city") and 43 < lat < 44 and -80 < lon < -79      # not Toronto, Australia
    assert 18 < w.lookup("Santo Domingo", "Dominican Republic")[0] < 19
    assert w.lookup("Victoria", "Canada", "BC")[1] < -120          # Victoria BC, not a Victoria elsewhere in Canada
    assert w.lookup("Glasgow", "Scotland")[0] > 55
    assert w.lookup_big("Tokyo")[0] > 35 and w.lookup_big("Southington") is None


# ---------------------------------------------------------------------------
# suggest_hometown_fixes

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


def test_fixer_reads_places_abroad(towns):
    what, new = sug.suggest(row("Brandon, Manitoba, CA", "Brandon, Manitoba", "CA", "USA", "fixed"), *towns)
    assert what == "fixed: place abroad" and (new["city"], new["state"], new["country"]) == ("Brandon", "MB", "Canada")
    what, new = sug.suggest(row("Willemstad, Curacao", "Willemstad", "", "Curacao"), *towns)
    assert new["country"] == "Curacao" and new["status"] == "fixed"
    assert sug.suggest(row("Teulon, MB", "Teulon", "MB", "Canada", "fixed"), *towns) is None   # already right


def test_fixer_more_state_spellings(towns):
    what, new = sug.suggest(row("Darien, III.", "Darien", "", "III."), *towns)
    assert (new["city"], new["state"], new["status"]) == ("Darien", "IL", "fixed")


def test_fixer_not_a_place(towns):
    what, new = sug.suggest(row("R/R", "R", "", "", "fixed"), *towns)
    assert new["status"] == "unfixable"


def test_fixer_wrong_state_is_only_a_suggestion(towns):
    what, new = sug.suggest(row("Murrieta, GA", "Murrieta", "GA", "USA", "fixed"), *towns)
    assert new["status"] == "review" and "CA" in new["note"]
    assert sug.suggest(row("Rockaway, Pa.", "Rockaway", "PA", "USA", "fixed"), *towns) is None   # two states
    assert sug.suggest(row("Darie, GA", "Darie", "GA", "USA", "fixed"), *towns) is None           # too short


def test_fixer_uses_the_geocoders_cached_lists(cache, monkeypatch):
    names = set(sug.geocoder_place_names())
    assert ("CO", "Thornton") in names and ("NY", "Cortlandt") in names and ("CA", "Arleta") in names


# ---------------------------------------------------------------------------
# scrape_rosters

def test_problem_list_wording_for_one_run(caplog):
    with caplog.at_level(logging.INFO, logger="rosters"):
        sr.print_problems([], this_run=True)
    assert "No failed or partial schools." not in caplog.text
    assert "scraped in this run" in caplog.text


def test_left_out_count_counts_schools_once(tmp_path):
    schools = tmp_path / "softball_schools.csv"
    schools.write_text("school,division,note\nSUNY Delhi,D3,left out: bot check\nSUNY Delhi,JUCO,left out: bot check\n"
                       "Harvard,D1,left out: bot check\n", encoding="utf-8")
    with open(tmp_path / "scrape_report_2026.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sr.REPORT_FIELDS)
        w.writeheader()
        w.writerow({"season": 2026, "school": "SUNY Delhi", "division": "D3", "status": "left_out", "error": "left out"})
        w.writerow({"season": 2016, "school": "SUNY Delhi", "division": "JUCO", "status": "left_out", "error": "left out"})
        w.writerow({"season": 2026, "school": "Harvard", "division": "D1", "status": "left_out", "error": "left out"})
    path = sr.write_missing_rosters(tmp_path, schools, "Softball", [], division_order=["D1", "D3", "JUCO"])
    assert "## Left out on purpose (2 schools)" in path.read_text(encoding="utf-8")


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
    ('<span class="text-bold"><span class="sidearm-roster-player-position-long-short hide-on-small-down"> OF R/R </span>'
     '</span><span class="sidearm-roster-player-custom1">R/R</span>', "OF"),
    ('<span class="sidearm-roster-player-custom1">R?R</span>', ""),                                    # Bluefield
    ('<span class="sidearm-roster-player-position-long-short">Wide Receiver</span>', "Wide Receiver"),
])
def test_classic_position_without_bats_throws(position_html, want):
    from bs4 import BeautifulSoup
    html = _classic_page(position_html)
    players = sidearm.parse_sidearm_classic(html, BeautifulSoup(html, "lxml"))
    assert sidearm.tidy_players(players)[0]["position"] == want


def test_saved_positions_lose_bats_throws():
    row = {"name": "Jane Doe", "hometown": "Austin, Texas", "position": "OF R/R", "high_school": "",
           "previous_school": "", "class_year": ""}
    assert sr.clean_row(row)["position"] == "OF"
    assert sidearm.strip_bats_throws("RHP") == "RHP" and sidearm.strip_bats_throws("LHP/OF") == "LHP/OF"


def test_state_only_gets_the_states_middle(cache):
    gaz = geo.Gazetteer()
    lat, lon, src, prec = geo.resolve(parse_hometown("TX"), gaz, None)
    assert (src, prec) == ("state", "region") and (lat, lon) == (32.8, -96.8)   # the tiny list's one TX town
    assert geo.resolve({"city": "Texas", "state": "", "country": ""}, gaz, None)[2] == "state"


def test_world_towns_dutch_and_bare_country_towns():
    pytest.importorskip("geonamescache")
    assert geo.WorldCities().lookup("Amsterdam", "Netherlands")[0] > 52     # GeoNames says "The Netherlands"
    assert parse_hometown("Lebanon") == {"city": "Lebanon", "state": "", "country": ""}
    assert parse_hometown("Columbia")["country"] == "" and parse_hometown("Bogota, Columbia")["country"] == "Colombia"


def test_parse_brackets_islands():
    assert parse_hometown("Pago Pago (AS)") == {"city": "Pago Pago", "state": "AS", "country": "USA"}
    assert parse_hometown("Maui") == {"city": "Maui", "state": "HI", "country": "USA"}


def test_first_nations_and_territory_towns(cache):
    pytest.importorskip("geonamescache")
    gaz = geo.Gazetteer()
    lat, lon, src, _ = geo.resolve(parse_hometown("Kahnawake Mohawk Territory"), gaz, None)
    assert src == "geonames" and 45 < lat < 46 and -74 < lon < -73
    assert geo.resolve(parse_hometown("Pago Pago"), gaz, None)[0] < -14


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

@pytest.mark.usefixtures("football")
def test_hometown_parsing():
    assert parse_hometown("Mobile, Ala.") == {"city": "Mobile", "state": "AL", "country": "USA"}
    assert parse_hometown("St. Louis, MO") == {"city": "St. Louis", "state": "MO", "country": "USA"}
    assert parse_hometown("Washington, D.C.")["state"] == "DC"
    assert parse_hometown("Melbourne, Australia") == {"city": "Melbourne", "state": "", "country": "Australia"}
    assert parse_hometown("Toronto, Ont.")["country"] == "Canada"
    assert parse_hometown("Houston, Texas, USA")["state"] == "TX"
    assert parse_hometown("Fort Worth, Texas (Paschal HS)")["city"] == "Fort Worth"
    assert split_hometown_highschool("Tracy, Calif. / Edison") == ("Tracy, Calif.", "Edison")


@pytest.mark.usefixtures("football")
def test_hometown_with_school_attached():
    assert parse_hometown("Atlanta, Ga. / Westlake HS") == {"city": "Atlanta", "state": "GA", "country": "USA"}
    assert parse_hometown("Houston, Texas (Alief Taylor)")["state"] == "TX"
    assert parse_hometown("Houston, Texas - Lamar HS")["state"] == "TX"
    assert parse_hometown("Hometown/Last School: Mobile, Ala.")["city"] == "Mobile"
    assert parse_hometown("Winston-Salem, N.C.")["city"] == "Winston-Salem"


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


@pytest.mark.usefixtures("football")
def test_recombine_fixes_saved_rows():
    """Rows saved by the old version (college stuck in high_school) are fixed when the files are rebuilt."""
    row = {"high_school": "Wake Forest", "previous_school": ""}
    sr.sort_schools(row)
    assert row == {"high_school": "", "previous_school": "Wake Forest"}


# ==================================================================================================
# Labels in hometown fields, and the levels of previous schools
# ==================================================================================================

# ---------------------------------------------------------------------------- roster labels in hometowns
# Labels saved with the hometown ("Hometown/Prev. School: ...") are taken off before the town is read,
# so they never reach the geocoder as a place called "Hometown".

@pytest.mark.parametrize("raw, town, school", [
    ("Hometown/Prev. School: Wilson, NC / Beddingfield", "Wilson, NC", "Beddingfield"),
    ("Hometown/Previous School(s): Omaha, Neb.", "Omaha, Neb.", ""),
    ("Hometown/High School/Previous College: Wichita, KS", "Wichita, KS", ""),
    ("Hometown/Last School: Milford, CT /", "Milford, CT", ""),
    ("Hometown/Prev. School: / East Bladen", "", "East Bladen"),
    ("Hometown/High School.: Honolulu", "Honolulu", ""),
    ("HS City (State): Mayfair HS / Lakewood (CA)", "Lakewood, CA", "Mayfair HS"),
    ("HS City (State): Mayfair", "", "Mayfair"),
    ("HS City (State): Lakewood/University of Nevada", "", "Lakewood / University of Nevada"),
    ("HS Hometown/High School: Santa Ana", "Santa Ana", ""),
    ("HS Hometown/High School:", "", ""),
    ("ICC Grad Date:", "", ""),
    # no label: unchanged
    ("Atlanta, Ga.", "Atlanta, Ga.", ""),
    ("Atlanta, Ga. / Westlake HS", "Atlanta, Ga. / Westlake HS", ""),
    ("Twitter:", "Twitter:", ""),
])
def test_split_labeled_hometown(raw, town, school):
    assert split_labeled_hometown(raw) == (town, school)


@pytest.mark.parametrize("raw, city, state", [
    ("Hometown/Previous School(s): Omaha, Neb.", "Omaha", "NE"),
    ("HS City (State): Long Beach Wilson HS / Long Beach (CA)", "Long Beach", "CA"),
    ("Hometown/Prev. School: Charlotte, NC / Olympic", "Charlotte", "NC"),
])
def test_parse_hometown_reads_past_the_label(raw, city, state):
    h = parse_hometown(raw)
    assert (h["city"], h["state"]) == (city, state)


@pytest.mark.parametrize("raw", ["HS City (State): Mayfair", "ICC Grad Date:", "HS Hometown/High School:"])
def test_label_without_a_town_is_no_hometown(raw):
    assert parse_hometown(raw) == {"city": "", "state": "", "country": ""}


# ---------------------------------------------------------------------------- transfer levels

@pytest.fixture(scope="module")
def lv():
    return Levels.load(load_sport("football"))


@pytest.mark.parametrize("text, year, level", [
    ("Valdosta St.", 2018, "D2"),
    ("Valdosta State University", 2018, "D2"),
    ("UW-Whitewater", 2020, "D3"),
    ("Hutchinson (Kan.) CC", 2022, "JUCO"),
    ("Iowa Western", 2022, "JUCO"),
    ("College of the Canyons", 2019, "JUCO"),
    ("Some Town Junior College", 2019, "JUCO"),            # generic two-year wording
    ("Lindsey Wilson College", 2019, "NAIA"),
    ("Hope College", 2019, "D3"),
    ("Notre Dame", 2019, "D1"),
    ("Notre Dame College", 2019, "D2"),                    # Ohio, Division II until it closed
    ("Illinois College", 2019, "D3"),
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
    assert lv.level("Thomas More", 2017)[0] == "D3"
    assert lv.level("Thomas More", 2020)[0] == "NAIA"
    assert lv.level("Thomas More", 2024)[0] == "D2"
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
    sidearm.configure(paths.load_sport(name))


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
    """A project folder with config/softball.json and an empty rosters/softball/."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "CONFIG", tmp_path / "config")
    monkeypatch.setattr(paths, "ROSTERS", tmp_path / "rosters")
    (tmp_path / "config").mkdir()
    (tmp_path / "rosters" / "softball").mkdir(parents=True)
    (tmp_path / "config" / "softball.json").write_text(json.dumps(SETTINGS))
    with open(tmp_path / "config" / "softball_schools.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["school", "division", "conference", "domain", "roster_url", "first_season", "last_season",
                    "aliases", "note"])
        w.writerow(["Alpha", "D1", "X", "alpha.com", "", "", "", "", ""])
        w.writerow(["Blocked", "D3", "Y", "blocked.edu", "", "", "", "", "left out: bot check every season"])
    sport = paths.load_sport("softball")
    sidearm.configure(sport)
    yield sport
    fetch.SPRING_SEASON = False


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


def test_saved_rosters_are_judged_by_the_sport():
    use("baseball")
    season = lambda n: [{"school": "A", "division": "D1", "hometown": "X"} for _ in range(n)]
    assert sr.saved_reports(season(38))["A"]["status"] == "ok"
    assert sr.saved_reports(season(8))["A"]["status"] == "partial"
    assert sr.saved_reports(season(130))["A"]["status"] == "partial"


def test_reasons_say_what_is_off():
    use("baseball")
    assert "fewer than a normal roster" in sr.plain_reason({"status": "partial", "players": 8, "with_hometown": 8})
    assert "more than a normal roster" in sr.plain_reason({"status": "partial", "players": 130, "with_hometown": 130})
    assert "hometowns" in sr.plain_reason({"status": "partial", "players": 38, "with_hometown": 5})


def test_oversized_reason_no_longer_says_wrong_page(tiny):
    why = sr.plain_reason({"status": "partial", "players": 80, "error": ""})
    assert why.startswith("80 players, more than a normal roster for this sport (at most 55)")
    assert "wrong page" not in why


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
    assert "too long" in sr.plain_reason(out[0][2])


# ---------------------------------------------------------------------------- seasons

def test_current_season_fall_and_spring():
    fetch.SPRING_SEASON = False
    assert fetch.current_season(date(2026, 10, 27)) == 2026      # football in the autumn: this fall
    assert fetch.current_season(date(2027, 2, 1)) == 2026
    fetch.SPRING_SEASON = True
    try:
        assert fetch.current_season(date(2026, 10, 27)) == 2027  # softball in the autumn: next spring
        assert fetch.current_season(date(2026, 4, 1)) == 2026
        assert fetch.current_season(date(2026, 7, 31)) == 2026
        assert fetch.current_season(date(2026, 8, 1)) == 2027
    finally:
        fetch.SPRING_SEASON = False


def test_configure_sets_spring_for_fetch(tiny):
    assert fetch.SPRING_SEASON is True


def test_default_seasons():
    assert paths.Sport(name="football").default_seasons() == "2016-2019,2021-2026"
    assert paths.Sport(name="softball").default_seasons() == "2016-2026"
    assert paths.Sport(name="softball", seasons="2018-2026").default_seasons() == "2018-2026"


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


def test_no_www_copy_of_a_subdomain(tiny):
    sub = sidearm.candidate_urls("athletics.cabrillo.edu", "", 2024)
    assert not any("www.athletics" in u for u in sub)
    bare = sidearm.candidate_urls("alpha.com", "", 2024)
    assert "https://www.alpha.com/sports/softball/roster/2024" in bare


def test_short_reason_browser_and_timeouts():
    err = ("render https://x.edu/r/2024: page.goto: Timeout 15000ms exceeded.\nCall log: navigating; "
           "render https://x.edu/r/2024-25: browser gave up after 45s; "
           "https://x.edu/r/2023: ReadTimeout; https://x.edu/r/2022: HTTP 202")
    assert sr.short_reason(err) == "browser: too slow ×2, too slow, bot check"
    assert sr.short_reason("render https://x/r: no players found") == "browser: no players found"
    assert sr.short_reason("render https://x/r: page shows 2025") == "browser: page shows 2025"
    assert sr.short_reason("render https://x/r: bot check not passed") == "browser: bot check not passed"


def test_left_out_old_and_new_reports():
    assert sr.is_left_out({"status": "left_out", "error": "left out: x"})
    assert sr.is_left_out({"status": "failed", "error": "Left out: bot check"})     # before Oct 27
    assert not sr.is_left_out({"status": "failed", "error": "https://x: HTTP 404"})


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
    f = fetch.Fetcher(tmp_path, delay=0)
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
    f = fetch.Fetcher(tmp_path, delay=0)
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
    with paths.sport_lock(tiny, "first run"):
        with pytest.raises(paths.SportBusy, match="first run"):
            with paths.sport_lock(tiny, "second run"):
                pass
    with paths.sport_lock(tiny, "after"):      # free again once the first is done
        pass


def test_pipeline_steps_share_its_lock(tiny, monkeypatch):
    monkeypatch.setenv(paths.LOCK_ENV, "softball")
    with paths.sport_lock(tiny, "pipeline"):
        with paths.sport_lock(tiny, "its scrape step"):
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
    assert plan(tiny).steps == ["scrape", "retry", "geocode", "fix-hometowns", "frozen", "build", "locations", "check"]
    assert plan(tiny, "from_step=geocode").steps[0] == "geocode"
    assert "scrape" not in plan(tiny, "skip=scrape,retry").steps
    assert plan(tiny, "steps=check,build").steps == ["build", "check"]
    assert "redo-current" in plan(tiny, "redo_current").steps
    with pytest.raises(SystemExit):
        plan(tiny, "steps=bild")


def test_pipeline_first_pass_only_fills_gaps_once_rosters_exist(tiny):
    first = plan(tiny).commands["scrape"][0]
    assert "--retry-failed" not in first and "2016-2026" in first and "--report" in first
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
    import check_rosters
    names = [f"Ann {a}{b}son" for a in "abcdefgh" for b in "abcdefgh"][:60]
    write_season(tiny, 2023, [player("Alpha", n, "FR") for n in names[:15]])
    write_season(tiny, 2024, [player("Alpha", n, "SO") for n in names[:15]] + [player("Alpha", n) for n in names[15:50]])
    write_season(tiny, 2025, [player("Alpha", n, "JR") for n in names[:15]])
    write_season(tiny, 2026, [player("Alpha", n, "JR") for n in names[:15]])   # 2025's page again
    assert check_rosters.main(["--sport", "softball"]) == 0
    out = capsys.readouterr().out
    assert "Alpha 2024: 50 players (usually 15)" in out
    assert "Alpha 2026: 15 players (100% same names and 100% same class years as 2025)" in out
    assert "Alpha 2025" not in out.split("Rosters nearly the same")[1]     # moved up a class: a real roster
    rows = list(csv.DictReader(open(tiny.rosters_dir / "roster_checks.csv")))
    assert {(r["check"], r["season"]) for r in rows} == {("oversized", "2024"), ("repeated", "2026")}


def test_frozen_check_with_too_few_players_doesnt_crash(tiny, capsys):
    import check_frozen_classes
    write_season(tiny, 2025, [player("Alpha", "Ann Lee", "FR")])
    write_season(tiny, 2026, [player("Alpha", "Ann Lee", "SO")])
    check_frozen_classes.main(["--sport", "softball"])
    assert (tiny.rosters_dir / "frozen_class_seasons.csv").exists()


def test_spelling_fixes_read_the_geocoders_table(tiny):
    import fix_hometown_spellings
    with open(tiny.rosters_dir / "hometowns.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["hometown", "school", "city", "state", "country", "lat", "lon",
                                          "source", "precision", "players"])
        w.writeheader()
        w.writerow({"hometown": "Baton Rogue, La.", "city": "Baton Rogue", "state": "LA", "country": "USA",
                    "lat": "30.5", "lon": "-91.1", "source": "usgs", "precision": "city", "players": 3})
        w.writerow({"hometown": "Baton Rouge, La.", "city": "Baton Rouge", "state": "LA", "country": "USA",
                    "lat": "30.45", "lon": "-91.15", "source": "census", "precision": "city", "players": 40})
    fix_hometown_spellings.main(["--sport", "softball"])
    fixes = {r["hometown_raw"]: r for r in csv.DictReader(open(tiny.hometown_corrections_csv))}
    assert fixes["Baton Rogue, La."]["city"] == "Baton Rouge" and fixes["Baton Rogue, La."]["players"] == "3"
    table = {r["hometown"]: r for r in csv.DictReader(open(tiny.rosters_dir / "hometowns.csv"))}
    assert table["Baton Rogue, La."]["city"] == "Baton Rouge" and table["Baton Rogue, La."]["lat"] == "30.45"


def test_cache_pages_are_saved_compressed_and_old_ones_still_read(tmp_path):
    f = fetch.Fetcher(tmp_path, delay=0)
    url = "https://a.edu/sports/softball/roster/2019"
    path = f._cache_path(url, rendered=False)
    path.write_text("<html>saved before Oct 28</html>")                # an old, uncompressed page
    assert f.get(url)[2] == "<html>saved before Oct 28</html>"
    assert not path.exists() and fetch.Fetcher.gz_path(path).exists()  # compressed the first time it's read
    assert f.get(url)[2] == "<html>saved before Oct 28</html>"
    import compress_cache
    old = f._cache_path(url + "x", rendered=False)
    old.write_text("<html>another</html>")
    (tmp_path / "junk.html.part").write_text("")
    compress_cache.main(["--cache", str(tmp_path)])
    assert fetch.Fetcher.read_cached(old) == "<html>another</html>" and not old.exists()
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
    (paths.CONFIG / "softball_wrong_seasons.csv").write_text("school,season,reason\nAlpha,2024,same roster as 2025\n")
    write_season(tiny, 2024, [player("Alpha", f"P{i}") for i in range(30)])
    sr.main(["--sport", "softball", "--seasons", "2024", "--threads", "--report"])
    assert list(csv.DictReader(open(tiny.rosters_dir / "rosters_2024.csv", encoding="utf-8"))) == []
    report = {r["school"]: r for r in csv.DictReader(open(tiny.rosters_dir / "scrape_report_2024.csv", encoding="utf-8"))}
    assert report["Alpha"]["status"] == "left_out" and "same roster as 2025" in report["Alpha"]["error"]
    assert "Alpha** (D1, seasons 2024): 2024: Left out: same roster as 2025" in \
        (tiny.rosters_dir / "MISSING_ROSTERS.md").read_text()
    sr.WRONG_SEASONS.clear()


def test_season_pages_list_the_page_to_use(tiny, monkeypatch):
    page = "https://alpha.com/sports/softball/roster/2023"
    (paths.CONFIG / "softball_season_pages.csv").write_text(f"school,season,url,note\nAlpha,2024,{page},filed a year early\n")
    write_season(tiny, 2024, [{**player("Alpha", f"Old{i}"), "roster_url": "https://alpha.com/sports/softball/roster/2024"}
                              for i in range(30)])
    asked = []

    def fake_get(self, url, remember_miss=True):
        asked.append(url)
        cards = "".join(f'<li class="sidearm-roster-player"><div class="sidearm-roster-player-name"><h3><a href="/b/{i}">'
                        f'New{i}</a></h3></div><span class="sidearm-roster-player-hometown">Austin, TX</span></li>'
                        for i in range(30))
        return 200, url, f"<html><title>2023 Softball Roster</title><ul>{cards}</ul></html>"
    monkeypatch.setattr(fetch.Fetcher, "get", fake_get)
    sr.main(["--sport", "softball", "--seasons", "2024", "--threads", "--retry-failed", "--only", "Alpha"])
    assert asked == [page]                                   # only the listed page, and its "2023" is accepted
    rows = list(csv.DictReader(open(tiny.rosters_dir / "rosters_2024.csv", encoding="utf-8")))
    assert rows and all(r["roster_url"] == page for r in rows) and not any(r["name"].startswith("Old") for r in rows)
    sr.SEASON_PAGES.clear()


def test_every_sports_pages_match_footballs():
    # docs/football/players-*.html are the masters; scripts/sync_pages.py copies them to the other sports.
    # A page edited for one sport only fails here: edit football's and run the script.
    import sync_pages
    assert sync_pages.main(["--check"]) == 0


def test_map_data_names_and_summary_files(tiny, tmp_path):
    # Oct 28: names in names.txt (only the dot map loads them), front-page numbers in summary.json
    import build_map_data
    write_season(tiny, 2025, [player("Alpha", "Ann Lee"), player("Alpha", "Bea Diaz", town="Dallas, TX")])
    with open(tiny.rosters_dir / "hometowns.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=geo.LOOKUP_FIELDS)
        w.writeheader()
        for town, lat, lon in (("Austin, TX", 30.27, -97.74), ("Dallas, TX", 32.78, -96.80)):
            w.writerow({"hometown": town, "school": "", "city": town.split(",")[0], "state": "TX", "country": "USA",
                        "lat": lat, "lon": lon, "source": "census", "precision": "city", "players": 1})
    dst = tmp_path / "site" / "map_data.json"
    build_map_data.main(None, dst, tiny)
    data = json.loads(dst.read_text())
    assert "names" not in data and len(data["players"]["s"]) == 2
    assert dst.with_name("names.txt").read_text().split("\n") == ["Ann Lee", "Bea Diaz"]
    summary = json.loads(dst.with_name("summary.json").read_text())
    assert (summary["players"], summary["schools"], summary["first"], summary["last"]) == (2, 1, 2025, 2025)
