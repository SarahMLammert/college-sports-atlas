#!/usr/bin/env python3
"""Scrape a sport's rosters into CSV, for one season or many.

Examples
    python scripts/scrape_rosters.py                                   # current season, every school
    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026     # last 10 seasons, skipping 2020
    python scripts/scrape_rosters.py --seasons 2019 --only "Alabama,Clemson"
    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed --render
    python scripts/scrape_rosters.py --recombine                       # no downloads: re-clean saved seasons, rebuild the combined files
    python scripts/scrape_rosters.py --sport mens-basketball           # another sport (needs config/mens-basketball.json)

Reads config/<sport>.json and config/<sport>_schools.csv (default sport: football).

Outputs (in rosters/<sport>/, or --out). The rosters are all cleaned: no jersey numbers or captain
marks in names, hometowns split into city/state/country, high school and previous school sorted out.
    rosters_<season>.csv          every player that season, one row each
    rosters_all_seasons.csv       every saved season stacked (one row per player per season)
    players_unique.csv            one row per player per school, with first/last season on the roster
    scrape_report_<season>.csv    per school: status, strategy, player counts, URL, errors

Fetching, page parsing and field cleaning live in fetch.py, sidearm.py and hometowns.py next to this script.
"""
from __future__ import annotations

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

import fetch, hometowns, sidearm
from fetch import Fetcher, current_season
from hometowns import *            # noqa: F401,F403
from paths import (ROOT, SCRAPED, add_sport_argument, d1_schools, division_for, load_all_colleges,
                   load_division_history, load_schools, load_sport)
from sidearm import *              # noqa: F401,F403

# Older code imported everything from this file (`from scrape_rosters import parse_hometown`); keep
# those names here, including the underscored helpers, so it still works.
for _mod in (fetch, hometowns, sidearm):
    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__") and k not in globals()})
# =============================================================================
# Scraping and output
# =============================================================================

log = logging.getLogger("rosters")
RENDER_TRIES = 4   # most addresses rendered per school-season with --render (each takes a few seconds)
# A site's own link to a season roster in PrestoSports style: /sports/fball/2026-27/roster (Mars Hill),
# /sports/m-footbl/2026-27/roster (Carson-Newman, Presto's older code). Not flag football ("flagfball").
ROSTER_LINK = re.compile(r'href="[^"]*/sports/(fball|m-footbl)/\d{4}-\d{2}/roster\b')

OUT_FIELDS = (
    ["season", "division", "current_conference", "school"]
    + [f for f in FIELDS if f != "bio_url"]
    + ["class_norm", "home_city", "home_state", "home_country", "strategy", "bio_url", "roster_url"]
)
REPORT_FIELDS = ["season", "school", "division", "current_conference", "status", "season_check",
                 "strategy", "players", "with_hometown", "url", "error"]
UNIQUE_FIELDS = ["school", "name", "position", "hometown", "home_city", "home_state", "home_country",
                 "high_school", "previous_school", "first_season", "last_season", "n_seasons", "seasons",
                 "first_class", "division_first_season", "current_conference"]


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
    if is_current:
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
            status, final_url, html = fetcher.get(url)
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
                link = None if followed else ROSTER_LINK.search(html)
                if link:
                    followed = True
                    # Built on the page's own address (its canonical link) when it gives one: Northwood's
                    # gonorthwood.com sends everyone to the www. home page, so only www. works.
                    canon = re.search(r'<link[^>]+rel="canonical"[^>]+href="(https?://[^"]+)"', html)
                    base = canon.group(1) if canon else url
                    nxt = urljoin(base, f"/sports/{link.group(1)}/{season}-{(season + 1) % 100:02d}/roster")
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
        if page.exists():
            safe = re.sub(r"[^A-Za-z0-9]+", "_", school["school"]).strip("_")
            shutil.copy(page, save_dir / f"{safe}_{season}.html")
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
    if len(rows) >= sidearm.MIN_PLAYERS and with_home >= 0.5 * len(rows):
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
    archive pages that silently show the current roster."""
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
                                         "current_conference": school.get("conference", ""), "status": "failed",
                                         "season_check": "", "strategy": "", "players": 0, "with_hometown": 0,
                                         "url": "", "error": note}))
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
        elif rows and (newest_season is None or season > newest_season):
            newest_names, newest_season = names, season
        if idx is not None and report["status"] == "ok":
            prefer = idx
        results.append((season, rows, report))
    return results


# ---------------------------------------------------------------------------
# problem list: failed and partial schools in a few words, without the web addresses

_URL_PREFIX = re.compile(r"^(render |bio )?https?://\S+?:\s*")


def short_reason(error: str) -> str:
    """'https://x/roster/2018: redirected to https://x/roster; https://x/...: HTTP 404; ...'
    -> 'redirected ×4, HTTP 404 ×6'. Browser results are marked 'browser:'."""
    counts: dict[str, int] = {}
    for part in (error or "").split("; "):
        part = part.strip()
        if not part or part == "...":
            continue
        browser = part.startswith("render ")
        msg = _URL_PREFIX.sub("", part)
        msg = re.sub(r"redirected to \S+", "redirected", msg)
        msg = re.sub(r"\S+://\S+", "", msg).strip(" :")
        msg = {"HTTP 202": "bot check", "HTTP 404": "not found", "SSLError": "certificate error",
               "TimeoutError": "too slow", "ConnectionError": "no connection"}.get(msg, msg)
        if browser:
            msg = "browser: " + msg
        counts[msg] = counts.get(msg, 0) + 1
    return ", ".join(f"{m} ×{n}" if n > 1 else m for m, n in counts.items())


def print_problems(reports: list[dict]) -> None:
    bad = [r for r in reports if r.get("status") in ("failed", "partial")]
    if not bad:
        log.info("No failed or partial schools.")
        return
    log.info("Failed or partial (%d):", len(bad))
    for r in sorted(bad, key=lambda r: (str(r["season"]), r.get("division", ""), r["school"])):
        players = f"{r.get('players') or 0} players, {r.get('with_hometown') or 0} with hometown" \
            if r["status"] == "partial" else "no roster"
        log.info("  %s %-5s %-26s %-8s %s  (%s)", r["season"], r.get("division", ""), r["school"][:26],
                 r["status"], players, short_reason(r.get("error", "")) or "no details")


# ---------------------------------------------------------------------------
# MISSING_ROSTERS.md: the failed and partial schools of a sport, by division, with the reason in words

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
        m = re.search(r"bios: hometowns from (\d+) of (\d+) player pages", err)
        if m:
            return (f"the roster page has no hometowns; the players' own pages gave {m.group(1)} of {m.group(2)}, "
                    "the rest don't list one")
        if "bios: the first" in err:
            return "neither the roster page nor the players' own pages list most hometowns"
        return "the site lists hometowns for only some players"
    if err.lower().startswith("left out"):
        return err[0].upper() + err[1:]
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
                          out_dir: Path | None = None) -> Path:
    """Write MISSING_ROSTERS.md from every scrape report in report_dir, into out_dir (the sport's
    rosters/<sport>/ folder, so it's always in the same place, even for a test run with --out).

    For each division: schools with a failed season (no roster saved) and schools with a partial one
    (saved, but most players without a hometown), each with its seasons and why. The reason is the
    school's note in the schools file when it has one (a person checked it), else the scraper's own
    short reason. Then the colleges skipped because they have no athletics site."""
    notes = _school_notes(schools_csv)
    division_of = {r["school"]: r["division"] for r in read_csv(schools_csv) if r["division"] in DIVISION_ORDER}
    reports = []
    for path in sorted(report_dir.glob("scrape_report_*.csv")):
        reports += read_csv(path)
    seasons_checked = sorted({int(r["season"]) for r in reports if str(r.get("season", "")).isdigit()})
    # (division, status) -> school -> [(season, report)]
    groups: dict[tuple[str, str], dict[str, list[tuple[int, dict]]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for r in reports:
        div = r.get("division") or division_of.get(r["school"], "")
        if r.get("status") == "no_program":
            continue
        c = counts.setdefault(div, {"ok": 0, "partial": 0, "failed": 0})
        c[r["status"]] = c.get(r["status"], 0) + 1
        if r["status"] in ("failed", "partial"):
            groups.setdefault((div, r["status"]), {}).setdefault(r["school"], []).append((int(r["season"]), r))

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
           "- **Partial**: the roster was saved, but most players have no hometown, so they get no dot on the map.",
           "- Seasons before a program started or after it ended aren't listed: they're not failures.", "",
           "| division | ok | partial | failed |", "|---|---|---|---|"]
    divs = [d for d in DIVISION_ORDER if d in counts] + sorted(d for d in counts if d not in DIVISION_ORDER)
    for d in divs:
        c = counts[d]
        out.append(f"| {d or '?'} | {c.get('ok', 0)} | {c.get('partial', 0)} | {c.get('failed', 0)} |")
    out.append("")
    for d in divs:
        failed, partial = groups.get((d, "failed"), {}), groups.get((d, "partial"), {})
        if not (failed or partial):
            continue
        out += [f"## {d or 'Unknown division'}", ""]
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
                out.append(line)
            out.append("")
    if no_site:
        # Current = some row of the school has a 2026 conference and no last season; the rest closed
        # or dropped football. Both are still used to sort transfers by level.
        rows_of: dict[str, list[dict]] = {}
        for r in read_csv(schools_csv):
            rows_of.setdefault(r["school"], []).append(r)
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
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MISSING_FILE
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# outputs

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:  # files written by the first version used "conference"
        if "current_conference" not in r and "conference" in r:
            r["current_conference"] = r.pop("conference")
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def person_key(row: dict) -> tuple:
    name = _SUFFIX.sub("", clean(row["name"]).lower())
    name = re.sub(r"[^a-z]", "", name)
    city = re.sub(r"[^a-z]", "", (row.get("home_city") or "").lower())
    return (row["school"], name, city, row.get("home_state") or row.get("home_country") or "")


def build_unique(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(person_key(r), []).append(r)
    # A season where the site left the hometown blank would otherwise count as a second player.
    # Fold it into the one group with the same school + name, if there is exactly one.
    by_name: dict[tuple, list[tuple]] = {}
    for k in groups:
        if k[2] or k[3]:
            by_name.setdefault(k[:2], []).append(k)
    for k in [k for k in groups if not (k[2] or k[3])]:
        homes = by_name.get(k[:2], [])
        if len(homes) == 1:
            groups[homes[0]].extend(groups.pop(k))
    out = []
    for grp in groups.values():
        grp.sort(key=lambda r: int(r["season"]))
        first, last = grp[0], grp[-1]
        seasons = sorted({int(r["season"]) for r in grp})
        out.append({
            "school": first["school"], "name": last["name"], "position": last["position"],
            **{f: next((r[f] for r in grp if r["hometown"]), first[f])
               for f in ("hometown", "home_city", "home_state", "home_country")},
            "high_school": next((r["high_school"] for r in grp if r["high_school"]), ""),
            "previous_school": next((r["previous_school"] for r in grp if r["previous_school"]), ""),
            "first_season": seasons[0], "last_season": seasons[-1], "n_seasons": len(seasons),
            "seasons": " ".join(map(str, seasons)), "first_class": first["class_norm"],
            "division_first_season": first["division"], "current_conference": first["current_conference"],
        })
    out.sort(key=lambda r: (r["school"], r["first_season"], r["name"]))
    return out


def season_files(out_dir: Path) -> dict[int, Path]:
    """season -> rosters_<season>.csv for every season saved in the folder."""
    out = {}
    for path in out_dir.glob("rosters_*.csv"):
        m = re.fullmatch(r"rosters_(\d{4})\.csv", path.name)
        if m:
            out[int(m.group(1))] = path
    return dict(sorted(out.items()))


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
    home = parse_hometown(r.get("hometown", ""))
    r["home_city"], r["home_state"], r["home_country"] = home["city"], home["state"], home["country"]
    r["class_norm"] = normalize_class(r.get("class_year", "")) or r.get("class_norm", "")
    return sort_schools(r)


def clean_rows(rows: list[dict]) -> list[dict]:
    """Drop coaches and staff, and clean every remaining row."""
    return [clean_row(r) for r in rows if not is_staff(r)]


def write_combined(out_dir: Path) -> tuple[list[int], list[dict], list[dict]]:
    """Clean every saved season file in place, then rebuild rosters_all_seasons.csv and players_unique.csv
    from them. Every roster file holds only the cleaned version."""
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
        log.info("Dropped %d coach/staff rows from the saved rosters", n_before - len(combined))
    write_csv(out_dir / "rosters_all_seasons.csv", OUT_FIELDS, combined)
    unique = build_unique(combined)
    write_csv(out_dir / "players_unique.csv", UNIQUE_FIELDS, unique)

    n_prev = sum(1 for r in unique if r["previous_school"])
    log.info("Combined files cover seasons %s: %d player-season rows, %d unique players (%d with a previous school) -> %s",
             ", ".join(map(str, all_saved)), len(combined), len(unique), n_prev, out_dir)
    return all_saved, combined, unique


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    ap.add_argument("--schools", type=Path, help="default: config/<sport>_schools.csv")
    ap.add_argument("--division-history", type=Path, help="default: config/<sport>_schools.csv (its rows with a season range)")
    ap.add_argument("--seasons", help="e.g. 2016-2019,2021-2026 (default: current season)")
    ap.add_argument("--season", type=int, help="single season (same as --seasons N)")
    ap.add_argument("--division", choices=["FBS", "FCS", "D2", "D3", "NAIA", "JUCO", "all"], default="all",
                    help="by current division")
    ap.add_argument("--conference", help="only this current conference (as in schools.csv)")
    ap.add_argument("--only", help="comma-separated school names")
    ap.add_argument("--out", type=Path, help="where the rosters go (default: rosters/<sport>/)")
    ap.add_argument("--cache", default=ROOT / ".cache" / "html", type=Path)
    ap.add_argument("--workers", type=int, default=6, help="schools scraped in parallel (different sites)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests to the same site")
    ap.add_argument("--refresh", action="store_true", help="ignore cached HTML and re-download")
    ap.add_argument("--render", action="store_true", help="headless Chromium for pages the fast path can't parse")
    ap.add_argument("--bios", action="store_true",
                    help="for rosters with players but mostly no hometowns, read each player's own page (slow: one request per player)")
    ap.add_argument("--save-pages", type=Path, metavar="DIR",
                    help="also copy each roster page used into DIR as <school>_<season>.html (for checking by hand)")
    ap.add_argument("--retry-failed", action="store_true", help="skip school-seasons already 'ok' in the reports")
    ap.add_argument("--recombine", action="store_true",
                    help="don't download anything: re-clean every saved season and rebuild the combined files")
    ap.add_argument("--problems", action="store_true",
                    help="don't scrape: list the failed and partial schools in the saved reports "
                         "(for --seasons, and --division / --only if given)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    sidearm.configure(sport)
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
    for d in (season_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)
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
    def write_missing() -> None:
        # Always in rosters/<sport>/, even when --out sends the rosters somewhere else
        path = write_missing_rosters(report_dir, args.schools, getattr(sport, "label", args.sport), no_site,
                                     out_dir=sport.rosters_dir)
        log.info("Failing and partial schools, with reasons -> %s", path)

    if args.recombine:
        write_combined(season_dir)
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
    for season in seasons:
        prev_reports = {r["school"]: r for r in read_csv(report_dir / f"scrape_report_{season}.csv")}
        done = {k for k, r in prev_reports.items() if r.get("status") in ("ok", "no_program")} if args.retry_failed else set()
        keep_schools = {k for k in prev_reports if k not in selected} | done
        skip.update((k, season) for k in done)
        prev_reports_all[season] = prev_reports
        prev_rows_all[season] = read_csv(season_dir / f"rosters_{season}.csv")
        kept_reports[season] = {k: r for k, r in prev_reports.items() if k in keep_schools}
        kept_rows[season] = [r for r in prev_rows_all[season] if r["school"] in keep_schools]

    todo = sum(1 for s in schools for y in seasons if (s["school"], y) not in skip)
    log.info("Scraping %d schools x %d seasons (%s) = %d roster pages",
             len(schools), len(seasons), ", ".join(map(str, seasons)), todo)

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
    fetcher = Fetcher(args.cache, delay=args.delay, refresh=args.refresh)
    new_rows: dict[int, list[dict]] = {y: [] for y in seasons}
    new_reports: dict[int, dict[str, dict]] = {y: {} for y in seasons}
    lock = threading.Lock()

    pool = ThreadPoolExecutor(max_workers=max(1, args.workers))
    futures = {pool.submit(scrape_school_all, s, seasons, fetcher, history, args.render, skip,
                           references.get(s["school"]), save_dir, args.bios): s
               for s in schools}
    finished: set[str] = set()
    interrupted = False
    try:
        for i, fut in enumerate(as_completed(futures), 1):
            school = futures[fut]
            try:
                results = fut.result()
            except Exception as exc:
                log.error("%s crashed: %r", school["school"], exc)
                continue
            with lock:
                summary = []
                for season, rows, report in results:
                    new_rows[season].extend(rows)
                    new_reports[season][school["school"]] = report
                    summary.append(f"{season}:{report['players'] if report['status'] in ('ok', 'partial') else report['status'][:4]}")
                finished.add(school["school"])
                if summary:   # schools whose seasons were all skipped (--retry-failed, already ok) print nothing
                    log.info("[%3d/%d] %-26s %s", i, len(schools), school["school"], " ".join(sorted(summary)))
        pool.shutdown(wait=True)
    except KeyboardInterrupt:
        # Ctrl-C: save the schools that finished. The ones still running keep what the run before
        # saved for them, and --retry-failed picks them up next time.
        interrupted = True
        pool.shutdown(wait=False, cancel_futures=True)
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
        write_csv(report_dir / f"scrape_report_{season}.csv", REPORT_FIELDS,
                  sorted(reports.values(), key=lambda r: order.get(r["school"], 9999)))
        st = [r.get("status") for r in reports.values()]
        totals.append((season, len(rows), st.count("ok"), st.count("partial"), st.count("failed")))

    all_saved, combined, unique = write_combined(season_dir)
    write_missing()
    log.info("season  players   ok  partial  failed")
    for season, n, ok, part, fail in totals:
        log.info("%6d  %7d  %3d  %7d  %6d", season, n, ok, part, fail)
    if any(t[3] or t[4] for t in totals):
        # The schools scraped in this run that still failed or came back partial, in a few words.
        print_problems([r for season in seasons for r in new_reports[season].values()])
        log.info("Details (with web addresses) are in scrape_report_<season>.csv in %s. "
                 "--problems lists all of them again without scraping.", report_dir)
    if interrupted:
        # Everything is saved. Leave now instead of waiting for the schools still downloading.
        log.info("Saved. Re-run with --retry-failed to finish the schools that were cut off.")
        logging.shutdown()
        os._exit(130)
    return 0


if __name__ == "__main__":
    sys.exit(main())
