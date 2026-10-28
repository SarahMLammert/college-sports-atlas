"""Running a scrape: roster sizes per sport, addresses, seasons, reasons, downloads, the one-run lock,
pipeline.py and check_rosters.py."""
import csv
import json
from datetime import date

import pytest
import requests

import fetch
import paths
import scrape_rosters as sr
import sidearm


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
