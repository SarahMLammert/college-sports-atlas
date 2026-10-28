"""Oct 27 (softball hometowns): Canadian provinces, more state spellings, places abroad, text from another
column read as a hometown, the geocoder's fallbacks and retries, and the hometown fixer."""
import csv
import io
import json
import logging
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import geocode_hometowns as geo  # noqa: E402
import paths  # noqa: E402
import scrape_rosters  # noqa: E402
import sidearm  # noqa: E402
import suggest_hometown_fixes as sug  # noqa: E402
from hometowns import not_a_place, parse_hometown  # noqa: E402


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
    assert scrape_rosters.clean_row(row)["hometown"] == ""


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
        scrape_rosters.print_problems([], this_run=True)
    assert "No failed or partial schools." not in caplog.text
    assert "scraped in this run" in caplog.text


def test_left_out_count_counts_schools_once(tmp_path):
    schools = tmp_path / "softball_schools.csv"
    schools.write_text("school,division,note\nSUNY Delhi,D3,left out: bot check\nSUNY Delhi,JUCO,left out: bot check\n"
                       "Harvard,D1,left out: bot check\n", encoding="utf-8")
    with open(tmp_path / "scrape_report_2026.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=scrape_rosters.REPORT_FIELDS)
        w.writeheader()
        w.writerow({"season": 2026, "school": "SUNY Delhi", "division": "D3", "status": "left_out", "error": "left out"})
        w.writerow({"season": 2016, "school": "SUNY Delhi", "division": "JUCO", "status": "left_out", "error": "left out"})
        w.writerow({"season": 2026, "school": "Harvard", "division": "D1", "status": "left_out", "error": "left out"})
    path = scrape_rosters.write_missing_rosters(tmp_path, schools, "Softball", [], division_order=["D1", "D3", "JUCO"])
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
    assert scrape_rosters.clean_row(row)["position"] == "OF"
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
