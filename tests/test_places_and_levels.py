"""Hometown fields with roster labels on them (scripts/hometowns.py), and the level a transfer's previous
school was at (scripts/levels.py, with football's real lists)."""
import pytest

from hometowns import parse_hometown, split_labeled_hometown
from levels import Levels, is_major, key
from paths import load_sport


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
