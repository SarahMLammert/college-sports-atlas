"""Previous school vs. high school: python -m pytest tests -q  (or: python tests/test_previous_school.py)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scrape_rosters as sr  # noqa: E402

sr.load_known_colleges([{"school": n} for n in
                        ["Wake Forest", "Notre Dame", "SMU", "Texas", "Miami (FL)", "Duke", "Alabama", "Texas Tech"]])


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


def roster(html):
    return {p["name"]: p for p in sr.parse_roster(html)[1]}


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


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
