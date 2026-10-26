"""A normal roster size is set per sport (min_players to max_players in config/<sport>.json)."""
import paths
import scrape_rosters as sr
import sidearm


def use(name):
    sidearm.configure(paths.load_sport(name))


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
