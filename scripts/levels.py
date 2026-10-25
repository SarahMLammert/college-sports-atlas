"""Which level a transfer's previous school was at: D1, D2, D3, NAIA, JUCO, club or unknown.

Every college is a row in config/<sport>_schools.csv: the D1 schools, the seasons some of them spent in
another division, and the D2, D3, NAIA and junior colleges, with other spellings in its aliases column
(separated by "|"). A row can be limited to a range of seasons, so "Tarleton State" means Division II
for a player who left before 2020 and D1 after. Rows with division HS are high schools whose name looks
like a college ("St. John's College"), so they stay unknown. Rows with division CLUB are club (non-varsity)
teams, such as lacrosse's MCLA teams: never scraped, only a level for transfers.

    levels = Levels.load(sport)
    levels.level("Valdosta St.", 2018)        -> ("D2", "Valdosta State")
    levels.level("Hutchinson (Kan.) CC", 2022) -> ("JUCO", "")

Spellings are compared by key(): lowercase words without "University", "the", "of", "at" or punctuation,
"St." read as "State" at the end of a name and "Saint" elsewhere, "UW-" as "Wisconsin", and a
parenthetical state ("(Kan.)", "(MO)") kept as a postal code. A name that fits schools at two different
levels ("Bethel", "Concordia") comes back unknown rather than guessed."""
from __future__ import annotations

import csv
import re
from pathlib import Path

LEVELS = ["D1", "D2", "D3", "NAIA", "JUCO", "CLUB", "unknown"]
LEVEL_NAMES = {"D1": "Division I", "D2": "Division II", "D3": "Division III", "NAIA": "NAIA",
               "JUCO": "Junior college", "CLUB": "Club team", "unknown": "Unknown"}

_DROP = {"the", "of", "at", "university", "univ", "suny", "in"}
_EXPAND = {"mt": "mount", "uw": "wisconsin", "wis": "wisconsin", "unc": "north carolina",
           "ft": "fort", "miss": "mississippi", "okla": "oklahoma", "ark": "arkansas", "tenn": "tennessee",
           "ala": "alabama", "ga": "georgia", "kan": "kansas", "neb": "nebraska", "minn": "minnesota",
           "mich": "michigan", "conn": "connecticut", "nw": "northwest", "sw": "southwest",
           "colo": "colorado", "calif": "california", "wva": "west virginia", "ne": "northeast",
           "se": "southeast", "ky": "kentucky", "fla": "florida", "pa": "pennsylvania", "col": "college",
           "coll": "college", "inst": "institute"}
_STATES = {
    "al": "al", "ala": "al", "alabama": "al", "ak": "ak", "alaska": "ak", "az": "az", "ariz": "az", "arizona": "az",
    "ar": "ar", "ark": "ar", "arkansas": "ar", "ca": "ca", "cal": "ca", "calif": "ca", "california": "ca",
    "co": "co", "colo": "co", "colorado": "co", "ct": "ct", "conn": "ct", "connecticut": "ct", "de": "de",
    "del": "de", "delaware": "de", "fl": "fl", "fla": "fl", "florida": "fl", "ga": "ga", "georgia": "ga",
    "hi": "hi", "hawaii": "hi", "ia": "ia", "iowa": "ia", "id": "id", "idaho": "id", "il": "il", "ill": "il",
    "illinois": "il", "in": "in", "ind": "in", "indiana": "in", "ks": "ks", "kan": "ks", "kans": "ks",
    "kansas": "ks", "ky": "ky", "kentucky": "ky", "la": "la", "louisiana": "la", "ma": "ma", "mass": "ma",
    "massachusetts": "ma", "md": "md", "maryland": "md", "me": "me", "maine": "me", "mi": "mi",
    "mich": "mi", "michigan": "mi", "mn": "mn", "minn": "mn", "minnesota": "mn", "mo": "mo",
    "missouri": "mo", "ms": "ms", "miss": "ms", "mississippi": "ms", "mt": "mt", "mont": "mt",
    "montana": "mt", "nc": "nc", "nd": "nd", "ne": "ne", "neb": "ne", "nebraska": "ne", "nh": "nh",
    "nj": "nj", "nm": "nm", "nv": "nv", "nev": "nv", "nevada": "nv", "ny": "ny", "oh": "oh", "ohio": "oh",
    "ok": "ok", "okla": "ok", "oklahoma": "ok", "or": "or", "ore": "or", "oregon": "or", "pa": "pa",
    "penn": "pa", "pennsylvania": "pa", "ri": "ri", "sc": "sc", "sd": "sd", "tn": "tn", "tenn": "tn",
    "tennessee": "tn", "tx": "tx", "tex": "tx", "texas": "tx", "ut": "ut", "utah": "ut", "va": "va",
    "virginia": "va", "vt": "vt", "vermont": "vt", "wa": "wa", "wash": "wa", "washington": "wa",
    "wi": "wi", "wis": "wi", "wisc": "wi", "wisconsin": "wi", "wv": "wv", "wva": "wv", "wy": "wy",
    "wyo": "wy", "wyoming": "wy", "n c": "nc", "s c": "sc", "n d": "nd", "s d": "sd", "n m": "nm",
    "n y": "ny", "n j": "nj", "n h": "nh", "w va": "wv", "r i": "ri",
}

# Generic two-year college wording: "Butler CC", "Tyler Junior College", "Santa Barbara City College".
_JUCO = re.compile(r"(?i:\b(community|junior|comm\.?)\s+college\b|\bjuco\b|\bcity college\b(?! of new york)|"
                   r"\bc\.\s?c\.(?=\W|$)|\bj\.\s?c\.(?=\W|$)|\bcommunity and technical college\b)|"
                   r"\b(CC|JC|CTC)\b")
# Academic majors that some roster pages (Valparaiso's, for one) put in the previous-school field.
_MAJOR = re.compile(
    r"(?i)^(?:(?:pre-?)?(?:business|finance|marketing|management|accounting|communications?|kinesiology|"
    r"exercise|sports?|sport|engineering|mechanical|electrical|civil|chemical|computer|environmental|"
    r"bio\w*|integrated|healthcare|health|leadership|psychology|criminal|justice|economics|econometrics|"
    r"data|science|sociology|political|history|nursing|mathematics|administration|undecided|undeclared|"
    r"general|studies|education|physical|recreation|journalism|english|and|&|,)\s*)+$")


# Wording that only a high school uses: "St. John's College H.S.", "Boston College High".
_HIGH_SCHOOL = re.compile(r"(?i)\b(high school|high|h\.\s?s\.?|hs|prep|preparatory|secondary|vo-?tech|"
                          r"lab(oratory)? school|collegiate institute|charter)\b(?![- ]?(at|of)\b)")


def is_major(text: str) -> bool:
    """'Business', 'Sport Management', 'Mechanical Engineering' -> True: a major, not a school."""
    return bool(_MAJOR.match((text or "").strip()))


def _state(v: str) -> str:
    v = re.sub(r"[^a-z ]", "", v.lower()).strip()
    return _STATES.get(v, _STATES.get(v.replace(" ", ""), ""))


def key(name: str) -> str:
    """'Valdosta St.' and 'Valdosta State University' -> 'valdosta state'; 'UW-Whitewater' ->
    'wisconsin whitewater'; 'Lincoln University (Mo.)' -> 'lincoln (mo)'."""
    v = (name or "").lower().replace("&", " and ").replace("’", "'")
    hint = ""
    for p in re.findall(r"\(([^)]*)\)", v):
        if not hint:   # a state becomes its postal code; anything else ("St. Louis", "Moorhead") is read like a name
            hint = _state(p) or " ".join("saint" if w == "st" else _EXPAND.get(w, w)
                                         for w in re.findall(r"[a-z]+", p) if w not in _DROP)
    v = re.sub(r"\([^)]*\)", " ", v)
    words = [w for w in re.findall(r"[a-z0-9]+", v.replace("'", "")) if w not in _DROP]
    words = re.sub(r"\b([a-z]) (?=[a-z]\b)", r"\1", " ".join(words)).split()   # "n c state" -> "nc state"
    out = []
    for i, w in enumerate(words):
        if w == "st":
            w = "state" if i == len(words) - 1 else "saint"
        out.extend(_EXPAND.get(w, w).split())
    if len(out) > 2 and out[-1] == "u":            # "Arizona State U." (but "Cal U" stays as it is)
        out.pop()
    if len(out) > 1 and out[0] == "u":             # "U of Mary"
        out.pop(0)
    base = " ".join(out)
    return f"{base} ({hint})" if hint and base else base


def _base(k: str) -> str:
    return re.sub(r"\s*\([^)]*\)$", "", k)


def _loose(k: str) -> set[str]:
    """Looser spellings of a key: without its parenthetical, without 'College' / 'CC' / 'JC'."""
    b = _base(k)
    out = {b}
    for pat in (r"\s+(college|community college|junior college|cc|jc|ctc)$", r"^college\s+"):
        s = re.sub(pat, "", b)
        if s and s != b:
            out.add(s)
    return out - {k, ""}


class Levels:
    def __init__(self):
        self.strong: dict[str, list[tuple]] = {}   # key -> [(level, first, last, school)]
        self.weak: dict[str, list[tuple]] = {}

    def add(self, school: str, level: str, first: int | None, last: int | None, aliases=(), loose=True):
        entry = (level, first, last, school)
        names = [school, *aliases]
        for n in names:
            k = key(n)
            if k:
                self.strong.setdefault(k, []).append(entry)
                if loose:
                    for w in _loose(k):
                        self.weak.setdefault(w, []).append(entry)

    @staticmethod
    def _at(entries, year):
        """Entries for that season; for a season outside every range (a program that closed), the nearest."""
        def gap(e):
            return max((e[1] - year) if e[1] is not None else 0, (year - e[2]) if e[2] is not None else 0, 0)
        if not entries:
            return []
        best = min(gap(e) for e in entries)
        return [e for e in entries if gap(e) == best]

    def _pick(self, table, k, year):
        """(level, school) for a key, ("ambiguous", "") if it fits schools at two levels, None if no school."""
        hits = self._at(table.get(k, []), year)
        if not hits:
            return None
        levels = {e[0] for e in hits}
        if len(levels) > 1:
            return ("ambiguous", "")                     # same name at two levels: don't guess
        schools = {e[3] for e in hits}
        return (hits[0][0], hits[0][3] if len(schools) == 1 else "")

    def level(self, text: str, year: int) -> tuple[str, str]:
        """(level, school name it matched) for a previous-school text, in the season he left.
        Several schools in one field ("Wawasee | Ball State | Bethel (Tenn.)", "Lyons (College of the
        Sequoias)") are tried from the last one listed, which is usually the most recent."""
        got = self._one(text, year)
        if got[0] != "unknown" or got[1]:
            return got
        parts = [x.strip() for x in re.split(r"\s*[|/;]\s*", text or "") if x.strip()]
        parts += [x.strip() for x in re.findall(r"\(([^)]{6,})\)", text or "") if not _state(x)]
        if len(parts) > 1 or (parts and parts[0] != (text or "").strip()):
            for part in reversed(parts):
                got = self._one(part, year)
                if got[0] != "unknown":
                    return got
        return ("unknown", "")

    def _one(self, text: str, year: int) -> tuple[str, str]:
        text = (text or "").strip()
        if not text or is_major(text) or _HIGH_SCHOOL.search(text):
            return ("unknown", "")
        k = key(text)
        for table, kk in ((self.strong, k), (self.strong, _base(k)), (self.weak, k), (self.weak, _base(k))):
            got = self._pick(table, kk, year)
            if got:
                if got[0] == "unknown":
                    return got                            # a name listed as not a college ("Gonzaga College")
                if got[0] != "ambiguous":
                    return got
                if table is self.weak:
                    return ("unknown", "")
                break                                     # an ambiguous exact name: try the JUCO wording only
        if _JUCO.search(text):
            return ("JUCO", "")
        for kk in sorted(_loose(k), key=len, reverse=True):   # "Hope College" -> "hope"
            got = self._pick(self.strong, kk, year) or self._pick(self.weak, kk, year)
            if got:
                return got if got[0] != "ambiguous" else ("unknown", "")
        return ("unknown", "")

    @classmethod
    def load(cls, sport, schools: list[dict] | None = None) -> "Levels":
        """Every college in the sport's schools.csv (or the rows given), and the sport's junior colleges."""
        lv = cls()
        if schools is None:
            schools = _read_schools(Path(sport.schools_csv))
        by_school: dict[str, list[tuple]] = {}
        aliases: dict[str, list[str]] = {}
        for r in schools:
            name = (r.get("school") or "").strip()
            if not name or name.startswith("#"):
                continue
            by_school.setdefault(name, []).append(
                (_int(r.get("first_season")), _int(r.get("last_season")), (r.get("division") or "").strip()))
            aliases.setdefault(name, []).extend(a.strip() for a in (r.get("aliases") or "").split("|") if a.strip())
        # The sport's own D1 divisions (football: FBS, FCS; most sports: D1) all count as D1.
        level_of = {**_LEVEL_OF, **{d.upper(): "D1" for d in getattr(sport, "d1_divisions", [])}}
        for name, rows in sorted(by_school.items()):
            for first, last, level in _spans(rows, level_of):
                if level:                                  # "none": no team those seasons
                    lv.add(name, level, first, last, aliases[name])
        for n in getattr(sport, "junior_colleges", []):
            lv.add(n, "JUCO", None, None)
        return lv


def _int(v):
    v = (v or "").strip()
    return int(v) if v else None


# A division in schools.csv -> its level here. "none" (no team) has no level. Levels.load() adds the
# sport's own D1 divisions (d1_divisions in config/<sport>.json), so FBS and FCS are D1 for football.
_LEVEL_OF = {"D1": "D1", "D2": "D2", "D3": "D3", "NAIA": "NAIA", "JUCO": "JUCO", "CLUB": "CLUB", "HS": "unknown"}


def _spans(rows, level_of=None):
    """One college's (first, last, division) rows -> (first, last, level) for its seasons: each row with a
    season range as given, and the row without one (the school's usual level) filling the seasons between."""
    level_of = level_of or _LEVEL_OF

    def level(d):
        return level_of.get(d.upper(), "")
    usual = next((level(d) for f, l, d in rows if f is None and l is None), None)
    ranged = sorted(((f, l, level(d)) for f, l, d in rows if f is not None or l is not None),
                    key=lambda r: -1 if r[0] is None else r[0])
    if usual is None:
        return ranged
    out, cur = [], None                                   # cur: the first season not covered yet (None: from the start)
    for first, last, lvl in ranged:
        if first is not None and (cur is None or first > cur):
            out.append((cur, first - 1, usual))
        out.append((first, last, lvl))
        if last is None:
            return out
        cur = last + 1
    out.append((cur, None, usual))
    return out


def _read_schools(path: Path) -> list[dict]:
    if not path.exists():
        print(f"{path} not found; only the sport's junior colleges have a level")
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
