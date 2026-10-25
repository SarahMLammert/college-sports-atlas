from __future__ import annotations

"""Cleaning raw roster fields: hometowns (city, state, country), class years, heights, weights.
Shared by the scraper and the geocoder, for every sport."""
import re

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

# AP-style and other abbreviations seen on rosters -> USPS code.
_STATE_ALIASES = {
    "ala": "AL", "alas": "AK", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA",
    "colo": "CO", "col": "CO", "conn": "CT", "del": "DE", "d.c": "DC", "dc": "DC",
    "washington dc": "DC", "washington d.c": "DC", "fla": "FL", "flor": "FL", "ga": "GA",
    "ill": "IL", "ills": "IL", "ind": "IN", "kan": "KS", "kans": "KS", "ky": "KY", "la": "LA",
    "md": "MD", "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO",
    "mont": "MT", "neb": "NE", "nebr": "NE", "nev": "NV", "n.h": "NH", "nh": "NH",
    "n.j": "NJ", "nj": "NJ", "n.m": "NM", "n.mex": "NM", "nm": "NM", "n.y": "NY", "ny": "NY",
    "n.c": "NC", "nc": "NC", "n.d": "ND", "n.dak": "ND", "nd": "ND", "okla": "OK",
    "ore": "OR", "oreg": "OR", "pa": "PA", "penn": "PA", "penna": "PA", "r.i": "RI", "ri": "RI",
    "s.c": "SC", "sc": "SC", "s.d": "SD", "s.dak": "SD", "sd": "SD", "tenn": "TN",
    "tex": "TX", "vt": "VT", "va": "VA", "wash": "WA", "w.va": "WV", "w.v": "WV", "wva": "WV",
    "wv": "WV", "wis": "WI", "wisc": "WI", "wyo": "WY", "p.r": "PR", "pr": "PR",
    "puerto rico": "PR", "guam": "GU", "american samoa": "AS", "a.s": "AS",
    "u.s. virgin islands": "VI", "virgin islands": "VI", "saipan": "MP",
    # Hawaii: islands and spellings with the okina
    "hawai'i": "HI", "hawaii": "HI", "hi": "HI", "o'ahu": "HI", "oahu": "HI", "maui": "HI",
    "kaua'i": "HI", "kauai": "HI", "big island": "HI", "hawai'i island": "HI", "moloka'i": "HI",
    "lana'i": "HI", "molokai": "HI", "lanai": "HI",
    "ga": "GA", "geo": "GA", "tx": "TX", "texas": "TX", "fl": "FL", "ca": "CA",
    "ken": "KY", "w. va": "WV", "w. virginia": "WV", "hawai‘i": "HI", "hawaiʻi": "HI",
}
for _code, _name in US_STATES.items():
    _STATE_ALIASES[_name.lower()] = _code
    _STATE_ALIASES[_code.lower()] = _code

_COUNTRY_FIXES = {
    "aus": "Australia", "aust": "Australia", "australia": "Australia", "nz": "New Zealand",
    "new zealand": "New Zealand", "eng": "England", "england": "England", "uk": "United Kingdom",
    "can": "Canada", "canada": "Canada", "ger": "Germany", "germany": "Germany",
    "mex": "Mexico", "mexico": "Mexico", "nigeria": "Nigeria", "bahamas": "Bahamas",
    "the bahamas": "Bahamas", "jamaica": "Jamaica", "samoa": "Samoa", "tonga": "Tonga",
    "japan": "Japan", "france": "France", "ireland": "Ireland", "sweden": "Sweden",
    "netherlands": "Netherlands", "austria": "Austria", "brazil": "Brazil",
    "the netherlands": "Netherlands", "holland": "Netherlands", "united kingdom": "United Kingdom",
    "great britain": "United Kingdom", "scotland": "Scotland", "wales": "Wales",
    "northern ireland": "Northern Ireland", "au": "Australia", "western australia": "Australia",
    "south australia": "Australia", "new south wales": "Australia", "nsw": "Australia",
    "queensland": "Australia", "qld": "Australia", "victoria": "Australia", "tasmania": "Australia",
    "grand bahama": "Bahamas", "nassau": "Bahamas", "china": "China", "serbia": "Serbia",
    "hungary": "Hungary", "south korea": "South Korea", "korea": "South Korea", "greece": "Greece",
    "russia": "Russia", "egypt": "Egypt", "liberia": "Liberia", "syria": "Syria", "panama": "Panama",
    "venezuela": "Venezuela", "croatia": "Croatia", "gabon": "Gabon", "ghana": "Ghana",
    "cameroon": "Cameroon", "kenya": "Kenya", "senegal": "Senegal", "south africa": "South Africa",
    "italy": "Italy", "spain": "Spain", "denmark": "Denmark", "norway": "Norway", "finland": "Finland",
    "switzerland": "Switzerland", "belgium": "Belgium", "poland": "Poland", "ukraine": "Ukraine",
    "israel": "Israel", "haiti": "Haiti", "dominican republic": "Dominican Republic", "fiji": "Fiji",
    "democratic republic of the congo": "Democratic Republic of the Congo",
    "democratic republic of congo": "Democratic Republic of the Congo",
    "dr of the congo": "Democratic Republic of the Congo", "drc": "Democratic Republic of the Congo",
    "congo": "Congo", "czech republic": "Czech Republic", "czechia": "Czech Republic",
}
_CANADIAN_PROVINCES = {
    "ont": "ON", "ontario": "ON", "on": "ON", "que": "QC", "quebec": "QC", "qc": "QC",
    "b.c": "BC", "bc": "BC", "british columbia": "BC", "alta": "AB", "alberta": "AB", "ab": "AB",
    "man": "MB", "manitoba": "MB", "sask": "SK", "saskatchewan": "SK", "n.s": "NS",
    "nova scotia": "NS", "n.b": "NB", "new brunswick": "NB", "p.e.i": "PE", "newfoundland": "NL",
    "ontario, canada": "ON", "québec": "QC", "nfld": "NL",
}


def clean(text) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _key(part: str) -> str:
    part = clean(part).replace("’", "'").replace("‘", "'").replace("ʻ", "'").replace("`", "'")
    return part.lower().rstrip(".").strip()


_PLACEHOLDERS = {"hometown", "n/a", "na", "-", "--", "tbd", "none", "unknown", "/"}


def _lookup(table: dict, k: str) -> str:
    """Look a state/country token up as written, then with dots, spaces and stray symbols
    removed, so 'W. Va.', 'F.L.', 'P.A.', 'U.K.' and 'SC|' all match."""
    if k in table:
        return table[k]
    return table.get(re.sub(r"[^a-z]", "", k), "")


def split_hometown_highschool(value: str) -> tuple[str, str]:
    """'Atlanta, Ga. / Westlake HS' -> ('Atlanta, Ga.', 'Westlake HS')."""
    value = clean(value)
    if " / " in value:
        a, b = value.split(" / ", 1)
        return clean(a), clean(b)
    if "/" in value and value.count("/") == 1:
        a, b = value.split("/", 1)
        return clean(a), clean(b)
    return value, ""


# A roster's column label saved in front of the value: "Hometown/Prev. School: Wilson, NC / Beddingfield".
_LABEL = re.compile(r"^(?P<label>[^:]{2,60}?)\s*\.?\s*:\s*(?P<value>.*)$")
_LABEL_WORDS = re.compile(r"\b(hometown|home town|hs|city|high school|prev|previous|last school|college|grad)\b", re.I)
_HOME_WORDS = re.compile(r"hometown|home town|city", re.I)


def split_labeled_hometown(value: str) -> tuple[str, str]:
    """Take a column label off a hometown field and split off the school that shares it.
    Returns (hometown, school). A field without such a label comes back unchanged, with no school.

        'Hometown/Prev. School: Wilson, NC / Beddingfield'  -> ('Wilson, NC', 'Beddingfield')
        'Hometown/Previous School(s): Omaha, Neb.'          -> ('Omaha, Neb.', '')
        'HS City (State): Mayfair HS / Lakewood (CA)'       -> ('Lakewood, CA', 'Mayfair HS')
        'HS City (State): Mayfair'                          -> ('', 'Mayfair')   (a school, no town)
        'HS Hometown/High School: Santa Ana'                -> ('Santa Ana', '')
        'ICC Grad Date:'                                    -> ('', '')          (no hometown in it)
    """
    v = clean(value)
    m = _LABEL.match(v)
    if not m or not _LABEL_WORDS.search(m.group("label")):
        return v, ""
    label, val = m.group("label").strip(), m.group("value").strip()
    if not _HOME_WORDS.search(label):
        return "", ""
    labels = ["HS", "City"] if re.match(r"hs city", label, re.I) else [p.strip() for p in label.split("/")]
    vals = [p.strip() for p in re.split(r"\s*/\s*", val)] if val else []
    home_idx = next(i for i, part in enumerate(labels) if _HOME_WORDS.search(part))
    if len(vals) < len(labels) and home_idx > 0:
        # Fewer values than the label names, and the town isn't first: "HS City (State): Mayfair"
        # holds only the high school.
        home, schools = "", vals
    elif vals:
        i = min(home_idx, len(vals) - 1) if len(vals) >= len(labels) else 0
        home, schools = vals[i], vals[:i] + vals[i + 1:]
    else:
        home, schools = "", []
    if re.search(r"\b(college|university|univ|cc|jc)\b", home, re.I):
        # "HS City (State): Lakewood/University of Nevada": a high school and a college, no town
        home, schools = "", schools + [home]
    home = re.sub(r"\s*\(([A-Za-z]{2})\)$", r", \1", home)   # "Lakewood (CA)" -> "Lakewood, CA"
    return home.strip(" ,"), " / ".join(s for s in schools if s)


def parse_hometown(raw: str) -> dict:
    """Return {'city','state','country'} from strings like 'Mobile, Ala.' or 'Sydney, Australia'."""
    raw = split_labeled_hometown(raw)[0]
    raw = clean(raw).replace("’", "'").replace("‘", "'").replace("ʻ", "'")
    out = {"city": "", "state": "", "country": ""}
    if not raw or raw.lower().strip(" .") in _PLACEHOLDERS:
        return out
    raw = re.sub(r"^(hometown|home town)(\s*/\s*(last|high|previous) school)?\s*:?\s*", "", raw, flags=re.I)
    # Drop a school that shares the field: "Atlanta, Ga. / Westlake HS", "Houston, Texas - Lamar"
    raw = re.split(r"\s*/\s*|\s+[-\u2013\u2014]\s+", raw, maxsplit=1)[0].strip()
    if re.fullmatch(r"washington,?\s*d\.?\s*c\.?", raw, flags=re.I):
        return {"city": "Washington", "state": "DC", "country": "USA"}
    # Drop parenthetical notes: "Miami, Fla. (Central HS)", "Houston, Texas (Alief Taylor)"
    raw = re.sub(r"\s*\([^)]*\)?\s*$", "", raw).strip().rstrip(",")
    if not raw:
        return out
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:
        k = _key(parts[0])
        if _lookup(_STATE_ALIASES, k):  # just a state
            out.update(state=_lookup(_STATE_ALIASES, k), country="USA")
        elif _lookup(_COUNTRY_FIXES, k):
            out["country"] = _lookup(_COUNTRY_FIXES, k)
        else:
            out["city"] = parts[0]
        return out

    city, rest = parts[0].strip("'\" "), parts[1:]
    last = _key(rest[-1])
    # "Montreal, Quebec, Canada" -> keep the province
    if len(rest) >= 2 and last in ("canada", "can") and _key(rest[-2]) in _CANADIAN_PROVINCES:
        return {"city": city, "state": _CANADIAN_PROVINCES[_key(rest[-2])], "country": "Canada"}
    if last in ("usa", "u.s.a", "us", "u.s", "united states"):
        rest = rest[:-1] or rest
        last = _key(rest[-1])
    if _lookup(_STATE_ALIASES, last):
        out.update(city=city, state=_lookup(_STATE_ALIASES, last), country="USA")
    elif _lookup(_CANADIAN_PROVINCES, last):
        out.update(city=city, state=_lookup(_CANADIAN_PROVINCES, last), country="Canada")
    elif _lookup(_COUNTRY_FIXES, last):
        out.update(city=city, country=_lookup(_COUNTRY_FIXES, last))
    else:
        # Unknown trailing token: treat as a foreign country/region.
        out.update(city=city, country=clean(rest[-1]))
    return out


_RS = r"^(r|rs|red|redshirt|medical redshirt)?[\s\-.]*"
_CLASS_MAP = [
    (_RS + r"(fr|fy|first[\s\-]year)", "FR"),
    (_RS + r"so", "SO"),
    (_RS + r"jr|junior", "JR"),
    (_RS + r"sr|senior", "SR"),
    (r"^gr|grad|^5th|fifth|^6th|sixth|^7th|seventh|^gs|post[\s\-]?bacc", "GR"),
    (r"^1st|first", "FR"),
    (r"^2nd|second", "SO"),
    (r"^3rd|third", "JR"),
    (r"^4th|fourth", "SR"),
]


def normalize_class(value: str) -> str:
    v = clean(value).lower()
    if not v:
        return ""
    for pattern, code in _CLASS_MAP:
        if re.search(pattern, v):
            redshirt = re.match(r"^(r[\s\-.]|rs|red|redshirt|medical redshirt)", v)
            return ("R-" + code) if redshirt and code != "GR" else code
    return clean(value)


def format_height(feet=None, inches=None, raw: str = "") -> str:
    if feet not in (None, "", 0, "0"):
        try:  # a bad value here used to raise and throw away the whole roster
            return f"{int(float(feet))}-{int(float(inches or 0))}"
        except (TypeError, ValueError):
            pass
    raw = clean(raw)
    m = re.match(r"^(\d)\s*['\-’ ]\s*(\d{1,2})", raw)
    return f"{m.group(1)}-{int(m.group(2))}" if m else raw


def clean_weight(value) -> str:
    m = re.search(r"\d{2,3}", clean(value))
    return m.group(0) if m else ""
