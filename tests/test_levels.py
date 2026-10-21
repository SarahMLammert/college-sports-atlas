"""The level a transfer's previous school was at (scripts/levels.py), with football's real lists."""
import pytest

from levels import Levels, is_major, key
from paths import load_sport


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
    assert lv.level("Tarleton State", 2018)[0] == "D2"      # division_history.csv: FCS from 2020
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
