"""The scraper's failure reports: attempts.csv (school-seasons that keep failing, so later runs stop trying
them), the problem list printed at the end of a run, and MISSING_ROSTERS.md (the failed and partial schools
of a sport by division, with the reason in words). scrape_rosters.py calls these.
(Part of scrape_rosters.py until Nov 1.)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import core
import sidearm
from core import read_csv, write_csv

log = logging.getLogger("rosters")   # the scraper's log


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
    return core.reason_code(report) != "time_limit"


def read_attempts(rosters_dir: Path, rules: sidearm.Rules = sidearm.DEFAULT) -> dict[tuple[str, int], dict]:
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
                    "reason": plain_reason(r, rules), "last_try": "before Oct 27"}
    return out


def write_attempts(rosters_dir: Path, attempts: dict[tuple[str, int], dict]) -> None:
    rows = sorted(attempts.values(), key=lambda r: (r["school"], int(r["season"])))
    write_csv(Path(rosters_dir) / ATTEMPTS_FILE, ATTEMPT_FIELDS, rows)


def update_attempts(attempts: dict[tuple[str, int], dict], results: dict[tuple[str, int], dict],
                    rules: sidearm.Rules = sidearm.DEFAULT) -> None:
    """Count this run's results in: an ok season is forgotten, a failed or partial one gets one more try."""
    from datetime import date
    today = date.today().isoformat()
    for key, report in results.items():
        if report.get("status") == "ok":
            attempts.pop(key, None)
        elif counts_as_try(report):
            row = attempts.get(key) or {"school": key[0], "season": key[1], "tries": 0}
            row.update(tries=int(row.get("tries") or 0) + 1, status=report["status"],
                       reason=plain_reason(report, rules), last_try=today)
            attempts[key] = row


def given_up(attempts: dict[tuple[str, int], dict], limit: int) -> set[tuple[str, int]]:
    return {k for k, r in attempts.items() if limit > 0 and int(r.get("tries") or 0) >= limit}


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
    return core.reason_code(report) == "left_out"


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


def plain_reason(report: dict, rules: sidearm.Rules = sidearm.DEFAULT) -> str:
    """One sentence on why a school-season failed or is partial, from its report row."""
    err = report.get("error", "") or ""
    short = short_reason(err)
    if report.get("status") == "partial":
        n = int(report.get("players") or 0)
        if n and n < rules.min_players:
            return f"only {n} players, fewer than a normal roster for this sport (at least {rules.min_players}): a page cut off?"
        if n and rules.max_players and n > rules.max_players:
            return (f"{n} players, more than a normal roster for this sport (at most {rules.max_players}): "
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
    code = core.reason_code(report)
    if code == "time_limit":
        return "skipped: the school's other seasons took too long (--retry-failed tries it again)"
    if code == "other_sport":
        return "the only roster pages found were another sport's (the site may not list this team's roster)"
    if code == "not_posted":
        return "this season's roster isn't up yet: the main roster page still shows last season's team"
    if code == "newer_roster":
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
                          gave_up: set[tuple[str, int]] | None = None,
                          rules: sidearm.Rules = sidearm.DEFAULT) -> Path:
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
    saved = {(r["school"], int(r["season"])) for r in reports if r.get("status") in ("ok", "partial")}
    has_season = lambda school, season: (school, season) in saved
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
        elif status == "failed":
            status = core.failure_kind(r, has_season, spring=rules.spring)     # not posted yet, or the COVID season (Oct 30)
        c = counts.setdefault(div, {"ok": 0, "partial": 0, "failed": 0, "not_posted": 0, "covid": 0, "left_out": 0})
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
           "- **Not posted yet**: the current season, when the school's site has no roster for it yet (its pages "
           "still show last season's team). Counted on their own, not listed; the next runs pick them up.",
           "- **COVID**: no roster for the COVID season (fall 2020, or 2020-21) at a school with rosters the "
           "seasons before and after: most likely no season was played. Counted on their own, not listed.",
           "- **Not tried any more**: failed or partial on several runs in a row (`attempts.csv` in this folder "
           "counts the tries), so runs skip it. `--retry-given-up` tries those again; deleting a row from "
           "attempts.csv does it for one school-season.", "",
           "| division | ok | partial | failed | not posted yet | COVID | left out |", "|---|---|---|---|---|---|---|"]
    divs = [d for d in order if d in counts] + sorted(d for d in counts if d not in order)
    for d in divs:
        c = counts[d]
        out.append(f"| {d or '?'} | {c.get('ok', 0)} | {c.get('partial', 0)} | {c.get('failed', 0)} "
                   f"| {c.get('not_posted', 0)} | {c.get('covid', 0)} | {c.get('left_out', 0)} |")
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
                reasons = {s: plain_reason(r, rules) for s, r in items}
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
                reason = notes.get(school) or plain_reason(items[0][1], rules)
                out.append(f"- **{school}** ({labels.get(d, d) or '?'}): {reason}")
            else:      # single seasons, from config/<sport>/wrong_seasons.csv
                why = "; ".join(f"{y}: {plain_reason(r, rules)}" for y, r in sorted(items, key=lambda x: x[0]))
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
