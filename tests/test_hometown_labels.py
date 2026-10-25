"""Roster column labels saved with the hometown ("Hometown/Prev. School: ...") are taken off before
the town is read, so they never reach the geocoder as a place called "Hometown"."""
import pytest

from hometowns import parse_hometown, split_labeled_hometown


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
