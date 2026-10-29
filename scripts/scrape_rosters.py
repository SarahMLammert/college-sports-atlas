"""Scrape a sport's rosters into CSV, for one season or many.

To run every step for a sport at once (scrape, retry, geocode, build, check), use scripts/pipeline.py:
    python3 scripts/pipeline.py softball

Examples
    python scripts/scrape_rosters.py                                   # current season, every school
    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026     # last 10 seasons, skipping 2020
    python scripts/scrape_rosters.py --seasons 2019 --only "Alabama,Clemson"
    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed --render
    python scripts/scrape_rosters.py --recombine                       # no downloads: re-clean the saved season files
    python scripts/scrape_rosters.py --sport lacrosse-mens             # another sport (needs config/lacrosse-mens/settings.json)
    python scripts/scrape_rosters.py --seasons 2016-2026 --report      # also write the scrape reports and MISSING_ROSTERS.md

Reads config/<sport>/settings.json and config/<sport>/schools.csv (default sport: football).

Outputs (in rosters/<sport>/, or --out). The rosters are all cleaned: no jersey numbers or captain
marks in names, hometowns split into city/state/country, high school and previous school sorted out.
    rosters_<season>.csv          every player that season, one row each (the later steps read these)
Only with --combined (for opening in a spreadsheet; nothing else needs them):
    rosters_all_seasons.csv       every saved season stacked (one row per player per season)
    players_unique.csv            one row per player per school, with first/last season on the roster
Only with --report:
    scrape_report_<season>.csv    per school: status, strategy, player counts, URL, errors
    MISSING_ROSTERS.md            the failed and partial schools by division, with reasons (always in rosters/<sport>/)

--retry-failed doesn't need the reports: it tells which school-seasons are done from the saved rosters.

Fetching, page parsing and field cleaning live in core.py, sidearm.py and geocode.py next to this script.

This file holds, in order:
    Scraping rosters
    Finding athletics domains (find-domains)

Commands:
    python3 scripts/scrape_rosters.py find-domains --sport football   # finding athletics domains
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ==============================================================================================================
# Scraping rosters   (was scripts/scrape_rosters.py)
# ==============================================================================================================

SCRAPE_ROSTERS_DOC = 'Scrape a sport\'s rosters into CSV, for one season or many.\n\nTo run every step for a sport at once (scrape, retry, geocode, build, check), use scripts/pipeline.py:\n    python3 scripts/pipeline.py softball\n\nExamples\n    python scripts/scrape_rosters.py                                   # current season, every school\n    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026     # last 10 seasons, skipping 2020\n    python scripts/scrape_rosters.py --seasons 2019 --only "Alabama,Clemson"\n    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed --render\n    python scripts/scrape_rosters.py --recombine                       # no downloads: re-clean the saved season files\n    python scripts/scrape_rosters.py --sport lacrosse-mens             # another sport (needs config/lacrosse-mens/settings.json)\n    python scripts/scrape_rosters.py --seasons 2016-2026 --report      # also write the scrape reports and MISSING_ROSTERS.md\n\nReads config/<sport>/settings.json and config/<sport>/schools.csv (default sport: football).\n\nOutputs (in rosters/<sport>/, or --out). The rosters are all cleaned: no jersey numbers or captain\nmarks in names, hometowns split into city/state/country, high school and previous school sorted out.\n    rosters_<season>.csv          every player that season, one row each (the later steps read these)\nOnly with --combined (for opening in a spreadsheet; nothing else needs them):\n    rosters_all_seasons.csv       every saved season stacked (one row per player per season)\n    players_unique.csv            one row per player per school, with first/last season on the roster\nOnly with --report:\n    scrape_report_<season>.csv    per school: status, strategy, player counts, URL, errors\n    MISSING_ROSTERS.md            the failed and partial schools by division, with reasons (always in rosters/<sport>/)\n\n--retry-failed doesn\'t need the reports: it tells which school-seasons are done from the saved rosters.\n\nFetching, page parsing and field cleaning live in core.py, sidearm.py and geocode.py next to this script.\n'
import argparse
import os
import warnings
import csv
import logging
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import core, geocode, sidearm
from core import Fetcher, current_season
from geocode import *            # noqa: F401,F403
from core import UNIQUE_FIELDS, build_unique, person_key, read_csv, season_files   # shared with the later steps
from core import ROOT, SCRAPED, add_sport_argument, d1_schools, division_for, load_all_colleges, load_division_history, load_schools, load_sport, sport_lock
from sidearm import *              # noqa: F401,F403

# Older code imported everything from this file (`from scrape_rosters import parse_hometown`); keep
# those names here, including the underscored helpers, so it still works.
for _mod in (core, geocode, sidearm):
    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__") and k not in globals()})
# =============================================================================
# Scraping and output
# =============================================================================

log = logging.getLogger("rosters")
SEASON_PAGES: dict[tuple[str, int], str] = {}    # config/<sport>/season_pages.csv: the one page to use
WRONG_SEASONS: dict[tuple[str, int], str] = {}   # config/<sport>/wrong_seasons.csv, set by run() and the workers
RENDER_TRIES = 2   # most addresses rendered per school-season with --render (each takes a few seconds)
SCHOOL_MINUTES = 3.0   # a school that takes longer stops starting new seasons (--school-minutes)
# A site's own link to a season roster in PrestoSports style: /sports/fball/2026-27/roster (Mars Hill),
# /sports/m-footbl/2026-27/roster (Carson-Newman, Presto's older code). Not flag football ("flagfball").
# The sport's codes come from its presto_paths (fball, bsb, sball, mlax, wlax) plus Presto's older code for each.
PRESTO_OLD_CODES = {"fball": "m-footbl", "bsb": "m-basebl", "sball": "w-softbl", "mlax": "m-lacros", "wlax": "w-lacros"}


def roster_link_re() -> re.Pattern:
    codes = {m.group(1) for p in sidearm.PRESTO_PATHS for m in [re.search(r"/sports/([^/{]+)/", p)] if m}
    codes |= {PRESTO_OLD_CODES[c] for c in list(codes) if c in PRESTO_OLD_CODES}
    alts = "|".join(sorted(map(re.escape, codes))) or "fball|m-footbl"
    return re.compile(rf'href="[^"]*/sports/({alts})/\d{{4}}-\d{{2}}/roster\b')


def presto_season(season: int) -> str:
    """Presto's season label: fall 2024 -> '2024-25'; a spring sport's 2024 season -> '2023-24'."""
    return f"{season - 1}-{season % 100:02d}" if sidearm.SPRING else f"{season}-{(season + 1) % 100:02d}"

OUT_FIELDS = (
    ["season", "division", "current_conference", "school"]
    + [f for f in FIELDS if f != "bio_url"]
    + ["class_norm", "home_city", "home_state", "home_country", "strategy", "bio_url", "roster_url"]
)
REPORT_FIELDS = ["season", "school", "division", "current_conference", "status", "season_check",
                 "strategy", "players", "with_hometown", "url", "error"]


# ---------------------------------------------------------------------------
# inputs

def parse_seasons(spec: str) -> list[int]:
    """'2016-2019,2021-2026' -> [2016, 2017, 2018, 2019, 2021, ..., 2026]"""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            out.update(range(min(a, b), max(a, b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


# ---------------------------------------------------------------------------
# scraping

BIO_PROBE = 5   # player pages tried before giving up on a site whose pages have no hometowns either


def fill_from_bios(players: list[dict], roster_url: str, fetcher: Fetcher, errors: list[str]) -> int:
    """--bios: for a roster that lists players but mostly no hometowns (Morehouse), read each
    player's own page for his hometown, high school and previous school. Only blank fields are
    filled. Returns how many players got a hometown.

    Skipped when most players already have a hometown, or most have no page linked. If the first
    few pages have nothing either (Tyler's pages are built by script), the rest aren't fetched."""
    if not players or sum(1 for p in players if p["hometown"]) >= 0.5 * len(players):
        return 0
    todo = [p for p in players if not p["hometown"] and p.get("bio_url")]
    if len(todo) < 0.5 * len(players):
        return 0
    filled = tried = 0
    for p in todo:
        if tried >= BIO_PROBE and not filled:
            errors.append(f"bios: the first {tried} player pages had no hometown; skipped the rest")
            break
        tried += 1
        bio = urljoin(roster_url, p["bio_url"])
        try:
            status, _, html = fetcher.get(bio)
        except Exception as exc:
            errors.append(f"bio {bio}: {type(exc).__name__}")
            continue
        if status != 200:
            continue
        found = parse_bio(html)
        for f in ("hometown", "high_school", "previous_school"):
            if found[f] and not p.get(f):
                p[f] = found[f]
        if found["hometown"]:
            filled += 1
            sort_schools(p)
    if filled:
        errors.append(f"bios: hometowns from {filled} of {tried} player pages")
    return filled


def scrape_school_season(school: dict, fetcher: Fetcher, season: int, division: str,
                         render: bool, prefer_idx: int | None,
                         save_dir: Path | None = None, bios: bool = False) -> tuple[list[dict], dict, int | None]:
    is_current = season == current_season()
    report = {"season": season, "school": school["school"], "division": division,
              "current_conference": school.get("conference", ""), "status": "failed",
              "season_check": "", "strategy": "", "players": 0, "with_hometown": 0, "url": "", "error": ""}
    urls = candidate_urls(school.get("domain", ""), school.get("roster_url", ""), None if is_current else season)
    fixed_page = SEASON_PAGES.get((school["school"], season))
    if fixed_page:
        # Listed in config/<sport>/season_pages.csv: this page holds the season, whatever year it shows
        urls = [fixed_page]
    if is_current and not fixed_page:
        # A school's main roster page can still show last season for weeks (New Haven 2026 came
        # back identical to 2025). Its year is checked like any archive page's, and this season's
        # archive URLs are tried after it in case the main page hasn't switched over.
        urls += [u for u in candidate_urls(school.get("domain", ""), school.get("roster_url", ""), season)
                 if u not in urls]
    order = list(range(len(urls)))
    if prefer_idx is not None and prefer_idx < len(urls):  # try last season's winning URL pattern first
        order.remove(prefer_idx)
        order.insert(0, prefer_idx)

    best = ("", [], "", None, "")  # strategy, players, url, idx, season_check
    errors: list[str] = []
    loaded: list[int] = []         # URLs that answered with a page (the ones worth rendering)
    blocked: list[int] = []        # URLs that answered with a bot check (HTTP 202) or a certificate error
    app_shell = False              # the site is a script-built app (empty <div id="root">), like Tyler's
    # Hosts that answered with a bot check. Their other addresses would get the same answer, so they
    # aren't asked again this season: a site that says no gets one request, not a dozen. Kept per
    # host, not per site, because some sites block the bare domain but answer on www. (Riverside).
    blocked_hosts: set[str] = set()
    for idx in order:
        url = urls[idx]
        host = urlparse(url).netloc.lower()
        if host in blocked_hosts:
            continue
        try:
            status, final_url, html = fetcher.get(url, remember_miss=not is_current)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            if "SSL" in type(exc).__name__:   # Python rejects the site's certificate; a browser may not
                blocked.append(idx)
            continue
        if status != 200:
            errors.append(f"{url}: HTTP {status}")
            if status == 202:                 # a bot check: the page only appears in a browser, if at all
                blocked.append(idx)
                blocked_hosts.add(host)
            continue
        if len(html) < 5000 and 'id="root"></div>' in html.replace(" ", ""):
            app_shell = True
        if fixed_page:
            shown = None
            loaded.append(idx)
            check = "verified"
            strategy, players = parse_roster(html)
            if not players:
                errors.append(f"{url}: no players found")
            best = (strategy, players, url, idx, check)    # saved under the listed address, redirect or not
            break
        other = sidearm.other_sport_page(final_url)
        if other:
            errors.append(f"{url}: another sport's page ({other})")
            continue
        if not is_current and str(season) in url and str(season) not in final_url:
            # e.g. liuathletics.com/.../roster/2019 quietly redirects to the current roster
            errors.append(f"{url}: redirected to {final_url}")
            continue
        shown = detect_season(html)
        if shown is not None and shown != season:
            errors.append(f"{url}: page shows {shown}")
            continue
        loaded.append(idx)
        if is_current:
            check = "verified" if shown == season else "current"
        else:
            check = "verified" if shown == season else "unverified"
        strategy, players = parse_roster(html)
        if not players:
            errors.append(f"{url}: no players found")
        # A page that shows the right year beats a bigger page that shows no year.
        if (check == "verified", len(players)) > (best[4] == "verified", len(best[1])):
            best = (strategy, players, final_url, idx, check)
        if len(players) >= sidearm.MIN_PLAYERS and check != "unverified":
            break

    if render and len(best[1]) < sidearm.MIN_PLAYERS:
        # Script-built sites (the NJCAA's Ardor app) answer every address with the same empty page,
        # so the first address isn't necessarily the right one. Render the addresses that loaded or
        # hit a bot check, until one has a roster. On app sites the season-in-the-middle addresses
        # (/sports/fball/2024-25/roster) go first; everywhere else the usual order is kept.
        def render_order(i):
            presto = bool(re.search(rf"/{season}-\d\d/roster\b", urls[i]))
            return 0 if i == best[3] else (1 if app_shell and presto else 2)
        # Only addresses that answered with a page or a bot check. An address that redirected away
        # (Florida Tech's go to its home page) or was missing has nothing for a browser to find.
        candidates = [i for i in order if i in loaded or i in blocked]
        # If no address loaded at all (every one a bot check or certificate error), one browser try
        # at the most likely address is enough to learn whether the site lets a browser in.
        tries = sorted(candidates, key=render_order)[:RENDER_TRIES if loaded else 1]
        followed = False
        n = 0
        while n < len(tries):
            idx = tries[n]
            n += 1
            url = urls[idx]
            if sidearm.other_sport_page(url):
                continue
            try:
                html = fetcher.render(url)
            except Exception as exc:
                errors.append(f"render {url}: {exc}")
                if "gave up" in str(exc):   # timed out: the site's other addresses would too
                    break
                continue
            shown = detect_season(html)
            if shown is not None and shown != season:
                errors.append(f"render {url}: page shows {shown}")
                continue
            strategy, players = parse_roster(html)
            if not players:
                errors.append(f"render {url}: no players found")
                # The page loaded but isn't the roster (Mars Hill's Sidearm address is "Not Found").
                # Its menu still links to the site's own roster address: follow that once, for
                # this season. (Flag football, "flagfball", is a different sport.)
                link = None if followed else roster_link_re().search(html)
                if link:
                    followed = True
                    # Built on the page's own address (its canonical link) when it gives one: Northwood's
                    # gonorthwood.com sends everyone to the www. home page, so only www. works.
                    canon = re.search(r'<link[^>]+rel="canonical"[^>]+href="(https?://[^"]+)"', html)
                    base = canon.group(1) if canon else url
                    nxt = urljoin(base, f"/sports/{link.group(1)}/{presto_season(season)}/roster")
                    if nxt not in urls:
                        urls.append(nxt)
                    if urls.index(nxt) not in tries[:n]:
                        tries.insert(n, urls.index(nxt))
                continue
            if len(players) > len(best[1]):
                check = "verified" if shown == season else ("current" if is_current else "unverified")
                best = (f"rendered:{strategy}", players, url, idx, check)
            if len(players) >= sidearm.MIN_PLAYERS:
                break

    strategy, players, url, win_idx, check = best
    if save_dir and win_idx is not None:  # --save-pages: keep a copy of the page these players came from
        page = fetcher._cache_path(urls[win_idx], rendered=strategy.startswith("rendered:"))
        if Fetcher.is_cached(page):
            safe = re.sub(r"[^A-Za-z0-9]+", "_", school["school"]).strip("_")
            (save_dir / f"{safe}_{season}.html").write_text(Fetcher.read_cached(page), encoding="utf-8")
    if bios and url:
        filled = fill_from_bios(players, url, fetcher, errors)
        if filled:
            strategy += "+bios"
    rows = []
    for p in players:
        home = parse_hometown(p["hometown"])
        row = {
            "season": season, "division": division, "current_conference": school.get("conference", ""),
            "school": school["school"], **{f: p.get(f, "") for f in FIELDS},
            "class_norm": normalize_class(p.get("class_year", "")),
            "home_city": home["city"], "home_state": home["state"], "home_country": home["country"],
            "strategy": strategy, "roster_url": url,
        }
        if row["bio_url"] and url:
            row["bio_url"] = urljoin(url, row["bio_url"])
        rows.append(row)

    with_home = sum(1 for r in rows if r["hometown"])
    report.update(strategy=strategy, players=len(rows), with_hometown=with_home, url=url,
                  season_check=check, error="; ".join(errors if len(errors) <= 8 else errors[:3] + ["..."] + errors[-5:]))
    if sidearm.normal_size(len(rows)) and with_home >= 0.5 * len(rows):
        report["status"] = "ok"
    elif rows:
        report["status"] = "partial"
    return rows, report, (win_idx if not is_current else None)


def scrape_school_all(school: dict, seasons: list[int], fetcher: Fetcher, history: dict,
                      render: bool, skip: set[tuple[str, int]],
                      reference: tuple[int, set[str]] | None = None,
                      save_dir: Path | None = None, bios: bool = False) -> list[tuple[int, list[dict], dict]]:
    """All seasons for one school, newest first, reusing the URL pattern that worked.

    ``reference`` is (season, roster names) from an already-saved newer season, used to catch
    archive pages that silently show the current roster. After SCHOOL_MINUTES the school stops starting
    new seasons: those are reported failed, and the next --retry-failed picks them up."""
    import time
    deadline = time.monotonic() + SCHOOL_MINUTES * 60
    results = []
    prefer: int | None = None
    newest_season, newest_names = reference if reference else (None, None)
    for season in sorted(seasons, reverse=True):
        if (school["school"], season) in skip:
            continue
        division = division_for(school, season, history)
        if division.lower() == "none":
            results.append((season, [], {"season": season, "school": school["school"], "division": "",
                                         "current_conference": school.get("conference", ""),
                                         "status": "no_program", "players": 0, "with_hometown": 0}))
            continue
        note = (school.get("note") or school.get("notes") or "").strip()
        if note.lower().startswith("left out"):
            # Kept in the school list and the counts, but never fetched (Indianapolis: its site
            # refuses automated visitors). The note is the reason shown in the report.
            results.append((season, [], {"season": season, "school": school["school"], "division": division,
                                         "current_conference": school.get("conference", ""), "status": "left_out",
                                         "season_check": "", "strategy": "", "players": 0, "with_hometown": 0,
                                         "url": "", "error": note}))
            continue
        wrong = WRONG_SEASONS.get((school["school"], season))
        if wrong is not None:
            # Its only roster page is another season's (config/<sport>/wrong_seasons.csv): not fetched
            results.append((season, [], {"season": season, "school": school["school"], "division": division,
                                         "current_conference": school.get("conference", ""), "status": "left_out",
                                         "season_check": "", "strategy": "", "players": 0, "with_hometown": 0,
                                         "url": "", "error": "left out: " + (wrong or "its roster page is another season's")}))
            continue
        if time.monotonic() > deadline:
            results.append((season, [], {"season": season, "school": school["school"], "division": division,
                                         "current_conference": school.get("conference", ""), "status": "failed",
                                         "season_check": "", "strategy": "", "players": 0, "with_hometown": 0,
                                         "url": "", "error": f"timed out: this school took over {SCHOOL_MINUTES:g} minutes"}))
            continue
        rows, report, idx = scrape_school_season(school, fetcher, season, division, render, prefer, save_dir, bios)
        names = {r["name"].lower() for r in rows}
        # A page with no visible year that is ~the same roster as a newer season is almost
        # certainly the site falling back to its current roster.
        if (report["season_check"] == "unverified" and newest_names and newest_season > season
                and names and len(names & newest_names) / len(names) > 0.8):
            report.update(status="failed", players=0, with_hometown=0,
                          error=f"page looks like the {newest_season} roster; " + report.get("error", ""))
            rows = []
        elif (report["season_check"] == "current" and newest_names and newest_season == season - 1
              and names and len(names & newest_names) / len(names) >= 0.9):
            # The main page with no year on it still shows last season's team (spring sports in the autumn,
            # before next spring's roster goes up): not this season's roster yet. A new season's roster keeps
            # about three in four of its players, not nine in ten.
            report.update(status="failed", players=0, with_hometown=0,
                          error=f"the main roster page still shows the {newest_season} roster (not posted yet); "
                          + report.get("error", ""))
            rows = []
        elif rows and (newest_season is None or season > newest_season):
            newest_names, newest_season = names, season
        if idx is not None and report["status"] == "ok":
            prefer = idx
        results.append((season, rows, report))
    return results


# ---------------------------------------------------------------------------
# attempts.csv: school-seasons that keep failing, so later runs stop trying them

ATTEMPTS_FILE = "attempts.csv"
ATTEMPT_FIELDS = ["school", "season", "tries", "status", "reason", "last_try"]
GIVE_UP_AFTER = 3     # tries (failed or partial) before a school-season is skipped (--give-up-after)


def counts_as_try(report: dict) -> bool:
    """A failed or partial result that says something about the site. Not: never started because the
    school ran out of time, left out on purpose, or no program that season."""
    if report.get("status") not in ("failed", "partial"):
        return False
    return not (report.get("error") or "").startswith("timed out: this school took over")


def read_attempts(rosters_dir: Path) -> dict[tuple[str, int], dict]:
    """(school, season) -> its row in attempts.csv. The first time (no file yet), it starts from the saved
    scrape reports: each failed or partial school-season counts as 1 try, so the next pipeline run (a quick
    pass and the browser retry) is its last chance."""
    path = Path(rosters_dir) / ATTEMPTS_FILE
    out: dict[tuple[str, int], dict] = {}
    if path.exists():
        for r in read_csv(path):
            try:
                out[(r["school"], int(r["season"]))] = {**r, "tries": int(r.get("tries") or 0)}
            except (KeyError, ValueError):
                continue
        return out
    for rp in sorted(Path(rosters_dir).glob("scrape_report_*.csv")):
        for r in read_csv(rp):
            if counts_as_try(r) and not is_left_out(r) and str(r.get("season", "")).isdigit():
                out[(r["school"], int(r["season"]))] = {
                    "school": r["school"], "season": int(r["season"]), "tries": 1, "status": r["status"],
                    "reason": plain_reason(r), "last_try": "before Oct 27"}
    return out


def write_attempts(rosters_dir: Path, attempts: dict[tuple[str, int], dict]) -> None:
    rows = sorted(attempts.values(), key=lambda r: (r["school"], int(r["season"])))
    write_csv(Path(rosters_dir) / ATTEMPTS_FILE, ATTEMPT_FIELDS, rows)


def update_attempts(attempts: dict[tuple[str, int], dict], results: dict[tuple[str, int], dict]) -> None:
    """Count this run's results in: an ok season is forgotten, a failed or partial one gets one more try."""
    from datetime import date
    today = date.today().isoformat()
    for key, report in results.items():
        if report.get("status") == "ok":
            attempts.pop(key, None)
        elif counts_as_try(report):
            row = attempts.get(key) or {"school": key[0], "season": key[1], "tries": 0}
            row.update(tries=int(row.get("tries") or 0) + 1, status=report["status"],
                       reason=plain_reason(report), last_try=today)
            attempts[key] = row


def given_up(attempts: dict[tuple[str, int], dict], limit: int) -> set[tuple[str, int]]:
    return {k for k, r in attempts.items() if limit > 0 and int(r.get("tries") or 0) >= limit}


# ---------------------------------------------------------------------------
# worker processes: one school at a time in each, so page parsing (most of the time once the pages are
# downloaded) runs on every core. With threads in one process only one page could be parsed at a time:
# 16 big schools waiting their turn all ran out of their school time together.

_WORKER: dict = {}


def _init_worker(sport_name: str, schools_csv: str, history_csv: str, school_minutes: float,
                 fetch_args: dict, verbose: bool) -> None:
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)    # Ctrl-C is the main process's to handle
    global SCHOOL_MINUTES
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if not verbose:
        warnings.simplefilter("ignore")
        logging.getLogger().setLevel(logging.ERROR)
        log.setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    sidearm.configure(load_sport(sport_name))
    WRONG_SEASONS.clear()
    WRONG_SEASONS.update(load_sport(sport_name).wrong_seasons())
    SEASON_PAGES.clear()
    SEASON_PAGES.update(load_sport(sport_name).season_pages())
    load_known_colleges(d1_schools(Path(schools_csv)))
    SCHOOL_MINUTES = school_minutes
    _WORKER["history"] = load_division_history(Path(history_csv))
    _WORKER["fetcher"] = Fetcher(**fetch_args)


def _scrape_in_worker(school, seasons, render, skip, reference, save_dir, bios):
    return scrape_school_all(school, seasons, _WORKER["fetcher"], _WORKER["history"], render, skip,
                             reference, save_dir, bios)


# ---------------------------------------------------------------------------
# problem list: failed and partial schools in a few words, without the web addresses

_URL_PREFIX = re.compile(r"^(render |bio )?https?://\S+?:\s*")

# Error names (from a download) and browser messages -> a few plain words.
_PLAIN_ERRORS = {"HTTP 202": "bot check", "HTTP 403": "refused", "HTTP 404": "not found",
                 "SSLError": "certificate error", "TimeoutError": "too slow", "ReadTimeout": "too slow",
                 "ConnectTimeout": "too slow", "Timeout": "too slow", "ConnectionError": "no connection", "ProxyError": "no connection",
                 "ChunkedEncodingError": "cut off", "ContentDecodingError": "cut off",
                 "TooManyRedirects": "redirect loop"}
_BROWSER_ERRORS = [   # (pattern in the browser's message, plain words), first match wins
    (re.compile(r"gave up|timeout|timed out|exceeded", re.I), "too slow"),
    (re.compile(r"bot check", re.I), "bot check not passed"),
    (re.compile(r"ERR_NAME_NOT_RESOLVED", re.I), "no such site"),
    (re.compile(r"ERR_CONNECTION|ERR_ADDRESS|ERR_NETWORK", re.I), "no connection"),
    (re.compile(r"ERR_CERT|SSL", re.I), "certificate error"),
    (re.compile(r"Playwright not installed", re.I), "Playwright not installed"),
]


def short_reason(error: str) -> str:
    """'https://x/roster/2018: redirected to https://x/roster; https://x/...: HTTP 404; ...'
    -> 'redirected ×4, not found ×6'. Browser results are marked 'browser:'."""
    counts: dict[str, int] = {}
    for part in (error or "").split("; "):
        part = part.strip()
        if not part or part == "...":
            continue
        browser = part.startswith("render ")
        msg = _URL_PREFIX.sub("", part)
        msg = re.sub(r"redirected to \S+", "redirected", msg)
        msg = re.sub(r"\S+://\S+", "", msg).strip(" :")
        msg = _PLAIN_ERRORS.get(msg, msg)
        if browser and msg not in ("no players found",) and not msg.startswith("page shows"):
            # Playwright's own text ("page.goto: Timeout 15000ms exceeded. Call log: ...") is long and
            # different every time; keep only what it means.
            msg = next((plain for pat, plain in _BROWSER_ERRORS if pat.search(msg)), msg[:60])
        if browser:
            msg = "browser: " + msg
        counts[msg] = counts.get(msg, 0) + 1
    return ", ".join(f"{m} ×{n}" if n > 1 else m for m, n in counts.items())


def is_left_out(report: dict) -> bool:
    """A school-season skipped on purpose (a "left out" note). Reports written before Oct 27 call these
    "failed", with the note as the error."""
    return report.get("status") == "left_out" or (
        report.get("status") == "failed" and (report.get("error") or "").lower().startswith("left out"))


def print_problems(reports: list[dict], this_run: bool = False) -> None:
    """The failed and partial school-seasons in `reports`. this_run: the reports are only the schools this
    run scraped, so "none" is said about them, not about the whole sport."""
    left_out = sorted({r["school"] for r in reports if is_left_out(r)})
    bad = [r for r in reports if r.get("status") in ("failed", "partial") and not is_left_out(r)]
    if left_out:
        log.info("Left out on purpose (never contacted; see their notes): %d schools", len(left_out))
    if not bad:
        log.info("None of the schools scraped in this run failed or came back partial (the table above "
                 "counts every school; MISSING_ROSTERS.md lists them)." if this_run else "No failed or partial schools.")
        return
    log.info("Failed or partial (%d):", len(bad))
    for r in sorted(bad, key=lambda r: (str(r["season"]), r.get("division", ""), r["school"])):
        players = f"{r.get('players') or 0} players, {r.get('with_hometown') or 0} with hometown" \
            if r["status"] == "partial" else "no roster"
        log.info("  %s %-5s %-26s %-8s %s  (%s)", r["season"], r.get("division", ""), r["school"][:26],
                 r["status"], players, short_reason(r.get("error", "")) or "no details")


# ---------------------------------------------------------------------------
# MISSING_ROSTERS.md: the failed and partial schools of a sport, by division, with the reason in words

# Football's order; write_missing_rosters() is given the sport's own (d1_divisions, then other_divisions).
DIVISION_ORDER = ["FBS", "FCS", "D2", "D3", "NAIA", "JUCO"]
MISSING_FILE = "MISSING_ROSTERS.md"


def _school_notes(schools_csv: Path) -> dict[str, str]:
    """school -> its notes from the schools file (every row of the school, joined)."""
    notes: dict[str, list[str]] = {}
    for r in read_csv(schools_csv):
        n = (r.get("note") or "").strip()
        if n and n not in notes.setdefault(r["school"], []):
            notes[r["school"]].append(n)
    return {s: "; ".join(n) for s, n in notes.items()}


def _seasons_text(seasons: list[int]) -> str:
    return ", ".join(str(s) for s in sorted(seasons))


def plain_reason(report: dict) -> str:
    """One sentence on why a school-season failed or is partial, from its report row."""
    err = report.get("error", "") or ""
    short = short_reason(err)
    if report.get("status") == "partial":
        n = int(report.get("players") or 0)
        if n and n < sidearm.MIN_PLAYERS:
            return f"only {n} players, fewer than a normal roster for this sport (at least {sidearm.MIN_PLAYERS}): a page cut off?"
        if n and sidearm.MAX_PLAYERS and n > sidearm.MAX_PLAYERS:
            return (f"{n} players, more than a normal roster for this sport (at most {sidearm.MAX_PLAYERS}): "
                    "a roster with JV or extra players on it, or the page was read wrong "
                    "(compare with the page in a browser)")
        m = re.search(r"bios: hometowns from (\d+) of (\d+) player pages", err)
        if m:
            return (f"the roster page has no hometowns; the players' own pages gave {m.group(1)} of {m.group(2)}, "
                    "the rest don't list one")
        if "bios: the first" in err:
            return "neither the roster page nor the players' own pages list most hometowns"
        return "the site lists hometowns for only some players"
    if is_left_out(report):
        return err[0].upper() + err[1:] if err else "Left out"
    if err.startswith("timed out"):
        return "skipped: the school's other seasons took too long (--retry-failed tries it again)"
    if "another sport's page" in err and not re.search(r"no players found|bot check", short):
        return "the only roster pages found were another sport's (the site may not list this team's roster)"
    if "not posted yet" in err:
        return "this season's roster isn't up yet: the main roster page still shows last season's team"
    if "page looks like the" in err:
        return "the archive page shows a newer season's roster, so there's no roster for this season"
    if "bot check not passed" in err:
        return "the site's bot check turned away the browser too"
    if "certificate error" in short and not re.search(r"redirected|not found|bot check", short):
        return "the site's security certificate is rejected (it may be refusing automated visitors)"
    if "too slow" in short or "gave up" in short:
        return "the site was too slow to answer"
    if "no connection" in short and not re.search(r"redirected|not found|page shows", short):
        return "couldn't connect to the site: the address in the schools file may be wrong or dead"
    if "bot check" in short and "browser: no players found" in short:
        return "the site blocks plain downloads, and the pages the browser opened had no roster"
    if re.search(r"redirected|page shows", short):
        return "the site has no roster for this season: its old-season addresses lead to a newer roster"
    if "not found" in short:
        return "no roster page at any of the usual addresses: the site may have moved or use another layout"
    if "no players found" in short:
        return "the roster page opened but no players could be read from it"
    return short or "no details"


def write_missing_rosters(report_dir: Path, schools_csv: Path, sport_label: str, no_site: list[str],
                          out_dir: Path | None = None, division_order: list[str] | None = None,
                          division_labels: dict[str, str] | None = None,
                          gave_up: set[tuple[str, int]] | None = None) -> Path:
    """Write MISSING_ROSTERS.md from every scrape report in report_dir, into out_dir (the sport's
    rosters/<sport>/ folder, so it's always in the same place, even for a test run with --out).

    For each division: schools with a failed season (no roster saved) and schools with a partial one
    (saved, but most players without a hometown), each with its seasons and why. The reason is the
    school's note in the schools file when it has one (a person checked it), else the scraper's own
    short reason. Then the colleges skipped because they have no athletics site."""
    order = list(division_order or DIVISION_ORDER)
    labels = division_labels or {}
    notes = _school_notes(schools_csv)
    school_rows = read_csv(schools_csv)
    division_of = {r["school"]: r["division"] for r in school_rows if r["division"] in order}
    # Schools whose note (on any of their rows) says to leave them out: the scraper never contacts them
    left_out_now = {r["school"] for r in school_rows if (r.get("note") or "").strip().lower().startswith("left out")}
    reports = []
    for path in sorted(report_dir.glob("scrape_report_*.csv")):
        reports += read_csv(path)
    seasons_checked = sorted({int(r["season"]) for r in reports if str(r.get("season", "")).isdigit()})
    # (division, status) -> school -> [(season, report)]
    groups: dict[tuple[str, str], dict[str, list[tuple[int, dict]]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for r in reports:
        div = r.get("division") or division_of.get(r["school"], "")
        if r.get("status") == "no_program" or r["school"] not in division_of:
            continue   # no program that season, or a school no longer in the schools file (renamed or removed)
        status = r["status"]
        if is_left_out(r) or (status == "failed" and r["school"] in left_out_now):
            status = "left_out"      # an older report's "failed", or a school left out since that run
        c = counts.setdefault(div, {"ok": 0, "partial": 0, "failed": 0, "left_out": 0})
        c[status] = c.get(status, 0) + 1
        if status in ("failed", "partial", "left_out"):
            groups.setdefault((div, status), {}).setdefault(r["school"], []).append((int(r["season"]), r))

    from datetime import date
    out_dir = Path(out_dir or report_dir)
    where = ("this folder" if out_dir.resolve() == Path(report_dir).resolve()
             else f"`{report_dir}` (a test run with --out)")
    out = [f"# {sport_label} rosters that are missing or incomplete", "",
           f"Written by `scripts/scrape_rosters.py` on {date.today().isoformat()} from the scrape reports in "
           f"{where} (seasons {_seasons_text(seasons_checked) or 'none yet'}). It is rewritten after every run, so "
           "don't edit it here: to explain a school, add a `note` to its row in the schools file, and that note "
           "becomes its reason below.", "",
           "- **Failed**: no roster was saved for that season.",
           "- **Partial**: the roster was saved, but most players have no hometown (so they get no dot on the map), "
           "or it has fewer or more players than a normal roster for this sport (min_players to max_players in "
           "its settings), which usually means a page cut off or the wrong page.",
           "- **Left out**: never contacted, on purpose: the school's note in the schools file starts with "
           "\"left out\" (most refuse automated visitors). They're listed once, at the end.",
           "- Seasons before a program started or after it ended aren't listed: they're not failures.",
           "- **Not tried any more**: failed or partial on several runs in a row (`attempts.csv` in this folder "
           "counts the tries), so runs skip it. `--retry-given-up` tries those again; deleting a row from "
           "attempts.csv does it for one school-season.", "",
           "| division | ok | partial | failed | left out |", "|---|---|---|---|---|"]
    divs = [d for d in order if d in counts] + sorted(d for d in counts if d not in order)
    for d in divs:
        c = counts[d]
        out.append(f"| {d or '?'} | {c.get('ok', 0)} | {c.get('partial', 0)} | {c.get('failed', 0)} "
                   f"| {c.get('left_out', 0)} |")
    out.append("")
    for d in divs:
        failed, partial = groups.get((d, "failed"), {}), groups.get((d, "partial"), {})
        if not (failed or partial):
            continue
        out += [f"## {labels.get(d, d) or 'Unknown division'}", ""]
        for status, title in (("failed", "Failed"), ("partial", "Partial")):
            schools_here = groups.get((d, status), {})
            if not schools_here:
                continue
            out += [f"### {title}", ""]
            for school in sorted(schools_here):
                items = sorted(schools_here[school], key=lambda x: x[0])
                reasons = {s: plain_reason(r) for s, r in items}
                if status == "partial":
                    sizes = "; ".join(f"{s}: {r.get('players') or 0} players, {r.get('with_hometown') or 0} "
                                      "with a hometown" for s, r in items)
                    head = f"- **{school}** ({sizes})"
                else:
                    head = f"- **{school}** ({_seasons_text(list(reasons))})"
                if len(set(reasons.values())) == 1:
                    line = f"{head}: {next(iter(reasons.values()))}."
                else:
                    line = f"{head}: " + "; ".join(f"{s}: {why}" for s, why in reasons.items()) + "."
                note = notes.get(school, "")
                if note and note.lower() not in line.lower():
                    line += f" Note: {note}."
                stopped = [s for s, _ in items if (school, s) in (gave_up or set())]
                if stopped:
                    line += (" Not tried any more" + ("" if len(stopped) == len(items) else f" ({_seasons_text(stopped)})")
                             + ": it failed every time (attempts.csv; --retry-given-up tries again).")
                out.append(line)
            out.append("")
    left = [(d, school) for d in divs for school in sorted(groups.get((d, "left_out"), {}))]
    if left:
        n_left = len({school for _, school in left})   # a school that changed division is listed under both
        out += [f"## Left out on purpose ({n_left} school{'' if n_left == 1 else 's'})", "",
                "Never contacted by the scraper, because of the note in the schools file (to try one again, change "
                "its note so it doesn't start with \"left out\"), or, for single seasons, because the season is in "
                "`config/<sport>/wrong_seasons.csv` (its only roster page shows another season's roster).", ""]
        for d, school in left:
            items = groups[(d, "left_out")][school]
            if school in left_out_now:
                reason = notes.get(school) or plain_reason(items[0][1])
                out.append(f"- **{school}** ({labels.get(d, d) or '?'}): {reason}")
            else:      # single seasons, from config/<sport>/wrong_seasons.csv
                why = "; ".join(f"{y}: {plain_reason(r)}" for y, r in sorted(items, key=lambda x: x[0]))
                out.append(f"- **{school}** ({labels.get(d, d) or '?'}, seasons {_seasons_text([y for y, _ in items])}): {why}")
        out.append("")
    if no_site:
        # Current = some row of the school has a 2026 conference and no last season; the rest closed
        # or dropped football. Both are still used to sort transfers by level.
        rows_of: dict[str, list[dict]] = {}
        for r in read_csv(schools_csv):
            rows_of.setdefault(r["school"], []).append(r)
        def level_only(s):    # listed only so transfers from it get a level (no team in this sport)
            text = " ".join((r.get("note") or "").lower() for r in rows_of.get(s, []))
            return bool(re.search(r"level only|listed only so transfers|no (men's |women's )?[a-z' ]*team in the", text))
        levels_only = [s for s in no_site if level_only(s)]
        no_site = [s for s in no_site if s not in levels_only]
        current = [s for s in no_site if any((r.get("conference") or r.get("current_conference")) and not r.get("last_season")
                                             for r in rows_of.get(s, []))]
        closed = [s for s in no_site if s not in current]
        out += ["## Skipped: no athletics site in the schools file", ""]
        for title, names, blurb in (
                ("Current programs", current, "These play now, but no roster site is known: worth finding."),
                ("Closed or dropped programs", closed, "No team now, so nothing to scrape.")):
            if not names:
                continue
            out += [f"### {title} ({len(names)})", "", blurb, ""]
            for school in names:
                note = notes.get(school)
                out.append(f"- {school} ({division_of.get(school, '?')})" + (f": {note}" if note else ""))
            out.append("")
        if levels_only:
            out += [f"Not listed: {len(levels_only)} colleges with no team in this sport, in the schools file only so "
                    "transfers from them get a level (their note says so).", ""]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MISSING_FILE
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# outputs

def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def saved_reports(rows: list[dict]) -> dict[str, dict]:
    """school -> a report row worked out from one season's saved roster rows, for runs without
    scrape reports: 'ok' with a normal number of players for the sport and most of them with a hometown, the same rule
    scrape_school_season() uses, else 'partial'. A school with no rows isn't listed (failed, or
    no program that season)."""
    by_school: dict[str, list[dict]] = {}
    for r in rows:
        by_school.setdefault(r["school"], []).append(r)
    out = {}
    for school, grp in by_school.items():
        first = grp[0]
        with_home = sum(1 for r in grp if r.get("hometown"))
        ok = sidearm.normal_size(len(grp)) and with_home >= 0.5 * len(grp)
        out[school] = {"season": first.get("season", ""), "school": school, "division": first.get("division", ""),
                       "current_conference": first.get("current_conference", ""),
                       "status": "ok" if ok else "partial", "season_check": "", "strategy": first.get("strategy", ""),
                       "players": len(grp), "with_hometown": with_home, "url": first.get("roster_url", ""),
                       "error": ""}
    return out


def restore_season_files(out_dir: Path) -> None:
    """If the per-season files are gone but rosters_all_seasons.csv is there, split it back into
    rosters_<season>.csv, so a run never rebuilds the combined files from nothing."""
    combined = out_dir / "rosters_all_seasons.csv"
    if season_files(out_dir) or not combined.exists():
        return
    by_season: dict[int, list[dict]] = {}
    for r in read_csv(combined):
        by_season.setdefault(int(r["season"]), []).append(r)
    for season, rows in by_season.items():
        write_csv(out_dir / f"rosters_{season}.csv", OUT_FIELDS, rows)
    log.info("Rebuilt %d season files from %s", len(by_season), combined.name)


def clean_row(r: dict) -> dict:
    """Clean one saved roster row with the current rules, so parser fixes (names, hometowns, high school
    vs. previous school) reach seasons scraped earlier too."""
    r["name"] = clean_name(r.get("name", ""))
    # A roster label saved with the hometown ("Hometown/Prev. School: Wilson, NC / Beddingfield"):
    # keep the town, and move the school to the high school field when that's empty (sort_schools
    # below moves it on to previous_school if it's a college).
    if not_a_place(r.get("hometown", "")):     # bats/throws, a height or "Manager" read as the hometown
        r["hometown"] = ""
    r["position"] = strip_bats_throws(r.get("position", ""))   # "OF R/R" saved before Oct 27
    town, school = split_labeled_hometown(r.get("hometown", ""))
    if town != clean(r.get("hometown", "")) or school:
        r["hometown"] = town
        if school and not r.get("high_school") and not r.get("previous_school"):
            r["high_school"] = school
    home = parse_hometown(r.get("hometown", ""))
    r["home_city"], r["home_state"], r["home_country"] = home["city"], home["state"], home["country"]
    r["class_norm"] = normalize_class(r.get("class_year", "")) or r.get("class_norm", "")
    return sort_schools(r)


def from_other_sport(row: dict) -> bool:
    """Saved from another sport's page (a lacrosse season taken from the school's football roster), or a
    school-season listed in config/<sport>/wrong_seasons.csv (another season's roster)."""
    if (WRONG_SEASONS or SEASON_PAGES) and str(row.get("season", "")).isdigit():
        key = (row.get("school", ""), int(row["season"]))
        if key in WRONG_SEASONS:
            return True
        page = SEASON_PAGES.get(key)
        if page and row.get("roster_url", "").rstrip("/") != page.rstrip("/"):
            return True          # saved from another page than the one listed for this season
    return bool(sidearm.other_sport_page(row.get("roster_url", "")))


def clean_rows(rows: list[dict]) -> list[dict]:
    """Drop coaches and staff and rows saved from another sport's page, and clean every remaining row."""
    return [clean_row(r) for r in rows if not is_staff(r) and not from_other_sport(r)]


def write_combined(out_dir: Path, combined_files: bool = False) -> tuple[list[int], list[dict], list[dict]]:
    """Clean every saved season file in place. With combined_files (--combined), also write
    rosters_all_seasons.csv and players_unique.csv from them, for opening in a spreadsheet; the later
    steps read the season files themselves. Every roster file holds only the cleaned version."""
    # Combined outputs cover every season saved so far, not just this run.
    combined = []
    all_saved = []
    n_before = 0
    for season, path in season_files(out_dir).items():
        rows = read_csv(path)
        n_before += len(rows)
        rows = clean_rows(rows)
        write_csv(path, OUT_FIELDS, rows)
        all_saved.append(season)
        combined.extend(rows)
    if n_before != len(combined):
        log.info("Dropped %d rows from the saved rosters: coaches and staff, or players from another sport's "
                 "page", n_before - len(combined))
    unique = build_unique(combined)
    if combined_files:
        write_csv(out_dir / "rosters_all_seasons.csv", OUT_FIELDS, combined)
        write_csv(out_dir / "players_unique.csv", UNIQUE_FIELDS, unique)
    n_prev = sum(1 for r in unique if r["previous_school"])
    log.info("Saved seasons %s: %d player-season rows, %d unique players (%d with a previous school)%s",
             ", ".join(map(str, all_saved)), len(combined), len(unique), n_prev,
             f" -> rosters_all_seasons.csv and players_unique.csv in {out_dir}" if combined_files else "")
    return all_saved, combined, unique


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    global SCHOOL_MINUTES
    ap = build_parser()
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    if args.problems:                      # only reads the reports (and rewrites MISSING_ROSTERS.md)
        return run(ap, args, sport)
    with sport_lock(sport, "scrape_rosters.py"):
        return run(ap, args, sport)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=SCRAPE_ROSTERS_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    ap.add_argument("--schools", type=Path, help="default: config/<sport>/schools.csv")
    ap.add_argument("--division-history", type=Path, help="default: config/<sport>/schools.csv (its rows with a season range)")
    ap.add_argument("--seasons", help="e.g. 2016-2019,2021-2026 (default: current season)")
    ap.add_argument("--season", type=int, help="single season (same as --seasons N)")
    ap.add_argument("--division", default="all",
                    help="only schools in this current division, as the sport's settings name it "
                         "(football: FBS, FCS, D2, D3, NAIA, JUCO; lacrosse-mens: D1, D2, ...)")
    ap.add_argument("--conference", help="only this current conference (as in schools.csv)")
    ap.add_argument("--only", help="comma-separated school names")
    ap.add_argument("--out", type=Path, help="where the rosters go (default: rosters/<sport>/)")
    ap.add_argument("--cache", default=ROOT / ".cache" / "html", type=Path)
    ap.add_argument("--workers", type=int, default=6, help="schools scraped in parallel (different sites)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests to the same site")
    ap.add_argument("--school-minutes", type=float, default=SCHOOL_MINUTES,
                    help=f"stop a school after this many minutes; its other seasons are left for --retry-failed (default {SCHOOL_MINUTES:g})")
    ap.add_argument("--timeout", type=int, default=15, help="seconds to wait for one page before giving up (default 15)")
    ap.add_argument("--refresh", action="store_true", help="ignore cached HTML and re-download")
    ap.add_argument("--render", action="store_true", help="headless Chromium for pages the fast path can't parse")
    ap.add_argument("--bios", action="store_true",
                    help="for rosters with players but mostly no hometowns, read each player's own page (slow: one request per player)")
    ap.add_argument("--save-pages", type=Path, metavar="DIR",
                    help="also copy each roster page used into DIR as <school>_<season>.html (for checking by hand)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="skip school-seasons already saved with enough players and hometowns ('ok')")
    ap.add_argument("--give-up-after", type=int, default=GIVE_UP_AFTER, metavar="N",
                    help=f"skip school-seasons that came back failed or partial N times (attempts.csv; default "
                         f"{GIVE_UP_AFTER}; 0: never give up). Schools named with --only are always tried")
    ap.add_argument("--retry-given-up", action="store_true",
                    help="try the given-up school-seasons again this run (their tries keep counting)")
    ap.add_argument("--forget-misses", action="store_true",
                    help="ask again for past-season addresses that answered 'not found' before (normally remembered "
                         f"for {core.MISS_DAYS} days)")
    ap.add_argument("--threads", action="store_true",
                    help="run the schools as threads in one process, like before Oct 27 (slower: one page is parsed "
                         "at a time); the default is one process per worker")
    ap.add_argument("--report", action="store_true",
                    help="also write scrape_report_<season>.csv (per school: status, URL, errors) and MISSING_ROSTERS.md")
    ap.add_argument("--recombine", action="store_true",
                    help="don't download anything: re-clean every saved season file (and, with --combined, rewrite the combined files)")
    ap.add_argument("--combined", action="store_true",
                    help="also write rosters_all_seasons.csv and players_unique.csv (every season in one file, for a spreadsheet); "
                         "the later steps don't need them")
    ap.add_argument("--problems", action="store_true",
                    help="don't scrape: list the failed and partial schools in the saved reports "
                         "(for --seasons, and --division / --only if given; needs reports from a --report run)")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def run(ap: argparse.ArgumentParser, args, sport) -> int:
    global SCHOOL_MINUTES
    sidearm.configure(sport)
    WRONG_SEASONS.clear()
    WRONG_SEASONS.update(sport.wrong_seasons())
    SEASON_PAGES.clear()
    SEASON_PAGES.update(sport.season_pages())
    divisions = list(sport.d1_divisions) + [d for d in sport.other_divisions if d not in sport.d1_divisions]
    args.division = args.division.upper() if args.division.lower() != "all" else "all"
    if args.division != "all" and args.division not in divisions:
        ap.error(f"--division {args.division}: {args.sport} has {', '.join(divisions)} (or all)")
    args.schools = args.schools or sport.schools_csv
    args.division_history = args.division_history or sport.division_history_csv
    args.out = args.out or sport.rosters_dir

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    if not args.verbose:
        # Only the scraper's own lines on screen: no library warnings (BeautifulSoup's parser notices,
        # urllib3's "connection pool is full", certificate warnings, ...). -v shows everything.
        warnings.simplefilter("ignore")
        logging.getLogger().setLevel(logging.ERROR)
        log.setLevel(logging.INFO)

    seasons = parse_seasons(args.seasons) if args.seasons else [args.season or current_season()]
    season_dir = report_dir = args.out
    season_dir.mkdir(parents=True, exist_ok=True)
    restore_season_files(season_dir)
    all_schools = load_schools(args.schools)
    history = load_division_history(args.division_history)
    load_known_colleges(d1_schools(args.schools))   # D1 names only: smaller colleges share names with high schools
    no_site = sorted({r["school"] for r in load_all_colleges(args.schools) if r["division"].strip() in SCRAPED}
                     - {s["school"] for s in all_schools})
    if no_site:   # one line; the names only with -v
        log.info("%d colleges have no domain or roster_url in %s yet, so they're skipped%s",
                 len(no_site), args.schools.name, " (-v lists them)" if not args.verbose else "")
        log.debug("Skipped (closed programs, or sites still to find): %s", ", ".join(no_site))
    def write_missing(gave_up: set | None = None) -> None:
        # Only with --report. Always in rosters/<sport>/, even when --out sends the rosters somewhere else
        if not args.report:
            return
        if gave_up is None:
            gave_up = given_up(read_attempts(sport.rosters_dir), args.give_up_after)
        path = write_missing_rosters(report_dir, args.schools, getattr(sport, "label", args.sport), no_site,
                                     out_dir=sport.rosters_dir, division_order=divisions,
                                     division_labels={d: sport.division_label(d) for d in divisions},
                                     gave_up=gave_up)
        log.info("Failing and partial schools, with reasons -> %s", path)

    if args.recombine:
        write_combined(season_dir, args.combined)
        write_missing()
        return 0

    schools = list(all_schools)
    if args.division != "all":
        schools = [s for s in schools if s["division"].upper() == args.division]
    if args.conference:
        schools = [s for s in schools if s["conference"].lower() == args.conference.lower()]
    if args.only:
        wanted = {w.strip().lower() for w in args.only.split(",")}
        schools = [s for s in schools if s["school"].lower() in wanted]
    if not schools:
        log.error("No schools selected.")
        return 1
    selected = {s["school"] for s in schools}
    if args.problems:
        if not any((report_dir / f"scrape_report_{season}.csv").exists() for season in seasons):
            log.error("No scrape reports saved for %s in %s. Scrape with --report to keep them.",
                      ", ".join(map(str, seasons)), report_dir)
            return 1
        print_problems([r for season in seasons for r in read_csv(report_dir / f"scrape_report_{season}.csv")
                        if r["school"] in selected])
        write_missing()
        return 0

    # Keep previous results for schools/seasons not being re-scraped in this run.
    kept_rows: dict[int, list[dict]] = {}
    kept_reports: dict[int, dict[str, dict]] = {}
    # Everything saved before this run, for schools a Ctrl-C stops before they finish.
    prev_rows_all: dict[int, list[dict]] = {}
    prev_reports_all: dict[int, dict[str, dict]] = {}
    skip: set[tuple[str, int]] = set()
    attempts = read_attempts(sport.rosters_dir)
    stop = set() if args.retry_given_up or args.only else given_up(attempts, args.give_up_after)
    # The current season is always tried: its roster can go up any day
    stop = {(k, y) for k, y in stop if k in selected and y in seasons and y != current_season()}
    for season in seasons:
        # Rows from another sport's page don't count as saved: those school-seasons are scraped again
        prev_rows_all[season] = [r for r in read_csv(season_dir / f"rosters_{season}.csv") if not from_other_sport(r)]
        # What's done comes from the saved rosters, so --retry-failed works without report files. A saved
        # report (from a --report run) adds the details (errors, season check) for schools it still matches.
        from_rows = saved_reports(prev_rows_all[season])
        old = {r["school"]: r for r in read_csv(report_dir / f"scrape_report_{season}.csv")} if args.report else {}
        prev_reports = {k: (old[k] if k in old and old[k].get("status") == r["status"] else r) for k, r in from_rows.items()}
        # Failed and no-program rows have no roster to come from; keep them from the saved report.
        prev_reports.update({k: r for k, r in old.items()
                             if k not in prev_reports and r.get("status") in ("failed", "no_program", "left_out")})
        done = {k for k, r in prev_reports.items() if r["status"] == "ok"} if args.retry_failed else set()
        # Given up (failed or partial every time): not tried, and whatever was saved for it is kept
        done |= {k for k, y in stop if y == season}
        keep_schools = {k for k in prev_reports if k not in selected} | done
        skip.update((k, season) for k in done)
        prev_reports_all[season] = prev_reports
        kept_reports[season] = {k: r for k, r in prev_reports.items() if k in keep_schools}
        kept_rows[season] = [r for r in prev_rows_all[season] if r["school"] in keep_schools]

    if stop:
        log.info("Not trying %d school-seasons (%d schools) that failed or came back partial %d times already "
                 "(%s; --retry-given-up tries them again)", len(stop), len({k for k, _ in stop}),
                 args.give_up_after, ATTEMPTS_FILE)
    todo = sum(1 for s in schools for y in seasons if (s["school"], y) not in skip)
    log.info("Scraping %d schools x %d seasons (%s) = %d roster pages",
             len(schools), len(seasons), ", ".join(map(str, seasons)), todo)
    # Schools with nothing left to do aren't sent to a worker at all
    schools = [s for s in schools if any((s["school"], y) not in skip for y in seasons)]

    # Newest saved roster per school (from earlier runs) for the fallback check. This includes
    # seasons inside the requested range, so --retry-failed still has the newest roster to
    # compare against when that season is skipped as already done.
    references: dict[str, tuple[int, set[str]]] = {}
    for season, path in sorted(season_files(season_dir).items(), reverse=True):
        for r in read_csv(path):
            if r["school"] not in references or references[r["school"]][0] == season:
                references.setdefault(r["school"], (season, set()))[1].add(r["name"].lower())

    save_dir = args.save_pages.expanduser() if args.save_pages else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    SCHOOL_MINUTES = args.school_minutes
    fetch_args = dict(cache_dir=args.cache, delay=args.delay, refresh=args.refresh, timeout=args.timeout,
                      forget_misses=args.forget_misses)
    new_rows: dict[int, list[dict]] = {y: [] for y in seasons}
    new_reports: dict[int, dict[str, dict]] = {y: {} for y in seasons}
    tried: dict[tuple[str, int], dict] = {}     # this run's own result per school-season, for attempts.csv
    lock = threading.Lock()

    skip_of: dict[str, set] = {}
    for k in skip:
        skip_of.setdefault(k[0], set()).add(k)
    workers = max(1, min(args.workers, len(schools) or 1))
    if args.threads or workers == 1:
        fetcher = Fetcher(**fetch_args)
        pool = ThreadPoolExecutor(max_workers=workers)
        futures = {pool.submit(scrape_school_all, s, seasons, fetcher, history, args.render, skip_of.get(s["school"], set()),
                               references.get(s["school"]), save_dir, args.bios): s
                   for s in schools}
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        # "spawn" on every system (the macOS default): a fresh Python per worker, set up by _init_worker
        pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                                   initializer=_init_worker,
                                   initargs=(sport.name, str(args.schools), str(args.division_history),
                                             args.school_minutes, fetch_args, args.verbose))
        futures = {pool.submit(_scrape_in_worker, s, seasons, args.render, skip_of.get(s["school"], set()),
                               references.get(s["school"]), save_dir, args.bios): s
                   for s in schools}
    finished: set[str] = set()
    interrupted = False
    def finished_in_order():
        # as_completed(), plus a line every minute naming the schools still running, so a slow one is visible
        from concurrent.futures import FIRST_COMPLETED, wait
        # (one line: how many are running and the one running longest, not a list of names)
        import time
        pending, since = set(futures), {}
        while pending:
            done, pending = wait(pending, timeout=60, return_when=FIRST_COMPLETED)
            now = time.monotonic()
            running = [f for f in pending if f.running()]
            for f in running:
                since.setdefault(f, now)
            if not done and running:
                slow = min(running, key=lambda f: since[f])
                log.info("still working on %d school%s; longest: %s (%d min)", len(running), "" if len(running) == 1 else "s",
                         futures[slow]["school"], (now - since[slow]) // 60)
            yield from done

    try:
        for i, fut in enumerate(finished_in_order(), 1):
            school = futures[fut]
            try:
                results = fut.result()
            except Exception as exc:
                log.error("%s crashed: %r", school["school"], exc)
                continue
            with lock:
                summary = []
                for season, rows, report in results:
                    tried[(school["school"], season)] = report
                    # A retry that fails (timed out, site down, bot check) mustn't erase a roster an
                    # earlier run saved: keep the saved one and its report. Not when this run found the
                    # saved roster was really a newer season's ("page looks like the 2026 roster").
                    err = report.get("error", "") or ""
                    if not rows and report.get("status") in ("failed", "left_out") and "page looks like the" not in err:
                        old = [r for r in prev_rows_all[season] if r["school"] == school["school"]]
                        if old:
                            rows = old
                            report = prev_reports_all[season].get(school["school"], report)
                    new_rows[season].extend(rows)
                    new_reports[season][school["school"]] = report
                    if report["status"] != "left_out":
                        summary.append(report["status"])
                finished.add(school["school"])
                # Schools whose seasons were all skipped (--retry-failed and already ok, or left out) print nothing
                if summary:      # "[ 12/1088] Adrian  11 ok, 1 failed" (each season is in the reports)
                    from collections import Counter
                    c = Counter(summary)
                    log.info("[%3d/%d] %-26s %s", i, len(schools), school["school"],
                             ", ".join(f"{n} {k}" for k, n in sorted(c.items(), key=lambda kv: ("ok", "partial").index(kv[0])
                                                                   if kv[0] in ("ok", "partial") else 2)))
        pool.shutdown(wait=True)
    except KeyboardInterrupt:
        # Ctrl-C: save the schools that finished. The ones still running keep what the run before
        # saved for them, and --retry-failed picks them up next time.
        interrupted = True
        pool.shutdown(wait=False, cancel_futures=True)
        for proc in list((getattr(pool, "_processes", None) or {}).values()):
            proc.terminate()      # worker processes (not threads): stop their downloads now
        with lock:
            unfinished = sorted(s["school"] for s in schools if s["school"] not in finished)
            log.warning("Stopped. Saving the %d schools that finished; %d didn't and keep their earlier "
                        "results: %s", len(finished), len(unfinished), ", ".join(unfinished[:10])
                        + (" ..." if len(unfinished) > 10 else ""))
            for season in seasons:
                for name in unfinished:
                    if name in prev_reports_all[season] and name not in kept_reports[season]:
                        kept_reports[season][name] = prev_reports_all[season][name]
                        kept_rows[season] += [r for r in prev_rows_all[season] if r["school"] == name]

    order = {s["school"]: i for i, s in enumerate(all_schools)}
    totals = []
    for season in seasons:
        rows = kept_rows[season] + new_rows[season]
        rows.sort(key=lambda r: (order.get(r["school"], 9999), r["school"]))
        reports = {**kept_reports[season], **new_reports[season]}
        write_csv(season_dir / f"rosters_{season}.csv", OUT_FIELDS, rows)
        if args.report:
            write_csv(report_dir / f"scrape_report_{season}.csv", REPORT_FIELDS,
                      sorted(reports.values(), key=lambda r: order.get(r["school"], 9999)))
        st = ["left_out" if is_left_out(r) else r.get("status") for r in reports.values()]
        totals.append((season, len(rows), st.count("ok"), st.count("partial"), st.count("failed"),
                       st.count("left_out")))

    update_attempts(attempts, tried)
    write_attempts(sport.rosters_dir, attempts)
    gave_up_now = given_up(attempts, args.give_up_after)
    all_saved, combined, unique = write_combined(season_dir, args.combined)
    write_missing(gave_up_now)
    log.info("season  players    ok  partial  failed  left out")
    for season, n, ok, part, fail, out in totals:
        log.info("%6d  %7d  %4d  %7d  %6d  %8d", season, n, ok, part, fail, out)
    if any(t[3] or t[4] for t in totals):
        # The schools scraped in this run that still failed or came back partial, in a few words.
        if finished:     # Ctrl-C before any school finished: nothing of this run's to list
            print_problems([r for season in seasons for r in new_reports[season].values()], this_run=True)
        if args.report:
            log.info("Details (with web addresses) are in scrape_report_<season>.csv in %s. "
                     "--problems lists all of them again without scraping.", report_dir)
        else:
            log.info("Add --report to save these with their web addresses (scrape_report_<season>.csv "
                     "and MISSING_ROSTERS.md).")
    if interrupted:
        # Everything is saved. Leave now instead of waiting for the schools still downloading.
        log.info("Saved. Re-run with --retry-failed to finish the schools that were cut off.")
        logging.shutdown()
        os._exit(130)
    return 0


# ==============================================================================================================
# Finding athletics domains (find-domains)   (was scripts/find_athletics_domains.py)
# ==============================================================================================================

FIND_ATHLETICS_DOMAINS_DOC = """Run on your Mac from the project folder:  python scripts/scrape_rosters.py find-domains
Follows each link in rosters/football/redirect_check.csv (athletics pages on a college's main site)
to where it ends up, and fills in that domain in config/football/schools.csv when the school's
domain is still blank. Prints what it did; nothing else is changed.
"""
import csv
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def find_athletics_domains_main(argv=None):
    import argparse as _argparse
    _argparse.ArgumentParser(prog="scrape_rosters.py find-domains", description=FIND_ATHLETICS_DOMAINS_DOC,
                             formatter_class=_argparse.RawDescriptionHelpFormatter).parse_args(argv)

    ROOT = Path(__file__).resolve().parent.parent
    CHECK = ROOT / "rosters" / "football" / "redirect_check.csv"
    SCHOOLS = ROOT / "config" / "football" / "schools.csv"
    UA = {"User-Agent": "Mozilla/5.0 (Macintosh) college-sports-atlas"}
    if not CHECK.exists():
        sys.exit(f"{CHECK} not found: nothing to check")

    found = {}
    for r in csv.DictReader(open(CHECK)):
        try:
            with urllib.request.urlopen(urllib.request.Request(r["ncaa_url"], headers=UA), timeout=30) as resp:
                final = resp.geturl()
        except Exception as e:  # noqa: BLE001
            print(f"  {r['school']}: could not open ({e})")
            continue
        host = urlparse(final).netloc.lower().removeprefix("www.")
        path = urlparse(final).path.strip("/")
        if path and "athletic" in path.lower():
            print(f"  {r['school']}: still on the college site ({final}); set roster_url by hand")
            continue
        found[r["school"]] = host
        print(f"  {r['school']}: {host}")

    rows = list(csv.DictReader(open(SCHOOLS)))
    fields = list(rows[0])
    n = 0
    for x in rows:
        if x["school"] in found and not x["domain"] and x["division"] in ("D2", "D3"):
            x["domain"] = found[x["school"]]
            n += 1
    with open(SCHOOLS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"filled {n} rows")


COMMANDS = {"find-domains": find_athletics_domains_main}


def command_line(argv=None) -> int:
    """python3 scripts/scrape_rosters.py <command> [options]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        sys.argv[0] = f"{Path(sys.argv[0]).name} {argv[0]}"     # so --help says "build.py map"
        return COMMANDS[argv[0]](argv[1:]) or 0
    return main(argv) or 0


if __name__ == "__main__":
    raise SystemExit(command_line())
