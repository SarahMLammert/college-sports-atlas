"""Coaches and staff from a team's roster page (Sidearm classic and cards, WMT/Nuxt) or its separate coaches page
(PrestoSports). Shared by staff.py scrape and the tests.

Every layout links each coach to a bio page: /sports/<sport>/roster/coaches/<name>/<id> (Sidearm),
/sports/<sport>/roster/season/<year>/staff/<name> (WMT), /sports/<sport>/coaches/<name> (Presto). parse_staff()
starts from those links, takes the name from the link (or its aria-label when the link says "Full Bio") and the
job title from the card or table row the link sits in.

This file holds, in order:
    Reading staff from pages
    Scraping staff (scrape)
    The staff data (build)

Commands:
    python3 scripts/staff.py scrape --sport football   # scraping staff
    python3 scripts/staff.py build --sport football   # the staff data
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ==============================================================================================================
# Reading staff from pages   (was scripts/staff.py)
# ==============================================================================================================

STAFF_DOC = 'Coaches and staff from a team\'s roster page (Sidearm classic and cards, WMT/Nuxt) or its separate coaches page\n(PrestoSports). Shared by staff.py scrape and the tests.\n\nEvery layout links each coach to a bio page: /sports/<sport>/roster/coaches/<name>/<id> (Sidearm),\n/sports/<sport>/roster/season/<year>/staff/<name> (WMT), /sports/<sport>/coaches/<name> (Presto). parse_staff()\nstarts from those links, takes the name from the link (or its aria-label when the link says "Full Bio") and the\njob title from the card or table row the link sits in.\n'
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_BIO_LINK = re.compile(r"/(?:roster/)?coaches/[^/?#]+|/roster/(?:season/[^/]+/)?staff/[^/?#]+|/coach/[^/?#]+", re.I)
_TITLE_CLASS = re.compile(r"title|position|role|job", re.I)
_NAME_CLASS = re.compile(r"name|heading|person-link", re.I)
_CARD = re.compile(r"coach|staff|person|card|member", re.I)
_NOT_NAME = re.compile(r"^(full bio|bio|view( full)? bio|read more|more|email|e-mail|phone|twitter|x|instagram|"
                       r"headshot|photo|coaches|coaching staff|staff|support staff|meet the staff)$", re.I)
_NAME_OK = re.compile(r"^[A-Z][\w'’.\-]*(?:\s+[\w'’.\-()]+){1,4}$", re.U)
_TITLE_WORDS = re.compile(r"coach|coordinator|director|manager|trainer|assistant|analyst|operations|strength|"
                          r"video|recruit|athletic|graduate|volunteer|intern|consultant|advisor|chief|specialist|"
                          r"administrat|equipment|sports (?:medicine|performance)|nutrition|scout|quality|personnel|"
                          r"chaplain|student|team|staff|associate", re.I)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _name_of(a) -> tuple[str, int]:
    """The person's name from a bio link, and how sure it is (2: the link's text, 1: its aria-label or title,
    0: made from the address). "Scott Marr - View Full Bio" and "Full Bio for Jo Koons" give the name."""
    for sure, cand in ((2, a.get_text(" ")), (1, a.get("aria-label", "")), (1, a.get("title", ""))):
        cand = _clean(re.sub(r"(?i)\s*[-–|]?\s*(view )?full bio\s*$|\s+full bio$", "", _clean(cand)))
        cand = re.sub(r"(?i)^(full bio for|bio for|view bio for|bio|view bio)\s*[:-]?\s*", "", cand)
        if cand and not _NOT_NAME.match(cand) and _NAME_OK.match(cand) and len(cand) <= 50:
            return cand, sure
    # a link with only a photo: the name from its address ("/coaches/scott-marr/2333" -> "Scott Marr")
    m = re.search(r"/(?:coaches|staff|coach)/([a-z0-9-]+?)(?:/\d+)?/?$", a.get("href", ""), re.I)
    if m and not m.group(1).isdigit():
        words = [w for w in m.group(1).split("-") if w and not w.isdigit() and w.lower() != "coach"]
        if 2 <= len(words) <= 4:
            return " ".join(w.capitalize() for w in words), 0
    return "", 0


_POSITION_GROUP = re.compile(
    r"quarterbacks?|running backs?|wide receivers?|receivers|tight ends?|offensive line|defensive line|"
    r"linebackers?|defensive backs?|secondary|safeties|cornerbacks?|special teams|outside linebackers|"
    r"inside linebackers|defensive ends?|edge|nickels?|pitching|pitchers|hitting|hitters|catchers?|infield|"
    r"outfield|baserunning|goalies?|goalkeepers?|attack|midfield|defen[cs]e|offen[cs]e|faceoffs?|draw controls?",
    re.I)


def _looks_like_title(t: str) -> bool:
    """A job title, not another spelling of the person's name ("Sandra Moton" under a photo linked as Simmons)."""
    return bool(_TITLE_WORDS.search(t) or _POSITION_GROUP.search(t)) or not _NAME_OK.match(t)


def _people_in(el) -> int:
    """How many different people an element links to, by the names its bio links show. Photo-only links don't
    count: some sites link a coach's photo to an older address than the name (LSU: sandra-simmons, then moton)."""
    names = set()
    for x in el.find_all("a", href=True):
        if _BIO_LINK.search(x["href"]):
            n, sure = _name_of(x)
            if n and sure > 0:
                names.add(n.lower())
    return len(names)


def _title_near(a, name: str) -> str:
    """The job title in the card, list item or table row that holds the link: the largest box around the link
    that holds no one else, so one coach's title is never read off the next card."""
    row = a.find_parent("tr")
    if row is not None and _people_in(row) == 1:          # a table: the title is one of the row's cells
        for td in row.find_all(["td", "th"]):
            c = _clean(td.get_text(" "))
            if not c or c == name or name in c or td.find("a", href=_BIO_LINK) or "@" in c or len(c) > 200:
                continue
            if re.fullmatch(r"[\d\s().+\-/x]+|(?i:e-?mail|phone|bio|full bio|view bio)", c) or not re.search(r"[A-Za-z]{3}", c):
                continue
            return c                                       # Name | Title | Phone | Email: the first other cell
        return ""
    box = a
    for _ in range(7):
        parent = box.parent
        if parent is None or _people_in(parent) > 1:
            break
        box = parent
    shown = {n.lower() for x in box.find_all("a", href=True) if _BIO_LINK.search(x["href"])
             for n, sure in [_name_of(x)] if n and sure > 0} | {name.lower()}
    for el in box.find_all(class_=_TITLE_CLASS):          # an element marked as the title or position
        classes = " ".join(el.get("class", []))
        if _NAME_CLASS.search(classes) and not _TITLE_CLASS.search(classes.replace("name", "")):
            continue
        if (el.name == "a" and _BIO_LINK.search(el.get("href", ""))) or el.find("a", href=_BIO_LINK) \
                or (el.name in ("h2", "h3", "h4") and not _looks_like_title(_clean(el.get_text(" ")))):
            continue                                       # the name's heading or link ("roster-card-item__title" on WMT)
        t = _clean(el.get_text(" "))
        if t.lower() in shown:
            continue
        if t and t != name and name not in t and len(t) < 200 and "@" not in t:
            return t
    for t in box.stripped_strings:                        # else a short line that reads like a job title
        t = _clean(t)
        if t != name and name not in t and len(t) < 70 and _TITLE_WORDS.search(t) and "@" not in t \
                and not re.search(r"(?i)full bio|view bio|^email|^phone", t):
            return t
    return ""


def parse_staff(html: str, base_url: str = "") -> list[dict]:
    """[{name, title, bio_url}] for the coaches and staff on a page, in page order, each person once."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    for bad in soup.select("script, style, noscript, header nav, footer, .sidearm-roster-related"):
        bad.decompose()
    # One person per bio page: a card links its photo, its name and "Full Bio" to the same page
    people: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _BIO_LINK.search(href) or re.search(r"(?i)staff-directory|/coaches/?$|/staff/?$", href):
            continue
        key = re.sub(r"[?#].*$", "", href).rstrip("/").lower()
        name, sure = _name_of(a)
        if not name:
            continue
        p = people.get(key)
        if p is None:
            p = people[key] = {"name": name, "sure": sure, "title": "", "bio_url": urljoin(base_url, href) if base_url else href}
        elif sure > p["sure"]:
            p.update(name=name, sure=sure)
        if not p["title"]:
            p["title"] = _title_near(a, name)
    out, seen = [], set()
    for p in people.values():
        if p["name"].lower() in seen:
            continue
        seen.add(p["name"].lower())
        if p["title"] == p["name"] or p["name"] in p["title"]:
            p["title"] = ""
        out.append({"name": p["name"], "title": p["title"], "bio_url": p["bio_url"]})
    return out


# ---- roles ------------------------------------------------------------------------------------------------
ROLES = ["head", "associate", "assistant", "coordinator", "graduate", "volunteer", "support"]
ROLE_LABELS = {"head": "Head coach", "associate": "Associate head coach", "assistant": "Assistant coach",
               "coordinator": "Coordinator", "graduate": "Graduate assistant", "volunteer": "Volunteer assistant",
               "support": "Support staff"}


_OTHER_SPORTS = (r"soccer|basketball|track|cross country|volleyball|swim|diving|golf|tennis|wrestling|hockey|"
                 r"rowing|bowling|cheer|dance|esports|rifle|fencing|gymnastics|water polo|rugby|beach")


def role_of(title: str, sport_label: str = "") -> str:
    """One word for what the job is, from its title. "Interim Head Coach" is head; "Associate Head Coach /
    Pitching Coach" is associate; "Offensive Coordinator / QBs" is coordinator; trainers and directors are support."""
    t = (title or "").lower()
    if re.search(r"\bassociate head\b|\bassoc\.? head\b", t):
        return "associate"
    other = "women" if "men's" in sport_label.lower() and "women's" not in sport_label.lower() else \
        "men" if "women's" in sport_label.lower() else None
    own = "men" if other == "women" else "women" if other == "men" else None
    only_other = bool(other and re.search(rf"\b{other}'?s\b", t) and not re.search(rf"\b{own}'?s\b", t))
    sport_words = {"football", "baseball", "softball", "lacrosse"} - set(re.findall(r"[a-z]+", sport_label.lower()))
    not_head = re.search(r"equipment|manager|\basst\.?\s*(?:head|to)\b|associate to\b|emeritus|\bjv\b|junior varsity|"
                         r"academy|developmental|strength|conditioning|performance", t)
    # other sports' words, less this sport's own ("hockey" is another sport for lacrosse, not for hockey)
    own_words = set(re.findall(r"[a-z]+", sport_label.lower()))
    others = "|".join(w for w in _OTHER_SPORTS.split("|") if not set(w.split()) <= own_words)
    elsewhere = "|".join([r"field hockey"] + [rf"\b{w}\b" for w in sorted(sport_words)]) if sport_label else r"field hockey"
    # "Head Coach" in one part of the title ("Defensive Coordinator | Head Women's Flag Football Coach" is not)
    for part in re.split(r"\s*[/|;,&]\s*|\s+and\s+|\s+-\s+", t):
        if re.search(r"\bhead (?:coach|women'?s|men'?s|baseball|softball|football|lacrosse|ice hockey|hockey)\b|^head coach|\binterim head\b|"
                     r"\bhead coach\b", part) \
                and not re.search(r"\bassistant head\b|\bassistant to\b|\bassistant$|\bassistant\b.*\bhead coach\b|"
                                  r"head coach'?s?\b.*\b(?:assistant|staff|office)|special assistant|advisor|adviser|"
                                  r"chief of staff|strength|conditioning|athletic train|head (?:athletic )?trainer|"
                                  r"performance|flag football|" + others + "|" + elsewhere, part) \
                and not (other and re.search(rf"\bhead {other}'?s\b", part)) and not only_other and not not_head:
            return "head"
    if re.search(r"assistant to\b|asst\.? to\b|associate to\b|special asst|special assistant|chief of staff|"
                 r"executive assistant|head coach assistant|emeritus", t):
        return "support"
    if re.search(r"graduate|\bga\b|grad assistant", t):
        return "graduate"
    if re.search(r"volunteer", t):
        return "volunteer"
    if re.search(r"coordinator", t) and re.search(r"offens|defens|special teams|recruiting coordinator|pitching", t):
        return "coordinator"
    if re.search(r"coach", t) and not re.search(r"strength|conditioning|performance coach|mental|nutrition", t):
        return "assistant"
    # Football staffs often give only the position group ("Tight Ends", "Offensive Line"): an assistant coach
    if _POSITION_GROUP.search(t) and not re.search(r"director|analyst|quality control|operations|intern|"
                                                   r"strength|trainer|video|recruiting|personnel|manager", t):
        return "assistant"
    return "support"


# ==============================================================================================================
# Scraping staff (scrape)   (was scripts/scrape_staff.py)
# ==============================================================================================================

SCRAPE_STAFF_DOC = """Coaches and staff for every school-season, read from the roster pages the scraper already downloaded.

    python3 scripts/staff.py scrape --sport lacrosse-mens          # every season with a saved roster
    python3 scripts/staff.py scrape --sport softball --seasons 2025-2027
    python3 scripts/staff.py scrape --sport baseball --offline     # only pages already in .cache/html

Most sites list the coaching staff on the roster page (Sidearm, WMT), so the staff come from the page each saved
roster was read from, out of .cache/html, with nothing downloaded. When that page has no staff (a season whose
roster page left the staff section empty) or the site loads its staff separately (PrestoSports), the season's
coaches page is downloaded instead: /sports/<sport>/coaches/<year> (Sidearm) or the address the Presto page gives
(/sports/<sport>/2024-25/coaches). --offline skips those downloads.

Writes rosters/<sport>/staff_<season>.csv: season, division, current_conference, school, name, title, role
(head, associate, assistant, coordinator, graduate, volunteer, support), bio_url, source_url. A season file is
rewritten as a whole; school-seasons whose roster failed get no staff (there's no page to read).
"""
import argparse
import csv
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import core  # noqa: E402
from core import Fetcher  # noqa: E402
from core import ROOT, add_sport_argument, load_sport  # noqa: E402
from core import read_csv, season_files  # noqa: E402

FIELDS = ["season", "division", "current_conference", "school", "name", "title", "role", "bio_url", "source_url"]
CACHE = ROOT / ".cache" / "html"
_BIO = re.compile(r"/(?:roster/)?coaches/[^/\"'?#]+|/roster/(?:season/[^/]+/)?staff/[^/\"'?#]+", re.I)


def staff_part(html: str) -> str:
    """Only the part of a page around its coach links: parsing a whole 2 MB page for 10 coaches is slow."""
    hits = [m.start() for m in _BIO.finditer(html)]
    if not hits:
        return ""
    return html[max(0, hits[0] - 6000): hits[-1] + 6000]


def final_url_index(cache: Path) -> dict[str, Path]:
    """final address -> cached page, from the .url files next to the pages (a saved roster keeps the address it
    ended at, the cache the one asked for)."""
    out = {}
    with os.scandir(cache) as it:
        for e in it:
            if e.name.endswith(".url"):
                try:
                    out.setdefault(Path(e.path).read_text().strip(), Path(e.path).with_suffix(".html"))
                except OSError:
                    pass
    return out


def coaches_page(roster_url: str, html: str, season: int, spring: bool) -> str:
    """Where the season's coaching staff is when the roster page doesn't list it."""
    m = re.search(r'data-coaches-url="([^"]+)"', html or "")           # Presto says so itself
    if m:
        return urljoin(roster_url, m.group(1))
    u = urlparse(roster_url)
    code = re.search(r"/sports/([^/]+)/", u.path)
    if not code:
        return ""
    if re.search(r"/\d{4}-\d{2}/roster", u.path):                        # Presto without the attribute
        return f"{u.scheme}://{u.netloc}" + re.sub(r"/roster.*$", "/coaches", u.path)
    return f"{u.scheme}://{u.netloc}/sports/{code.group(1)}/coaches/{season}"   # Sidearm


_WORKER: dict = {}


def _init(sport_name: str, offline: bool, index: dict) -> None:
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sport = load_sport(sport_name)
    core.SPRING_SEASON = bool(sport.spring_season)
    _WORKER.update(fetcher=Fetcher(CACHE, delay=1.5, timeout=10), offline=offline, index=index,
                   spring=bool(sport.spring_season), label=sport.label or sport.name)


def _page(url: str, rendered: bool) -> str | None:
    f = _WORKER["fetcher"]
    for r in ((rendered, not rendered) if rendered else (False, True)):
        p = f._cache_path(url, r)
        if Fetcher.is_cached(p):
            return Fetcher.read_cached(p)
    p = _WORKER["index"].get(url)
    if p is not None and Fetcher.is_cached(p):
        return Fetcher.read_cached(p)
    return None


def one(job: tuple) -> tuple[tuple, list[dict], str]:
    """(season, school, url, strategy, row) -> (job, staff, where they came from: page, coaches, none, no-page)."""
    season, school, url, strategy, base = job
    html = _page(url, strategy.startswith("rendered:"))
    people, source, how = [], url, "no-page"
    if html is not None:
        people = parse_staff(staff_part(html), url)
        how = "page" if people else "none"
    if not people:
        extra = coaches_page(url, html or "", season, _WORKER["spring"])
        if extra:
            page = _page(extra, False)
            if page is None and not _WORKER["offline"]:
                try:
                    status, final, page = _WORKER["fetcher"].get(extra)
                    page = page if status == 200 and str(season) in final + page[:200000] else None
                except Exception:
                    page = None
            if page:
                people = parse_staff(staff_part(page), extra)
                if people:
                    source, how = extra, "coaches"
    rows = [{**base, "name": p["name"], "title": p["title"], "role": role_of(p["title"], _WORKER["label"]),
             "bio_url": p["bio_url"], "source_url": source} for p in people]
    return job, rows, how


def scrape_staff_main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=SCRAPE_STAFF_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    ap.add_argument("--seasons", help="e.g. 2016-2027 (default: every season with a saved roster)")
    ap.add_argument("--offline", action="store_true", help="only pages already downloaded; no coaches pages fetched")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4)))
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    rdir = sport.rosters_dir
    saved = season_files(rdir)
    if args.seasons:
        from scrape_rosters import parse_seasons
        wanted = set(parse_seasons(args.seasons))
        saved = {y: p for y, p in saved.items() if y in wanted}
    jobs = []
    for season, path in sorted(saved.items()):
        first = {}
        for r in read_csv(path):
            if r["school"] not in first and r.get("roster_url"):
                first[r["school"]] = r
        for school, r in first.items():
            base = {"season": season, "division": r.get("division", ""),
                    "current_conference": r.get("current_conference", ""), "school": school}
            jobs.append((season, school, r["roster_url"], r.get("strategy", ""), base))
    print(f"{sport.label or sport.name}: {len(jobs):,} school-seasons with a saved roster, "
          f"{len(saved)} seasons{' (offline: no downloads)' if args.offline else ''}", flush=True)
    index = final_url_index(CACHE)
    by_season: dict[int, list[dict]] = {y: [] for y in saved}
    how_count: dict[str, int] = {}
    heads = 0
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init,
                             initargs=(sport.name, args.offline, index)) as pool:
        for (season, school, *_), rows, how in pool.map(one, jobs, chunksize=8):
            by_season[season] += rows
            how_count[how] = how_count.get(how, 0) + 1
            heads += any(r["role"] == "head" for r in rows)
    for season, rows in by_season.items():
        with open(rdir / f"staff_{season}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    total = sum(len(v) for v in by_season.values())
    found = how_count.get("page", 0) + how_count.get("coaches", 0)
    print(f"staff for {found:,} of {len(jobs):,} school-seasons ({found / max(1, len(jobs)):.0%}), "
          f"{total:,} people-seasons; a head coach for {heads:,}")
    print(f"  from the roster page {how_count.get('page', 0):,}, from a coaches page {how_count.get('coaches', 0):,}, "
          f"page has none {how_count.get('none', 0):,}, page not downloaded {how_count.get('no-page', 0):,}")
    print(f"-> {rdir}/staff_<season>.csv")
    return 0


# ==============================================================================================================
# The staff data (build)   (was scripts/build_staff_data.py)
# ==============================================================================================================

BUILD_STAFF_DATA_DOC = 'Coaches and staff for the staff pages: one person per name across a sport\'s schools and seasons, their\nseasons at each school, and their moves between schools.\n\n    python3 scripts/staff.py build --sport football     # rosters/football/staff_*.csv -> docs/football/staff_data.json\n\nReads rosters/<sport>/staff_<season>.csv (staff.py scrape) and the schools, conferences and divisions from\ndocs/<sport>/map_data.json (build.py map, so run that first).\n\nPeople: the same name in the same sport is the same person ("Mike Smith Jr." and "Mike Smith" too, and "Mike A. Smith"\nwhen "Mike Smith" is listed somewhere). A name seen\nat two schools in the same season more than once is two people (a common name), and gets no moves. One season\nat two schools is fine: coaches change jobs mid-year and both pages list them.\n\nA move: the last season at one school, then the first season at the next (at most two seasons later), each with\nthe person\'s role there.\n'
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from core import add_sport_argument, load_sport  # noqa: E402

COACHING = {"head", "associate", "assistant", "coordinator", "graduate", "volunteer"}
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|dr|coach)\b\.?", re.I)


def person_key(name: str) -> str:
    n = _SUFFIX.sub(" ", name.lower().replace(".", " ").replace(",", " ").replace("’", "'"))
    return re.sub(r"\s+", " ", n).strip()


def load_rows(rdir: Path) -> list[dict]:
    rows = []
    for path in sorted(rdir.glob("staff_*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def build(rows: list[dict], schools: list[str]) -> dict:
    """people, their seasons (stints) and moves, as columns."""
    sidx = {s: i for i, s in enumerate(schools)}
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["school"] in sidx and r["name"].strip():
            by_key[person_key(r["name"])].append(r)
    # "Deion Prime Sanders", "John A. Smith": the same person as "Deion Sanders" when that name is listed too
    for key in [k for k in by_key if len(k.split()) > 2]:
        w = key.split()
        short = f"{w[0]} {w[-1]}"
        if short in by_key:
            by_key[short] += by_key.pop(key)
    names, titles, tidx = [], [], {}
    st = {"p": [], "s": [], "y": [], "r": [], "t": []}
    mv = {"p": [], "a": [], "b": [], "y": [], "ra": [], "rb": []}
    shared = 0

    def title_id(t: str) -> int:
        if t not in tidx:
            tidx[t] = len(titles)
            titles.append(t)
        return tidx[t]

    for key, rs in sorted(by_key.items()):
        per_season: dict[int, set] = defaultdict(set)
        for r in rs:
            per_season[int(r["season"])].add(r["school"])
        doubles = sum(1 for v in per_season.values() if len(v) > 1)
        # a common name: split into one person per school, with no moves
        groups = [rs] if doubles <= 1 else [[r for r in rs if r["school"] == s] for s in sorted({r["school"] for r in rs})]
        shared += doubles > 1
        for grp in groups:
            pid = len(names)
            names.append(max((r["name"] for r in grp), key=lambda n: (sum(r["name"] == n for r in grp), len(n))))
            seen = set()
            for r in sorted(grp, key=lambda r: (int(r["season"]), r["school"])):
                k = (int(r["season"]), r["school"])
                if k in seen:
                    continue
                seen.add(k)
                st["p"].append(pid); st["s"].append(sidx[r["school"]]); st["y"].append(int(r["season"]))
                st["r"].append(ROLES.index(r["role"]) if r["role"] in ROLES else ROLES.index("support"))
                st["t"].append(title_id(r["title"]))
            if len(groups) > 1:
                continue
            # moves: walk the seasons in order; a new school within two seasons of the last one is a move
            by_season = defaultdict(list)
            for r in grp:
                by_season[int(r["season"])].append(r)
            prev = None                           # (school, last season there, role)
            for y in sorted(by_season):
                here = by_season[y]
                schools_now = {r["school"] for r in here}
                if prev and prev[0] not in schools_now:
                    new = here[0]
                    if y - prev[1] <= 2:
                        mv["p"].append(pid); mv["a"].append(sidx[prev[0]]); mv["b"].append(sidx[new["school"]])
                        mv["y"].append(y); mv["ra"].append(ROLES.index(prev[2]) if prev[2] in ROLES else 6)
                        mv["rb"].append(ROLES.index(new["role"]) if new["role"] in ROLES else 6)
                    prev = (new["school"], y, new["role"])
                else:
                    keep = next((r for r in here if prev and r["school"] == prev[0]), here[0])
                    prev = (keep["school"], y, keep["role"])
    return {"people": "\n".join(names), "titles": titles, "stints": st, "moves": mv, "shared": shared}


def build_staff_data_main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=BUILD_STAFF_DATA_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    if not (sport.site_dir / "map_data.json").exists():
        print(f"{sport.label}: no {sport.site_dir / 'map_data.json'} yet (build.py map makes it); skipped")
        return 0
    md = json.loads((sport.site_dir / "map_data.json").read_text(encoding="utf-8"))
    rows = load_rows(sport.rosters_dir)
    for r in rows:   # the roles again, so a fix to role_of() reaches the pages without scraping again
        r["role"] = role_of(r["title"], sport.label)
    if not rows:
        print(f"{sport.label}: no staff rows in {sport.rosters_dir} (staff.py scrape finds them); skipped")
        return 0
    schools = [s[0] for s in md["schools"]]
    out = build(rows, schools)
    out.update(sport=md.get("sport", sport.label), schools=md["schools"], confs=md["confs"], divs=md["divs"],
               divLabels=md.get("divLabels", {}), d1=md.get("d1", []), roles=ROLES,
               roleLabels=[ROLE_LABELS[r] for r in ROLES])
    dst = sport.site_dir / "staff_data.json"
    dst.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    n_people = out["people"].count("\n") + 1
    mv = out["moves"]
    heads = sum(1 for r in mv["rb"] if ROLES[r] == "head")
    coach = sum(1 for a, b in zip(mv["ra"], mv["rb"]) if ROLES[a] in COACHING and ROLES[b] in COACHING)
    print(f"{n_people:,} people, {len(out['stints']['p']):,} person-seasons, {len(mv['p']):,} moves "
          f"({coach:,} coach to coach, {heads:,} into a head coaching job); {out['shared']:,} common names kept apart"
          f" -> {dst}")
    return 0


COMMANDS = {"scrape": scrape_staff_main, "build": build_staff_data_main}


def command_line(argv=None) -> int:
    """python3 scripts/staff.py <command> [options]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        sys.argv[0] = f"{Path(sys.argv[0]).name} {argv[0]}"     # so --help says "build.py map"
        return COMMANDS[argv[0]](argv[1:]) or 0
    sys.exit("commands: " + ", ".join(COMMANDS) + " (add --help to one for its options)")


if __name__ == "__main__":
    raise SystemExit(command_line())
