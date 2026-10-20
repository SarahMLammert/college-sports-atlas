from __future__ import annotations

"""Reading Sidearm and WMT athletics pages: building roster URLs, checking which season a page
shows, and pulling players out of it (five parsers, best result kept). Also the rules for telling a
previous college from a high school.

Sport-specific settings (roster URL paths, minimum roster size, junior-college names) come from
config/<sport>/sport.json through configure(), which the scripts call at startup."""
import json
import re
from itertools import zip_longest
from typing import Any, Callable, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from core.fetch import current_season
from core.hometowns import *            # noqa: F401,F403  clean, parse_hometown, normalize_class, ...
from core.hometowns import _PLACEHOLDERS, _key, _lookup   # noqa: F401

# Set by configure() from the sport's settings; these defaults are football's.
ROSTER_PATHS = ["/sports/football/roster"]
MIN_PLAYERS = 25  # fewer players than this on a page is suspicious
JUCO_NAMES: list[str] = []


def configure(sport) -> None:
    """Use a sport's roster URL paths, minimum roster size and junior-college names."""
    global ROSTER_PATHS, MIN_PLAYERS, JUCO_NAMES
    ROSTER_PATHS = list(sport.roster_paths)
    MIN_PLAYERS = sport.min_players
    JUCO_NAMES = list(sport.junior_colleges)


def _fill(template: str, season: int) -> str:
    return template.format(season=season, next_season=season + 1, next_yy=f"{(season + 1) % 100:02d}")


def candidate_urls(domain: str, override: str = "", season: int | None = None) -> list[str]:
    """Roster URLs to try, most likely first.

    ``season=None`` means the current roster page. For past seasons the list always has the same
    length and order for a given school, so the index of the URL that worked can be reused.
    ``roster_url`` overrides may contain {season}, {next_season} and {next_yy} (e.g. 2019-{next_yy} -> 2019-20).
    """
    urls: list[str] = []
    override = (override or "").strip()
    if override:
        if season is None:
            urls.append(_fill(override, current_season()))
        elif "{season}" in override:
            urls.append(_fill(override, season))
        else:  # plain URL: try the Sidearm and WMT archive conventions on it
            o, yy = override.rstrip("/"), f"{(season + 1) % 100:02d}"
            urls += [f"{o}/{season}", f"{o}/season/{season}/", f"{o}/{season}-{yy}", f"{o}/season/{season}-{yy}/"]
    base = f"https://{domain.strip().strip('/')}"
    for path in ROSTER_PATHS:
        path = path.rstrip("/")
        if season:
            yy = f"{(season + 1) % 100:02d}"
            urls.append(f"{base}{path}/{season}")                # Sidearm:  /roster/2019
            urls.append(f"{base}{path}/season/{season}/")        # WMT:      /roster/season/2019/
            urls.append(f"{base}{path}/{season}-{yy}")           # Sidearm:  /roster/2019-20 (Cornell, Ohio State)
            urls.append(f"{base}{path}/season/{season}-{yy}/")   # WMT:      /roster/season/2019-20/ (Notre Dame, Georgia Tech)
        else:
            urls.append(f"{base}{path}")
    if domain and not domain.startswith("www."):
        urls.append(f"https://www.{domain}{ROSTER_PATHS[0]}" + (f"/{season}" if season else ""))
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out



# =============================================================================
# Season check: which year an archive page is really showing
# =============================================================================
# Work out which season a roster page is showing, so archive URLs that silently fall back
# to the current roster are caught instead of being saved under the wrong year.

_YEAR = re.compile(r"\b(20[0-3]\d)(?:\s*[-–/]\s*(?:20)?(\d{2}))?\b")


def detect_season(html: str) -> int | None:
    soup = BeautifulSoup(html[:400_000], "lxml")
    candidates: list[str] = []
    if soup.title:  # .string is None when the title has child nodes; get_text() isn't
        candidates.append(soup.title.get_text(" "))
    for sel in ("select[name=season] option[selected]", "select option[selected]",
                "h1", "h2", "[class*=roster-title]", "[class*=season] [aria-selected=true]"):
        for el in soup.select(sel)[:3]:
            candidates.append(el.get_text(" "))
    for text in candidates:
        m = _YEAR.search(text or "")
        if m:
            return int(m.group(1))
    return None


# =============================================================================
# Parsing: pull players out of a roster page
# =============================================================================
# Roster page parsers.
#
# Each strategy takes raw HTML and returns a list of player dicts with these keys
# (any may be empty): name, first_name, last_name, jersey, position, class_year,
# height, weight, hometown, high_school, previous_school, bio_url.
#
# Strategies, tried in order by ``parse_roster``:
#   1. nuxt_data       - Nuxt 3 ``__NUXT_DATA__`` payload (Sidearm "nextgen" and WMT sites)
#   2. sidearm_classic - older Sidearm markup (li.sidearm-roster-player)
#   3. sidearm_cards   - Sidearm nextgen person cards (data-test-id attributes)
#   4. html_table      - any <table> whose header mentions Hometown
#   5. embedded_json   - any other <script> JSON blob (__NEXT_DATA__, ld+json, ...) with hometown keys

FIELDS = [
    "name", "first_name", "last_name", "jersey", "position", "class_year",
    "height", "weight", "hometown", "high_school", "previous_school", "bio_url",
]


def _blank() -> dict:
    return {f: "" for f in FIELDS}


# ---------------------------------------------------------------------------
# 1. Nuxt devalue payload
# ---------------------------------------------------------------------------

_WRAPPERS = {"ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}
_OPAQUE = {"Date", "Set", "Map", "RegExp", "BigInt", "Error", "NuxtError", "URL", "URLSearchParams"}


def decode_devalue(raw: list) -> Any:
    """Rehydrate a devalue-flattened array (the format Nuxt 3 uses for __NUXT_DATA__).

    Iterative rather than recursive: the old version raised the process-wide recursion limit,
    which raced between worker threads and could crash or silently drop a roster."""
    memo: dict[int, Any] = {}
    todo: list[tuple[Any, Any]] = []   # (empty container, source list/dict) still to fill

    def get(i):
        if not isinstance(i, int) or isinstance(i, bool):
            return i
        if i < 0 or i >= len(raw):  # -1 undefined, -2 hole, -3 NaN, ...
            return None
        if i in memo:
            return memo[i]
        j, hops = i, set()
        while True:  # unwrap Reactive/Ref/... chains
            v = raw[j]
            if isinstance(v, list) and v and isinstance(v[0], str) and v[0] in _WRAPPERS:
                nxt = v[1] if len(v) > 1 else -1
                if not isinstance(nxt, int) or nxt < 0 or nxt >= len(raw) or nxt in hops:
                    memo[i] = None
                    return None
                hops.add(j)
                j = nxt
                if j in memo:
                    memo[i] = memo[j]
                    return memo[j]
                continue
            break
        v = raw[j]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _OPAQUE:
                out = None
            else:
                out = []
                todo.append((out, v))
        elif isinstance(v, dict):
            out = {}
            todo.append((out, v))
        else:
            out = v
        memo[i] = memo[j] = out
        return out

    root = get(0)
    while todo:
        container, src = todo.pop()
        if isinstance(container, list):
            container.extend(get(x) for x in src)
        else:
            for k, x in src.items():
                container[k] = get(x)
    return root


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", k.lower())


def _text(v) -> str:
    """Flatten a JSON value to display text (dicts like {'abbreviation': 'QB', 'name': ...})."""
    if v is None:
        return ""
    if isinstance(v, dict):
        for k in ("abbreviation", "abbrev", "short", "shortName", "name", "title", "value", "text"):
            if v.get(k):
                return clean(v[k])
        return ""
    if isinstance(v, list):
        return ", ".join(t for t in (_text(x) for x in v) if t)
    return clean(v)


# Candidate JSON keys (already passed through _norm_key) for each output field, best first.
_KEYMAP = {
    "first_name": ["firstname", "first"],
    "last_name": ["lastname", "last"],
    "name": ["fullname", "displayname", "playername", "name"],
    "jersey": ["jerseynumber", "jerseynumberlabel", "jersey", "number", "uniformnumber", "no"],
    "position": ["positionshort", "playerposition", "positionabbreviation", "position", "pos",
                 "positionlong"],
    "class_year": ["academicyearshort", "academicyear", "classlevel", "academicyearlong",
                   "classyear", "class", "year", "eligibility", "yr"],
    "hometown": ["hometown", "homecity", "hometowncity"],
    "high_school": ["highschool", "hs", "highschoolname", "lastschool"],
    # "Last School" is a high school for freshmen and a college for transfers; sort_schools() decides which.
    "previous_school": ["previousschool", "previousschools", "previousschoolname", "prevschool", "priorschool",
                        "formerschool", "transferschool", "transferfrom", "transferredfrom", "previouscollege",
                        "lastcollege", "college"],
    "weight": ["weight", "wt"],
    "bio_url": ["calltoaction", "relativeurl", "url", "permalink", "biourl"],
}


# Fields a wrapper object may supply for the player it contains (WMT puts season-specific
# position/class/jersey on the roster entry and hometown etc. on the nested ``player``).
_PARENT_FIELDS = ("position", "class_year", "jersey", "bio_url")


def _pick(d: dict, field: str) -> str:
    for k in _KEYMAP[field]:
        if k in d:
            t = _text(d[k])
            if t:
                return t
    return ""


def _record_from_json(obj: dict, parent: dict | None = None) -> dict | None:
    d = {_norm_key(k): v for k, v in obj.items()}
    rec = _blank()
    for field in _KEYMAP:
        rec[field] = _pick(d, field)
    if parent:
        p = {_norm_key(k): v for k, v in parent.items()}
        for field in _PARENT_FIELDS:
            val = _pick(p, field)
            if val:
                rec[field] = val
        for field in ("high_school", "previous_school"):   # only to fill a blank: the player's own record wins
            if not rec[field]:
                rec[field] = _pick(p, field)

    rec["height"] = format_height(d.get("heightfeet"), d.get("heightinches"),
                                  _text(d.get("height") or d.get("heightdisplay") or ""))
    rec["weight"] = clean_weight(rec["weight"])

    if rec["first_name"] or rec["last_name"]:
        full = clean(f"{rec['first_name']} {rec['last_name']}")
        if not rec["name"]:
            rec["name"] = full
    if not rec["name"]:
        return None
    if rec["hometown"] and not rec["high_school"]:
        ht, hs = split_hometown_highschool(rec["hometown"])
        if hs:
            rec["hometown"], rec["high_school"] = ht, hs
    return rec


# ---------------------------------------------------------------------------
# Staff filter: coaches, managers, trainers and other support staff share the roster page (and
# often the same markup or JSON shape) with players. Every parser runs its results through this.
# ---------------------------------------------------------------------------

STAFF_WORDS = re.compile(
    r"\b(coach(es|ing)?|coordinator|manager|mgr|trainer|athletic training|director|analyst|"
    r"graduate assistant|grad assistant|quality control|intern|staff|operations|recruiting|"
    r"equipment|video|strength|conditioning|nutrition(ist)?|dietitian|chaplain|physician|doctor|"
    r"sports medicine|therapist|psycholog\w*|administrat\w*|advisor|consultant|"
    r"personnel|scouting|student assistant|assistant|support|team services|"
    r"chief of staff|general manager|gm|creative|social media|photographer|mascot)\b",
    re.I,
)
# Only checked against a record's position, class and job-title fields, never its name or school.
# Words that can describe players are left out: "Medical Redshirt" is a class, "Scout team" a note.
# JSON keys that hold a staff member's job title:
_STAFF_KEYS = {"title", "jobtitle", "stafftitle", "positiontitle", "role", "stafftype", "type"}


def staff_text_hit(*texts: str) -> bool:
    return any(t and STAFF_WORDS.search(t) for t in texts)


def is_staff(rec: dict) -> bool:
    """A scraped record whose position or class column holds a job title ("Head Coach",
    "Student Manager", "Director of Football Operations") is staff, not a player."""
    return staff_text_hit(rec.get("position", ""), rec.get("class_year", ""), rec.get("staff_title", ""))


def drop_staff(rows: list[dict]) -> list[dict]:
    rows = [r for r in rows if not is_staff(r)]
    # Players nearly always have a position or jersey number; staff almost never do. If most of
    # the page has them, a record with neither (and no class or size) is support staff.
    def has_player_fields(r):
        return any(r.get(f) for f in ("position", "jersey", "class_year", "height", "weight"))
    if rows and sum(1 for r in rows if r.get("position") or r.get("jersey")) >= 0.8 * len(rows):
        rows = [r for r in rows if has_player_fields(r)]
    return rows


_STAFF_SECTIONS = re.compile(r"coach|staff|manager|support|trainer|administration", re.I)


def _looks_like_player(d: dict) -> bool:
    keys = {_norm_key(k) for k in d}
    has_home = bool(keys & {"hometown", "homecity", "hometowncity"})
    has_name = bool(keys & {"firstname", "lastname", "fullname", "name", "displayname"})
    return has_home and has_name


def players_from_json_tree(root: Any) -> list[dict]:
    """Walk any decoded JSON tree, collecting player-like dicts (with their parent for context)."""
    out: list[dict] = []
    seen: set[int] = set()
    # (node, parent dict, key it was stored under). Anything under a key like "coaches",
    # "staff" or "support_staff" is skipped, whatever it looks like.
    stack: list[tuple[Any, dict | None, str]] = [(root, None, "")]
    while stack:
        node, parent, key = stack.pop()
        if _STAFF_SECTIONS.search(key):
            continue
        if isinstance(node, dict):
            if id(node) in seen:
                continue
            seen.add(id(node))
            if _looks_like_player(node):
                rec = _record_from_json(node, parent)
                if rec:
                    titles = [_text(v) for d in (node, parent or {}) for k, v in d.items()
                              if _norm_key(k) in _STAFF_KEYS and not isinstance(v, (dict, list))]
                    rec["staff_title"] = " / ".join(t for t in titles if t)
                    out.append(rec)
                continue
            for k, v in node.items():
                stack.append((v, node, str(k)))
        elif isinstance(node, list):
            if id(node) in seen:
                continue
            seen.add(id(node))
            for v in node:
                stack.append((v, None, key))
    out.reverse()  # stack order -> document order
    return out


def parse_nuxt_data(html: str, soup: BeautifulSoup) -> list[dict]:
    tag = soup.find("script", id="__NUXT_DATA__")
    if not tag or not tag.string:
        return []
    try:
        raw = json.loads(tag.string)
    except json.JSONDecodeError:
        return []
    root = decode_devalue(raw) if isinstance(raw, list) else raw
    return _dedupe(players_from_json_tree(root))


# ---------------------------------------------------------------------------
# 2. Classic Sidearm markup
# ---------------------------------------------------------------------------

def _sel_text(node: Tag, selector: str) -> str:
    el = node.select_one(selector)
    return clean(el.get_text(" ")) if el else ""


def parse_sidearm_classic(html: str, soup: BeautifulSoup) -> list[dict]:
    out = []
    for li in soup.select("li.sidearm-roster-player"):
        if _in_staff_section(li):
            continue
        rec = _blank()
        name_el = li.select_one(".sidearm-roster-player-name h3 a, .sidearm-roster-player-name a, "
                                ".sidearm-roster-player-name h3, .sidearm-roster-player-name")
        rec["name"] = clean(name_el.get_text(" ")) if name_el else ""
        if name_el is not None and name_el.name == "a":
            rec["bio_url"] = name_el.get("href", "")
        rec["jersey"] = _sel_text(li, ".sidearm-roster-player-jersey-number")
        rec["position"] = _sel_text(li, ".sidearm-roster-player-position-long-short, .sidearm-roster-player-position > span:first-child, .sidearm-roster-player-position")
        rec["class_year"] = _sel_text(li, ".sidearm-roster-player-academic-year")
        rec["height"] = format_height(raw=_sel_text(li, ".sidearm-roster-player-height"))
        rec["weight"] = clean_weight(_sel_text(li, ".sidearm-roster-player-weight"))
        # Exact classes only: "sidearm-roster-player-class-hometown" is a wrapper that can hold
        # nothing but the class year ("R-Fr.") when a season has no hometowns on file.
        rec["hometown"] = _sel_text(li, ".sidearm-roster-player-hometown")
        rec["high_school"] = _sel_text(li, ".sidearm-roster-player-highschool")
        rec["previous_school"] = _sel_text(li, ".sidearm-roster-player-previous-school")
        # Position text often runs into height/weight ("Wide Receiver 6'2\" 195 lbs"); cut at the
        # first number instead of the first space, so "Wide Receiver" doesn't become "Wide".
        rec["position"] = re.split(r"\s+(?=\d)", rec["position"])[0].strip() if rec["position"] else ""
        if rec["name"]:
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 3. Sidearm nextgen person cards (HTML, used if the JSON payload is missing)
# ---------------------------------------------------------------------------

def _in_staff_section(node: Tag) -> bool:
    """True if the element sits inside a block whose id/class/heading marks it as coaches or staff
    (Sidearm: #sidearm-roster-coaches, .s-person-card-list--staff, a "Coaching Staff" heading)."""
    for anc in node.parents:
        if not isinstance(anc, Tag) or anc.name in ("body", "html", "[document]"):
            break
        attrs = " ".join([anc.get("id", ""), " ".join(anc.get("class", [])), anc.get("data-test-id", ""),
                          anc.get("aria-label", "")])
        if re.search(r"coach|staff", attrs, re.I):
            return True
        if anc.name in ("section", "div"):
            head = anc.find(["h2", "h3"], recursive=False)
            if head is not None and re.search(r"\b(coach|staff|support|manager)", head.get_text(" "), re.I) \
                    and not re.search(r"\broster\b|\bplayers?\b", head.get_text(" "), re.I):
                return True
    return False


def _strip_label(node: Tag | None) -> str:
    if node is None:
        return ""
    node = BeautifulSoup(str(node), "lxml")
    for sr in node.select(".sr-only"):
        sr.decompose()
    text = clean(node.get_text(" "))
    return re.sub(r"^(Hometown|Last School|High School|Previous School|Position|Academic Year|Height|Weight)\s*:?\s*", "", text, flags=re.I)


def parse_sidearm_cards(html: str, soup: BeautifulSoup) -> list[dict]:
    out = []
    for card in soup.select('[data-test-id="s-person-card-list__root"], .s-person-card'):
        if _in_staff_section(card):
            continue
        rec = _blank()
        a = card.select_one('[data-test-id="s-person-details__personal-single-line-person-link"]') or card.select_one("h3")
        if a is None:
            continue
        rec["name"] = clean(a.get_text(" "))
        if a.name == "a":
            rec["bio_url"] = a.get("href", "")
        g = lambda tid: _strip_label(card.select_one(f'[data-test-id="{tid}"]'))
        rec["position"] = g("s-person-details__bio-stats-person-position-short")
        rec["class_year"] = g("s-person-details__bio-stats-person-title")
        rec["height"] = format_height(raw=g("s-person-details__bio-stats-person-season"))
        rec["weight"] = clean_weight(g("s-person-details__bio-stats-person-weight"))
        rec["hometown"] = g("s-person-card-list__content-location-person-hometown")
        rec["high_school"] = g("s-person-card-list__content-location-person-high-school")
        rec["previous_school"] = g("s-person-card-list__content-location-person-previous-school")
        stamp = card.select_one('[data-test-id="s-stamp__root"]')
        rec["jersey"] = re.sub(r"\D", "", _strip_label(stamp)) if stamp else ""
        if rec["name"]:
            out.append(rec)
    # Staff cards put their job title where players have their class ("Head Coach"); drop_staff
    # (run on every parser's result) removes them.
    return out


# ---------------------------------------------------------------------------
# 4. Generic HTML table
# ---------------------------------------------------------------------------

_HEADER_FIELDS = [
    (r"hometown\s*/\s*(high school|last school|previous school)", "hometown_hs"),
    (r"hometown", "hometown"),
    (r"(high\s*school|^hs).*/.*(previous|prior|transfer|college)", "hs_prev"),
    (r"high\s*school|last\s*school|^hs$", "high_school"),
    (r"previous|transfer|prior|former|^college$|^last college$", "previous_school"),
    (r"^(#|no\.?|num|number|jersey)$", "jersey"),
    (r"first\s*name", "first_name"),
    (r"last\s*name", "last_name"),
    (r"name|player", "name"),
    (r"^pos", "position"),
    (r"^(cl|class|yr|year|academic|elig)", "class_year"),
    (r"^(ht|height)", "height"),
    (r"^(wt|weight)", "weight"),
]


def _header_field(text: str) -> str | None:
    t = clean(text).lower()
    for pattern, field in _HEADER_FIELDS:
        if re.search(pattern, t):
            return field
    return None


def _name_from_link(cell: Tag) -> str:
    """Some sites (PrestoSports) render the visible name with JS; fall back to link metadata."""
    a = cell.find("a")
    if a is None:
        return ""
    for attr in ("aria-label", "title", "data-player-name"):
        v = clean(a.get(attr, ""))
        if v:
            return clean(re.split(r":|\bjersey\b|\bfull bio\b", v, flags=re.I)[0])
    img = a.find("img")
    if img is not None and clean(img.get("alt", "")):
        return clean(img["alt"])
    m = re.search(r"/bios?/([a-z0-9_\-]+?)(?:_[a-z0-9]{5,})?(?:\?|$)", a.get("href", ""), flags=re.I)
    if m:
        return " ".join(w.capitalize() for w in re.split(r"[_\-]+", m.group(1)) if w)
    return ""


def parse_html_tables(html: str, soup: BeautifulSoup) -> list[dict]:
    best: list[dict] = []
    for table in soup.find_all("table"):
        header_row = table.find("thead")
        header_cells = header_row.find_all(["th", "td"]) if header_row else []
        if not header_cells:
            first = table.find("tr")
            header_cells = first.find_all(["th", "td"]) if first else []
        headers = [_header_field(c.get_text(" ")) for c in header_cells]
        header_text = [clean(c.get_text(" ")).lower() for c in header_cells]
        if any(h in ("title", "position/title", "staff", "coaching staff", "support staff") for h in header_text):
            continue  # a staff table, even if it also lists hometowns
        cap = table.find("caption")
        if (cap is not None and _STAFF_SECTIONS.search(cap.get_text(" "))) or _in_staff_section(table):
            continue
        if "hometown" not in headers and "hometown_hs" not in headers:
            continue
        if "name" not in headers and "last_name" not in headers:
            continue
        body_rows = table.select("tbody tr") or table.find_all("tr")[1:]
        rows = []
        for tr in body_rows:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(headers) - 1:
                continue
            # Some sites repeat the header row inside the table (once per position group). Those
            # rows used to come through as a "player" named "Name" from the hometown "Hometown".
            same = sum(1 for c, h in zip(cells, header_text) if h and clean(c.get_text(" ")).lower() == h)
            if same >= 2:
                continue
            rec = _blank()
            for field, cell in zip_longest(headers, cells):
                if cell is None:
                    continue
                val = clean(cell.get_text(" "))
                m = _CELL_LABEL.match(val)
                if m:  # PrestoSports-style responsive cells carry their own label; trust it
                    field = _header_field(m.group(1)) or field
                    val = val[m.end():].strip()
                if not field:
                    continue
                if field == "name" and not val:
                    val = _name_from_link(cell)
                if field == "hometown_hs":
                    rec["hometown"], rec["high_school"] = split_hometown_highschool(val)
                elif field == "hs_prev":
                    rec["high_school"], rec["previous_school"] = split_hometown_highschool(val)
                elif not rec.get(field):
                    rec[field] = val
                if field == "name":
                    a = cell.find("a")
                    if a and a.get("href"):
                        rec["bio_url"] = a["href"]
            if not rec["name"] and (rec["first_name"] or rec["last_name"]):
                rec["name"] = clean(f"{rec['first_name']} {rec['last_name']}")
            rec["height"] = format_height(raw=rec["height"])
            rec["weight"] = clean_weight(rec["weight"])
            if rec["name"]:
                rows.append(rec)
        if len(rows) > len(best):
            best = rows
    return best


# ---------------------------------------------------------------------------
# 5. Any other embedded JSON
# ---------------------------------------------------------------------------

def parse_embedded_json(html: str, soup: BeautifulSoup) -> list[dict]:
    best: list[dict] = []
    for tag in soup.find_all("script"):
        txt = tag.string or tag.get_text() or ""
        if "hometown" not in txt.lower() or tag.get("id") == "__NUXT_DATA__":
            continue
        for blob in _json_candidates(txt):
            players = _dedupe(players_from_json_tree(blob))
            if len(players) > len(best):
                best = players
    return best


def _json_candidates(txt: str) -> Iterable[Any]:
    txt = txt.strip()
    try:
        yield json.loads(txt)
        return
    except (json.JSONDecodeError, ValueError):
        pass
    # JSON assigned in JS: window.__DATA__ = {...};  Scan for balanced top-level objects/arrays.
    # After a successful decode, jump past it: scanning inside it again is quadratic on big blobs.
    dec = json.JSONDecoder()
    pat = re.compile(r"[\[{]")
    pos = 0
    while True:
        m = pat.search(txt, pos)
        if not m:
            return
        start = m.start()
        window = txt[max(0, start - 3): start]
        if "=" not in window and ":" not in window and start != 0 and "(" not in window:
            pos = start + 1
            continue
        try:
            obj, end = dec.raw_decode(txt, start)
        except (json.JSONDecodeError, ValueError):
            pos = start + 1
            continue
        pos = end
        if "hometown" in txt[start:end].lower():
            yield obj


# ---------------------------------------------------------------------------

def _merge_into(kept: dict, r: dict) -> None:
    for f, v in r.items():
        if v and not kept.get(f):
            kept[f] = v


def _dedupe(rows: list[dict]) -> list[dict]:
    """Collapse repeats of the same player, filling blanks from the other copies.

    Same name + same hometown is one player. Some pages list everyone twice (a grid view and a
    list view) and one copy has no hometown; that copy is folded into the one same-named player
    who has a hometown. Two players who share a name but not a hometown stay separate."""
    by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (r["name"].lower(), r["hometown"].lower())
        if key not in by_key:
            by_key[key] = dict(r)
        else:
            _merge_into(by_key[key], r)
    with_home: dict[str, list[tuple]] = {}
    for name, home in by_key:
        if home:
            with_home.setdefault(name, []).append((name, home))
    for key in [k for k in by_key if not k[1]]:
        if len(with_home.get(key[0], [])) == 1:
            _merge_into(by_key[with_home[key[0]][0]], by_key.pop(key))
    return list(by_key.values())


STRATEGIES: list[tuple[str, Callable[[str, BeautifulSoup], list[dict]]]] = [
    ("nuxt_data", parse_nuxt_data),
    ("sidearm_classic", parse_sidearm_classic),
    ("sidearm_cards", parse_sidearm_cards),
    ("html_table", parse_html_tables),
    ("embedded_json", parse_embedded_json),
]



_CELL_LABEL = re.compile(
    r"^(No\.?|#|Jersey|Name|Full Name|Pos\.?|Position|Cl\.?|Class|Yr\.?|Year|Academic Year|Elig\.?|"
    r"Ht\.?|Height|Wt\.?|Weight|Hometown(?:\s*/\s*[A-Za-z ]+)?|High School|Last School|"
    r"Previous Schools?|Prev\. School|Former School|College|Experience|Exp\.?)\s*:\s*",
    re.I,
)
_CLASS_ONLY = re.compile(
    r"(?i)(r|rs|red|redshirt|medical redshirt)?[\s\-.]*"
    r"(fr|fy|so|jr|sr|gr|gs|freshman|sophomore|junior|senior|graduate|grad|5th|6th|"
    r"fifth|sixth)(\s*year)?\.?")
_HS_WORDS = re.compile(r"\b(hs|h\.s\.|high|academy|prep|preparatory|school)\b", re.I)


# Telling a college from a high school, for fields like "Last School" that can hold either.
# Filled with the names in config/schools.csv when the scraper starts (see main()).
KNOWN_COLLEGES: set[str] = set()
# Junior colleges whose roster names often leave out "College"/"CC" come from the sport's settings
# (JUCO_NAMES, set by configure()): multi-word or distinctive names only, since a single common
# word like "Independence" or "Highland" is also a high school name.
_HS_STRONG = re.compile(r"\b(high school|h\.s\.|hs|prep|preparatory|secondary)\b", re.I)
_COLLEGE_WORDS = re.compile(r"\b(university|univ\.?|college|community college|institute|polytechnic|state|tech|a&m|"
                            r"naval academy|air force academy|u\.?s\.? military academy|west point)\b", re.I)
_JUCO = re.compile(r"\b(CC|JC|JUCO)\b")          # capitals only: "C.C. Winn" is a high school in Laredo


def _college_key(v: str) -> str:
    v = re.sub(r"\((fl|fla|oh|ohio|pa)\.?\)", "", v.lower())          # "Miami (FL)" -> "miami"
    return re.sub(r"[^a-z&]", "", re.sub(r"^(the|university of)\s+", "", v.strip()))


def load_known_colleges(schools: list[dict]) -> None:
    """D1 schools from the sport's schools.csv plus its junior colleges (JUCO_NAMES)."""
    KNOWN_COLLEGES.update(_college_key(s["school"]) for s in schools)
    KNOWN_COLLEGES.update(_college_key(n) for n in JUCO_NAMES)


def looks_like_college(value: str) -> bool:
    """'Texas Tech', 'Wake Forest', 'Blinn College', 'Butler CC', 'Univ. of Iowa' -> True.
    'Lamar HS', 'IMG Academy', 'Mater Dei', 'College Park High School', 'Fork Union Military Academy' -> False."""
    v = clean(value)
    if not v or _HS_STRONG.search(v):
        return False
    if re.search(r"\b(university|college|naval academy|air force academy|military academy at|west point)\b", v, re.I) \
            and not re.search(r"\bmilitary academy\b(?! at)", v, re.I):
        return True
    if _JUCO.search(v):
        return True
    if _COLLEGE_WORDS.search(v) and not re.search(r"\b(academy|school)\b", v, re.I):
        return True                                          # "Texas Tech", "Penn State", "Prairie View A&M"
    return _college_key(v) in KNOWN_COLLEGES                 # "Wake Forest", "Notre Dame", "SMU"


def _same_school(a: str, b: str) -> bool:
    """'Menard' and 'Menard HS', or 'Rancho Cucamonga' and 'Rancho Cucamonga High School (Calif.)', are one school."""
    def n(v):
        v = re.sub(r"\([^)]*\)", "", v.lower())                                  # "(Calif.)", "(Pa.)"
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(high school|h\.?s\.?|school|the)\b", "", v))
    x, y = n(a or ""), n(b or "")
    if not x or not y:
        return False
    short, long_ = sorted((x, y), key=len)
    return x == y or (len(short) >= 5 and long_.startswith(short))


def sort_schools(p: dict) -> dict:
    """Put a college in previous_school and a high school in high_school, whichever field the site used.

    'Lamar HS / Texas Tech' in one field   -> high_school 'Lamar HS', previous_school 'Texas Tech'
    'Wake Forest' under "Last School"       -> previous_school 'Wake Forest'
    high school and college swapped         -> swapped back
    two separate fields the site filled     -> kept as they are otherwise ("Saddleback" stays a previous school)
    only a "previous school", not a college -> it's his high school (some sites file every high school there)
    previous school = the high school       -> dropped ('Menard' next to 'Menard HS')"""
    def parts(v):
        return [clean(x) for x in re.split(r"\s+/\s+|\s*;\s*", v or "") if clean(x)]
    hs_parts, prev_parts = parts(p.get("high_school")), parts(p.get("previous_school"))
    hs, prev = " / ".join(hs_parts), " / ".join(prev_parts)
    if len(hs_parts) > 1 or len(prev_parts) > 1:              # combined values
        every = hs_parts + prev_parts
        colleges = [x for x in every if looks_like_college(x)]
        others = [x for x in every if x not in colleges]
        hs = next((x for x in others if _HS_WORDS.search(x)), others[0] if others else "")
        if colleges:
            prev = colleges[-1]                               # most recent college is usually listed last
        elif len(prev_parts) == 1 and prev_parts[0] != hs:
            prev = prev_parts[0]                              # the site's own previous-school field
        else:
            prev = ""
    elif hs and looks_like_college(hs):
        if not prev:
            hs, prev = "", hs
        elif not looks_like_college(prev):
            hs, prev = prev, hs                               # the two were swapped
    elif prev and not hs and not looks_like_college(prev):
        hs, prev = prev, ""                                   # a high school filed as the previous school
    if _same_school(hs, prev):
        prev = ""
    elif prev and not looks_like_college(prev) and (_HS_STRONG.search(prev) or re.search(r"\bacademy\b", prev, re.I)):
        hs, prev = hs or prev, ""                             # clearly a high school: never a transfer
    p["high_school"], p["previous_school"] = hs, prev
    return p


def _undouble(name: str) -> str:
    """'Dami Adekunjo Dami Adekunjo' (name text plus a hidden copy) -> 'Dami Adekunjo'."""
    w = name.split()
    half = len(w) // 2
    if len(w) >= 4 and len(w) % 2 == 0 and [x.lower() for x in w[:half]] == [x.lower() for x in w[half:]]:
        return " ".join(w[:half])
    return name


_CAPTAIN = re.compile(r"\(\s*c\s*\)|©|\(\s*captain\s*\)|\s+-\s*captain\b|\*+", re.I)


def clean_name(name: str) -> str:
    """Strip roster decorations from a player's name:
    '89 Mason Thomas', '#89 Mason Thomas', 'Mason Thomas 89'  -> 'Mason Thomas'
    'C Mason Thomas', 'C 89 Mason Thomas', 'Mason Thomas (C)', 'Mason Thomas*' -> 'Mason Thomas'
    'Dami Adekunjo Dami Adekunjo' -> 'Dami Adekunjo'
    A real initial is kept: 'C.J. Stroud', 'CJ Stroud' and 'C J Stroud' are left alone."""
    n = clean(_CAPTAIN.sub(" ", name or ""))
    for _ in range(3):  # markers can be stacked: "C #89 Mason Thomas"
        before = n
        n = re.sub(r"^#?\d{1,3}\s+(?=\D)", "", n)               # leading jersey number
        n = re.sub(r"\s+#?\d{1,3}$", "", n)                       # trailing jersey number
        words = n.split()
        # a lone leading "C" is a captain marker when a full name (2+ words, not initials) follows
        if len(words) >= 3 and words[0] in ("C", "C:", "C.") and len(words[1].strip(".")) > 1:
            n = " ".join(words[1:])
        if n == before:
            break
    return _undouble(n.strip(" -,"))


def tidy_players(players: list[dict]) -> list[dict]:
    for p in players:
        for f in ("position", "class_year", "hometown", "high_school", "previous_school", "height", "weight", "jersey"):
            if p.get(f):
                p[f] = _CELL_LABEL.sub("", p[f]).strip()
        # A class year is never a hometown ("R-Fr.", "Sophomore", "Gr.")
        if p.get("hometown") and _CLASS_ONLY.fullmatch(p["hometown"].strip()):
            p["hometown"] = ""
        # "25 Jalyn Williams", "C Mason Thomas", "Mason Thomas (C)" -> the bare name
        p["name"] = clean_name(p.get("name", ""))
        # Hometown sitting in a school column: "Clinton, Md. / Glen Burnie HS"
        if not p.get("hometown"):
            for f in ("high_school", "previous_school"):
                v = p.get(f, "")
                if "/" not in v:
                    continue
                town, school = split_hometown_highschool(v)
                h = parse_hometown(town)
                if h["state"] or (h["country"] and h["city"]):
                    p["hometown"], p[f] = town, ""
                    dest = "high_school" if _HS_WORDS.search(school) else "previous_school"
                    if p.get(dest):
                        dest = f
                    p[dest] = school
                    break
        sort_schools(p)
    return players


def parse_roster(html: str) -> tuple[str, list[dict]]:
    """Run every strategy; return (strategy_name, players) for the best result."""
    soup = BeautifulSoup(html, "lxml")
    best_name, best = "", []
    for name, fn in STRATEGIES:
        try:
            players = tidy_players(drop_staff(fn(html, soup)))
        except Exception:  # one broken strategy shouldn't sink the page
            players = []
        with_home = sum(1 for p in players if p["hometown"])
        best_home = sum(1 for p in best if p["hometown"])
        if with_home > best_home or (with_home == best_home and len(players) > len(best)):
            best_name, best = name, players
        if len(players) >= MIN_PLAYERS and with_home >= 0.8 * len(players):
            break  # good enough, skip slower strategies
    for p in best:
        p.pop("staff_title", None)
        if p["hometown"].strip().lower().rstrip(":. ") in _PLACEHOLDERS:
            p["hometown"] = ""
    return best_name, _dedupe(best)
