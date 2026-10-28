#!/usr/bin/env python3
"""Run a sport's whole pipeline with one command: scrape, retry, geocode, fix hometowns, frozen classes,
build the map data, campuses, and a check at the end.

    python3 scripts/pipeline.py softball
    python3 scripts/pipeline.py baseball softball lacrosse-mens
    python3 scripts/pipeline.py all
    python3 scripts/pipeline.py softball --only "Arkansas,LSU"
    python3 scripts/pipeline.py softball --from geocode
    python3 scripts/pipeline.py softball --skip scrape
    python3 scripts/pipeline.py softball --steps check
    python3 scripts/pipeline.py softball --dry-run

The steps, in order (--steps, --from and --skip use these names):

    test           python -m pytest tests -q              only with --test
    scrape         the quick pass: 2 minutes per school (--first-minutes), no browser, --workers 16
    retry          what's still failed or partial, slowly: 3 minutes per school (--school-minutes),
                   --refresh --render --bios, --workers 8
    redo-current   only with --redo-current (spring sports): scrape again the seasons that came from a
                   main roster page with no year on it (check_rosters.py says when there are any)
    geocode        place the hometowns
    fix-hometowns  suggest_hometown_fixes.py and fix_hometown_spellings.py, then geocode again
    frozen         check_frozen_classes.py
    build          build_map_data.py -> docs/<sport>/map_data.json
    locations      build_school_locations.py -> docs/<sport>/school_locations.json
    check          check_rosters.py: players, ok/partial/failed, oversized and repeated rosters

Both scrape steps always write the reports (--report) and MISSING_ROSTERS.md. When the sport already has
saved rosters, the first pass only fills in what's missing or partial (--retry-failed), like a second
retry; --rescrape makes it go through every school again. With --only, the schools named are scraped
again in full.

Schools that don't work are skipped: a school-season that came back failed or partial 3 times (counted in
rosters/<sport>/attempts.csv) isn't tried again; --retry-given-up tries them all again, --give-up-after N changes
the 3, and deleting a row from attempts.csv retries one. The current season is always tried. Schools named
with --only are always tried.

Seasons come from the sport's settings ("seasons" in config/<sport>.json; if it isn't there, football is
2016-2019,2021-2026 and every other sport 2016-2026). --seasons overrides them.

Several sports run one after the other. A sport that fails at a step stops there and the next sport
goes on; the table at the end says what ran. Everything printed is also saved to
rosters/<sport>/pipeline.log (send that file when something looks wrong).

A sport can't run twice at once: a second pipeline or scrape_rosters.py for the same sport stops
straight away with a message. Two different sports can run side by side in two windows.

Ctrl-C stops the step that's running (a scrape saves what finished first) and skips the rest.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import LOCK_ENV, ROOT, SportBusy, available_sports, load_sport, sport_lock  # noqa: E402
from seasons import read_csv, season_files  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
STEPS = ["test", "scrape", "retry", "redo-current", "geocode", "fix-hometowns", "frozen", "build",
         "locations", "check"]
OPTIONAL = {"test", "redo-current"}          # only run when asked (--test, --redo-current or --steps)


@dataclass
class Result:
    sport: str
    step: str
    status: str = "skipped"      # ok, failed, stopped, skipped
    seconds: float = 0.0
    note: str = ""


@dataclass
class Plan:
    steps: list[str]
    commands: dict[str, list[list[str]]] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


def py(script: str, *args: str) -> list[str]:
    return [sys.executable, str(SCRIPTS / script), *args]


def pick_steps(args) -> list[str]:
    def names(text: str) -> list[str]:
        out = [s.strip() for s in text.split(",") if s.strip()]
        bad = [s for s in out if s not in STEPS]
        if bad:
            raise SystemExit(f"unknown step {', '.join(bad)}; the steps are: {', '.join(STEPS)}")
        return out
    if args.steps:
        wanted = names(args.steps)
        return [s for s in STEPS if s in wanted]
    steps = [s for s in STEPS if s not in OPTIONAL
             or (s == "test" and args.test) or (s == "redo-current" and args.redo_current)]
    if args.from_step:
        start = names(args.from_step)[0]
        steps = [s for s in steps if STEPS.index(s) >= STEPS.index(start)]
    if args.skip:
        skip = set(names(args.skip))
        steps = [s for s in steps if s not in skip]
    return steps


def current_page_schools(sport) -> dict[int, list[str]]:
    """season -> schools whose saved roster came from a main page with no year on it ("current")."""
    out: dict[int, set[str]] = {}
    for path in sport.rosters_dir.glob("scrape_report_*.csv"):
        for r in read_csv(path):
            if r.get("season_check") == "current" and r.get("status") in ("ok", "partial"):
                out.setdefault(int(r["season"]), set()).add(r["school"])
    return {s: sorted(v) for s, v in sorted(out.items())}


def plan_for(sport, args) -> Plan:
    plan = Plan(steps=[s for s in pick_steps(args) if s != "test"])   # the tests run once, in main()
    seasons = args.seasons or sport.default_seasons()
    common = ["--sport", sport.name]
    picks = []
    if getattr(args, "retry_given_up", False):
        picks += ["--retry-given-up"]
    if getattr(args, "give_up_after", None) is not None:
        picks += ["--give-up-after", str(args.give_up_after)]
    if args.only:
        picks += ["--only", args.only]
    if args.division:
        picks += ["--division", args.division]
    scrape = py("scrape_rosters.py", *common, "--seasons", seasons, "--report", *picks)
    have_rosters = bool(season_files(sport.rosters_dir))

    if have_rosters and not args.only and not args.rescrape:
        first = [*scrape, "--retry-failed"]
        plan.notes["scrape"] = "rosters already saved: only what's missing or partial (--rescrape for everything)"
    else:
        first = list(scrape)
    plan.commands["scrape"] = [[*first, "--workers", str(args.workers), "--school-minutes", f"{getattr(args, 'first_minutes', 2):g}", "--timeout", "10"]]
    retry = [*scrape, "--retry-failed", "--render", "--bios", "--workers", str(args.retry_workers),
             "--school-minutes", f"{args.school_minutes:g}"]
    if not args.no_refresh:
        retry.append("--refresh")
    plan.commands["retry"] = [retry]

    redo = []
    pages = current_page_schools(sport) if sport.spring_season else {}   # a fall sport's main page is right
    for season, schools in pages.items():
        if args.only:
            wanted = {s.strip().lower() for s in args.only.split(",")}
            schools = [s for s in schools if s.lower() in wanted]
        if schools:
            redo.append(py("scrape_rosters.py", *common, "--seasons", str(season), "--report", "--render",
                           "--bios", "--only", ",".join(schools), "--workers", str(args.retry_workers),
                           "--school-minutes", f"{args.school_minutes:g}"))
    plan.commands["redo-current"] = redo
    if not redo:
        plan.notes["redo-current"] = "no seasons from a main page without a year"

    geocode = py("geocode_hometowns.py", *common, *(["--use-review"] if args.use_review else []))
    plan.commands["geocode"] = [geocode]
    plan.commands["fix-hometowns"] = [py("suggest_hometown_fixes.py", *common),
                                      py("fix_hometown_spellings.py", *common), geocode]
    plan.commands["frozen"] = [py("check_frozen_classes.py", *common)]
    plan.commands["build"] = [py("build_map_data.py", *common)]
    plan.commands["locations"] = [py("build_school_locations.py", *common)]
    plan.commands["check"] = [py("check_rosters.py", *common)]
    return plan


def show(cmd: list[str]) -> str:
    """The command as you'd type it, from the project folder."""
    parts = ["python3" if c == sys.executable else c for c in cmd]
    parts = [os.path.relpath(c, ROOT) if c.startswith(str(ROOT)) else c for c in parts]
    return " ".join(shlex.quote(c) for c in parts)


class Log:
    """Prints to the screen and to rosters/<sport>/pipeline.log at the same time."""

    def __init__(self, path: Path | None):
        self.fh = open(path, "w", encoding="utf-8") if path else None

    def __call__(self, text: str = "") -> None:
        print(text, flush=True)
        if self.fh:
            self.fh.write(text + "\n")
            self.fh.flush()

    def raw(self, line: str) -> None:
        sys.stdout.write(line)
        sys.stdout.flush()
        if self.fh:
            self.fh.write(line)
            self.fh.flush()

    def close(self) -> None:
        if self.fh:
            self.fh.close()


def run_command(cmd: list[str], log: Log, env: dict) -> int:
    """Run one command, its output shown and logged as it comes. Returns its exit code."""
    log(f"$ {show(cmd)}")
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    try:
        for line in proc.stdout:
            log.raw(line)
        return proc.wait()
    except KeyboardInterrupt:
        # The step got the Ctrl-C too (same terminal); let it finish saving, however long that takes
        log("\n[pipeline] stopping: waiting for the step to save what it has ...")
        while True:
            try:
                for line in proc.stdout:
                    log.raw(line)
                proc.wait()
                break
            except KeyboardInterrupt:
                continue
        raise


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def run_sport(name: str, args, results: list[Result]) -> bool:
    """Every step for one sport. False if Ctrl-C was pressed (stop everything)."""
    sport = load_sport(name)
    plan = plan_for(sport, args)
    for step in plan.steps:
        results.append(Result(name, step))
    mine = [r for r in results if r.sport == name]

    if args.dry_run:
        print(f"\n== {name} ({', '.join(plan.steps)})")
        for step in plan.steps:
            note = plan.notes.get(step)
            print(f"-- {step}" + (f"   ({note})" if note else ""))
            for cmd in plan.commands.get(step, []):
                print("   " + show(cmd))
        return True

    sport.rosters_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, LOCK_ENV: name, "PYTHONUNBUFFERED": "1"}
    log = Log(None)
    try:
        with sport_lock(sport, "pipeline.py"):
            log = Log(sport.rosters_dir / "pipeline.log")   # opened only once the sport is ours
            log(f"== {sport.label or name}: {', '.join(plan.steps)}   ({time.strftime('%Y-%m-%d %H:%M')})")
            for res in mine:
                cmds = plan.commands.get(res.step, [])
                res.note = plan.notes.get(res.step, "")
                if not cmds:
                    res.status = "skipped"
                    log(f"\n-- {res.step}: nothing to do" + (f" ({res.note})" if res.note else ""))
                    continue
                log(f"\n-- {res.step}" + (f"   ({res.note})" if res.note else ""))
                start = time.monotonic()
                code = 0
                try:
                    for cmd in cmds:
                        code = run_command(cmd, log, env)
                        if code != 0:
                            break
                except KeyboardInterrupt:
                    res.status, res.seconds = "stopped", time.monotonic() - start
                    log(f"[pipeline] {name}: stopped during {res.step}; later steps not run.")
                    return False
                res.seconds = time.monotonic() - start
                if code == 0:
                    res.status = "ok"
                else:
                    res.status = "failed"
                    res.note = f"exit code {code}"
                    if res.step == "check" or args.keep_going:
                        continue
                    log(f"\n[pipeline] {name}: {res.step} failed (exit code {code}); the later steps were "
                        f"not run. When it's fixed: python3 scripts/pipeline.py {name} --from {res.step}")
                    break
            log(f"\n== {name} done in {fmt_time(sum(r.seconds for r in mine))}. "
                f"This output is saved in {sport.rosters_dir.relative_to(ROOT)}/pipeline.log")
    except SportBusy as exc:
        log(f"\n[pipeline] {exc}")
        for res in mine:
            res.status, res.note = "busy", "already running elsewhere"
    finally:
        log.close()
    return True


def summary(results: list[Result]) -> None:
    if not results:
        return
    print("\n" + "=" * 70)
    print(f"{'sport':<18} {'step':<14} {'result':<8} {'time':>8}  note")
    for r in results:
        print(f"{r.sport:<18} {r.step:<14} {r.status:<8} {fmt_time(r.seconds) if r.seconds else '':>8}  {r.note}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sports", nargs="+", metavar="sport",
                    help="one or more sports as named in config/ (football, softball, lacrosse-mens, ...), or all")
    ap.add_argument("--steps", help="run only these steps, e.g. --steps build,check")
    ap.add_argument("--from", dest="from_step", metavar="STEP", help="start at this step, e.g. --from geocode")
    ap.add_argument("--skip", help="leave out these steps, e.g. --skip scrape,retry")
    ap.add_argument("--only", help="scrape only these schools (comma-separated); the later steps cover the whole sport")
    ap.add_argument("--division", help="scrape only schools in this current division (D1, FBS, NAIA, ...)")
    ap.add_argument("--seasons", help="override the sport's seasons, e.g. 2024-2026")
    ap.add_argument("--rescrape", action="store_true",
                    help="first pass goes through every school, not just what's missing (pages still come from the cache)")
    ap.add_argument("--no-refresh", action="store_true",
                    help="the retry reuses downloaded pages instead of downloading them again")
    ap.add_argument("--workers", type=int, default=16, help="schools at once in the first pass (default 16)")
    ap.add_argument("--retry-workers", type=int, default=8, help="schools at once in the retry (default 8)")
    ap.add_argument("--first-minutes", type=float, default=2,
                    help="time per school in the first pass before its other seasons are left for the retry (default 2)")
    ap.add_argument("--school-minutes", type=float, default=3,
                    help="time per school in the retry before its other seasons wait for the next run (default 3)")
    ap.add_argument("--give-up-after", type=int, metavar="N",
                    help="skip school-seasons that failed or came back partial N times (default 3; 0: never)")
    ap.add_argument("--retry-given-up", action="store_true",
                    help="try the given-up school-seasons again (see rosters/<sport>/attempts.csv)")
    ap.add_argument("--use-review", action="store_true", help="geocode with the 'review' hometown fixes too")
    ap.add_argument("--test", action="store_true", help="run the tests first")
    ap.add_argument("--redo-current", action="store_true",
                    help="spring sports: scrape again the seasons that came from a main page with no year on it")
    ap.add_argument("--keep-going", action="store_true", help="carry on with the next step when one fails")
    ap.add_argument("--dry-run", action="store_true", help="print the commands without running anything")
    args = ap.parse_args(argv)

    have = available_sports()
    sports = have if [s.lower() for s in args.sports] == ["all"] else args.sports
    unknown = [s for s in sports if s not in have]
    if unknown:
        ap.error(f"no config/<sport>.json for {', '.join(unknown)}; sports set up: {', '.join(have)}")
    if len(set(sports)) != len(sports):
        ap.error("a sport is listed twice")
    if args.only and len(sports) > 1:
        ap.error("--only names schools of one sport: give one sport with it")

    results: list[Result] = []
    try:
        # The tests cover every sport, so they run once, before any sport. Failing tests stop everything.
        if "test" in pick_steps(args):
            res = Result("(all)", "test")
            results.append(res)
            cmd = [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q"]
            if not (ROOT / "tests").is_dir():
                res.note = "no tests folder"
            elif args.dry_run:
                print(f"\n== tests\n   {show(cmd)}")
            else:
                start = time.monotonic()
                code = run_command(cmd, Log(None), {**os.environ, "PYTHONUNBUFFERED": "1"})
                res.seconds = time.monotonic() - start
                res.status = "ok" if code == 0 else "failed"
                if code != 0:
                    print("\n[pipeline] the tests failed, so nothing else was run.")
                    summary(results)
                    return 1
        for name in sports:
            if not run_sport(name, args, results):
                break
    except KeyboardInterrupt:
        print("\n[pipeline] stopped.")
    if not args.dry_run:
        summary(results)
    bad = [r for r in results if r.status in ("failed", "stopped", "busy")]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
