#!/usr/bin/env python3
"""Scrape a sport's rosters into CSV, for one season or many.

Examples
    python scripts/scrape_rosters.py                                   # current season, every school
    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026     # last 10 seasons, skipping 2020
    python scripts/scrape_rosters.py --seasons 2019 --only "Alabama,Clemson"
    python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed --render
    python scripts/scrape_rosters.py --recombine                       # no downloads: re-clean saved seasons, rebuild the combined files
    python scripts/scrape_rosters.py --sport mens-basketball           # another sport (needs config/mens-basketball/)

Reads config/<sport>/schools.csv, division_history.csv and sport.json (default sport: football).

Outputs (in --out, default data/<sport>/)
    seasons/rosters_<season>.csv          every player that season, one row each
    reports/scrape_report_<season>.csv    per school: status, strategy, player counts, URL, errors
    rosters_all_seasons.csv       all requested seasons stacked (one row per player per season)
    players_unique.csv            one row per player per school, with first/last season on the roster

Fetching, page parsing and field cleaning live in scripts/core/.
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

from core import fetch, hometowns, sidearm
from core.fetch import Fetcher, current_season
from core.hometowns import *            # noqa: F401,F403
from core.paths import ROOT, add_sport_argument, division_for, load_division_history, load_schools, load_sport
from core.sidearm import *              # noqa: F401,F403

# Older code imported everything from this file (`from scrape_rosters import parse_hometown`); keep
# those names here, including the underscored helpers, so it still works.
for _mod in (fetch, hometowns, sidearm):
    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__") and k not in globals()})
# =============================================================================
# Scraping and output
# =============================================================================

log = logging.getLogger("rosters")

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

def scrape_school_season(school: dict, fetcher: Fetcher, season: int, division: str,
                         render: bool, prefer_idx: int | None,
                         save_dir: Path | None = None) -> tuple[list[dict], dict, int | None]:
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
    for idx in order:
        url = urls[idx]
        try:
            status, final_url, html = fetcher.get(url)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            continue
        if status != 200:
            errors.append(f"{url}: HTTP {status}")
            continue
        if not is_current and str(season) in url and str(season) not in final_url:
            # e.g. liuathletics.com/.../roster/2019 quietly redirects to the current roster
            errors.append(f"{url}: redirected to {final_url}")
            continue
        shown = detect_season(html)
        if shown is not None and shown != season:
            errors.append(f"{url}: page shows {shown}")
            continue
        if is_current:
            check = "verified" if shown == season else "current"
        else:
            check = "verified" if shown == season else "unverified"
        strategy, players = parse_roster(html)
        # A page that shows the right year beats a bigger page that shows no year.
        if (check == "verified", len(players)) > (best[4] == "verified", len(best[1])):
            best = (strategy, players, final_url, idx, check)
        if len(players) >= sidearm.MIN_PLAYERS and check != "unverified":
            break

    if render and len(best[1]) < sidearm.MIN_PLAYERS:
        idx = best[3] if best[3] is not None else order[0]
        url = urls[idx]
        try:
            html = fetcher.render(url)
            shown = detect_season(html)
            if shown is None or shown == season:
                strategy, players = parse_roster(html)
                if len(players) > len(best[1]):
                    check = "verified" if shown == season else ("current" if is_current else "unverified")
                    best = (f"rendered:{strategy}", players, url, idx, check)
            else:
                errors.append(f"render {url}: page shows {shown}")
        except Exception as exc:
            errors.append(f"render {url}: {exc}")

    strategy, players, url, win_idx, check = best
    if save_dir and win_idx is not None:  # --save-pages: keep a copy of the page these players came from
        page = fetcher._cache_path(urls[win_idx], rendered=strategy.startswith("rendered:"))
        if page.exists():
            safe = re.sub(r"[^A-Za-z0-9]+", "_", school["school"]).strip("_")
            shutil.copy(page, save_dir / f"{safe}_{season}.html")
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
                  season_check=check, error="; ".join(errors[:8]))
    if len(rows) >= sidearm.MIN_PLAYERS and with_home >= 0.5 * len(rows):
        report["status"] = "ok"
    elif rows:
        report["status"] = "partial"
    return rows, report, (win_idx if not is_current else None)


def scrape_school_all(school: dict, seasons: list[int], fetcher: Fetcher, history: dict,
                      render: bool, skip: set[tuple[str, int]],
                      reference: tuple[int, set[str]] | None = None,
                      save_dir: Path | None = None) -> list[tuple[int, list[dict], dict]]:
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
        rows, report, idx = scrape_school_season(school, fetcher, season, division, render, prefer, save_dir)
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


def write_combined(out_dir: Path, season_dir: Path) -> tuple[list[int], list[dict], list[dict]]:
    """Rebuild rosters_all_seasons.csv and players_unique.csv from every saved season, re-cleaning
    each row so parser fixes (names, hometowns, high school vs. previous school) reach old seasons too."""
    # Combined outputs cover every season saved so far, not just this run.
    combined = []
    all_saved = []
    for path in sorted(season_dir.glob("rosters_*.csv")):
        m = re.fullmatch(r"rosters_(\d{4})\.csv", path.name)
        if m:
            all_saved.append(int(m.group(1)))
            combined.extend(read_csv(path))
    n_before = len(combined)
    combined = [r for r in combined if not is_staff(r)]  # also cleans seasons saved by older versions
    if n_before != len(combined):
        log.info("Dropped %d coach/staff rows from the saved rosters", n_before - len(combined))
    for r in combined:  # re-clean so name/hometown fixes also reach seasons scraped earlier
        r["name"] = clean_name(r.get("name", ""))
        home = parse_hometown(r.get("hometown", ""))
        r["home_city"], r["home_state"], r["home_country"] = home["city"], home["state"], home["country"]
        r["class_norm"] = normalize_class(r.get("class_year", "")) or r.get("class_norm", "")
        sort_schools(r)
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
    ap.add_argument("--schools", type=Path, help="default: config/<sport>/schools.csv")
    ap.add_argument("--division-history", type=Path, help="default: config/<sport>/division_history.csv")
    ap.add_argument("--seasons", help="e.g. 2016-2019,2021-2026 (default: current season)")
    ap.add_argument("--season", type=int, help="single season (same as --seasons N)")
    ap.add_argument("--division", choices=["FBS", "FCS", "all"], default="all", help="by current division")
    ap.add_argument("--conference", help="only this current conference (as in schools.csv)")
    ap.add_argument("--only", help="comma-separated school names")
    ap.add_argument("--out", type=Path, help="default: data/<sport>/")
    ap.add_argument("--cache", default=ROOT / ".cache" / "html", type=Path)
    ap.add_argument("--workers", type=int, default=6, help="schools scraped in parallel (different sites)")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests to the same site")
    ap.add_argument("--refresh", action="store_true", help="ignore cached HTML and re-download")
    ap.add_argument("--render", action="store_true", help="headless Chromium for pages the fast path can't parse")
    ap.add_argument("--save-pages", type=Path, metavar="DIR",
                    help="also copy each roster page used into DIR as <school>_<season>.html (for checking by hand)")
    ap.add_argument("--retry-failed", action="store_true", help="skip school-seasons already 'ok' in the reports")
    ap.add_argument("--recombine", action="store_true",
                    help="don't download anything: re-clean every saved season and rebuild the combined files")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    sidearm.configure(sport)
    args.schools = args.schools or sport.schools_csv
    args.division_history = args.division_history or sport.division_history_csv
    args.out = args.out or sport.data_dir

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.ERROR)

    seasons = parse_seasons(args.seasons) if args.seasons else [args.season or current_season()]
    season_dir, report_dir = args.out / "seasons", args.out / "reports"
    for d in (season_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)
    all_schools = load_schools(args.schools)
    history = load_division_history(args.division_history)
    load_known_colleges(all_schools)
    if args.recombine:
        write_combined(args.out, season_dir)
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

    # Keep previous results for schools/seasons not being re-scraped in this run.
    kept_rows: dict[int, list[dict]] = {}
    kept_reports: dict[int, dict[str, dict]] = {}
    skip: set[tuple[str, int]] = set()
    for season in seasons:
        prev_reports = {r["school"]: r for r in read_csv(report_dir / f"scrape_report_{season}.csv")}
        done = {k for k, r in prev_reports.items() if r.get("status") in ("ok", "no_program")} if args.retry_failed else set()
        keep_schools = {k for k in prev_reports if k not in selected} | done
        skip.update((k, season) for k in done)
        kept_reports[season] = {k: r for k, r in prev_reports.items() if k in keep_schools}
        kept_rows[season] = [r for r in read_csv(season_dir / f"rosters_{season}.csv") if r["school"] in keep_schools]

    todo = sum(1 for s in schools for y in seasons if (s["school"], y) not in skip)
    log.info("Scraping %d schools x %d seasons (%s) = %d roster pages",
             len(schools), len(seasons), ", ".join(map(str, seasons)), todo)

    # Newest saved roster per school (from earlier runs) for the fallback check. This includes
    # seasons inside the requested range, so --retry-failed still has the newest roster to
    # compare against when that season is skipped as already done.
    references: dict[str, tuple[int, set[str]]] = {}
    saved = sorted(season_dir.glob("rosters_*.csv"), reverse=True)
    for path in saved:
        m = re.fullmatch(r"rosters_(\d{4})\.csv", path.name)
        if not m:
            continue
        for r in read_csv(path):
            if r["school"] not in references or references[r["school"]][0] == int(m.group(1)):
                references.setdefault(r["school"], (int(m.group(1)), set()))[1].add(r["name"].lower())

    save_dir = args.save_pages.expanduser() if args.save_pages else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(args.cache, delay=args.delay, refresh=args.refresh)
    new_rows: dict[int, list[dict]] = {y: [] for y in seasons}
    new_reports: dict[int, dict[str, dict]] = {y: {} for y in seasons}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(scrape_school_all, s, seasons, fetcher, history, args.render, skip,
                               references.get(s["school"]), save_dir): s
                   for s in schools}
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
                log.info("[%3d/%d] %-26s %s", i, len(schools), school["school"], " ".join(sorted(summary)))

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

    all_saved, combined, unique = write_combined(args.out, season_dir)
    log.info("season  players   ok  partial  failed")
    for season, n, ok, part, fail in totals:
        log.info("%6d  %7d  %3d  %7d  %6d", season, n, ok, part, fail)
    if any(t[3] or t[4] for t in totals):
        log.info("Not every school worked; see reports/scrape_report_<season>.csv, fix config/schools.csv, then re-run with --retry-failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
