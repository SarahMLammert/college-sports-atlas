"""This file holds, in order:
    Reading hometowns
    Placing hometowns on the map

Commands:
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ==============================================================================================================
# Reading hometowns   (was scripts/hometowns.py)
# ==============================================================================================================

HOMETOWNS_DOC = ''
from core import clean  # noqa: E402  (moved to core so the season files needn't import this file)

"""Cleaning raw roster fields: hometowns (city, state, country), class years, heights, weights.
Shared by the scraper and the geocoder, for every sport."""
import html
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
    "long island": "NY", "n. car": "NC", "n car": "NC", "s. car": "SC", "s car": "SC",   # Oct 28
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
    # Oct 27 (softball): more spellings seen on rosters. "Ill." read as "III." or "lll." (capital I or
    # lower-case L in place of the I's); short forms that no style guide uses but rosters do.
    "iii": "IL", "lll": "IL", "illi": "IL", "illinios": "IL", "virg": "VA", "ten": "TN", "kent": "KY",
    "mary": "MD", "min": "MN", "miinn": "MN", "color": "CO", "ida": "ID", "mon": "MT", "louis": "LA",
    "ver": "VT", "west va": "WV", "nev": "NV", "ak": "AK", "vir": "VA", "wisc.": "WI",
    "usvi": "VI", "us virgin islands": "VI", "virgin island": "VI", "st. croix": "VI", "st. thomas": "VI",
    "mariana islands": "MP", "northern marianas": "MP", "cnmi": "MP",
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
    # Oct 27 (softball)
    "curacao": "Curacao", "curaçao": "Curacao", "curacau": "Curacao", "suriname": "Suriname",
    "qatar": "Qatar", "hong kong": "Hong Kong", "trinidad": "Trinidad and Tobago",
    "trinidad and tobago": "Trinidad and Tobago", "trinidad & tobago": "Trinidad and Tobago",
    "colombia": "Colombia", "columbia": "Colombia", "philippines": "Philippines", "phillipines": "Philippines",
    "singapore": "Singapore", "lithuania": "Lithuania", "grand bahamas": "Bahamas", "bahama": "Bahamas",
    "british virgin islands": "British Virgin Islands", "bvi": "British Virgin Islands", "aruba": "Aruba",
    "guatemala": "Guatemala", "argentina": "Argentina", "chile": "Chile", "peru": "Peru",
    "bermuda": "Bermuda", "cayman islands": "Cayman Islands", "rwanda": "Rwanda",
    # Oct 28: abbreviations and spellings left unplaced after the Oct 27 runs (baseball most of all)
    "dr": "Dominican Republic", "d.r": "Dominican Republic", "rd": "Dominican Republic",
    "dom. rep": "Dominican Republic", "dom rep": "Dominican Republic", "dom. republic": "Dominican Republic",
    "dominican rep": "Dominican Republic", "dominican repub": "Dominican Republic",
    "domincan republic": "Dominican Republic", "dominic republic": "Dominican Republic",
    "dominican republica": "Dominican Republic", "republica dominicana": "Dominican Republic",
    "república dominicana": "Dominican Republic", "rep. dominicana": "Dominican Republic",
    "vz": "Venezuela", "ve": "Venezuela", "ven": "Venezuela", "venez": "Venezuela", "venezuala": "Venezuela",
    "jpn": "Japan", "jap": "Japan", "pan": "Panama", "nicaragua": "Nicaragua", "nic": "Nicaragua",
    "saudi arabia": "Saudi Arabia", "cuba": "Cuba", "honduras": "Honduras", "el salvador": "El Salvador",
    "costa rica": "Costa Rica", "ecuador": "Ecuador", "uruguay": "Uruguay", "paraguay": "Paraguay",
    "bolivia": "Bolivia", "belize": "Belize", "barbados": "Barbados", "grenada": "Grenada",
    "st. lucia": "Saint Lucia", "saint lucia": "Saint Lucia", "antigua": "Antigua and Barbuda",
    "u.s. virgin islands": "", "taiwan": "Taiwan", "india": "India", "pakistan": "Pakistan",
    "vietnam": "Vietnam", "thailand": "Thailand", "indonesia": "Indonesia", "malaysia": "Malaysia",
    "portugal": "Portugal", "iceland": "Iceland", "estonia": "Estonia", "latvia": "Latvia",
    "slovakia": "Slovakia", "slovenia": "Slovenia", "romania": "Romania", "bulgaria": "Bulgaria",
    "turkey": "Turkey", "lebanon": "Lebanon", "jordan": "Jordan", "morocco": "Morocco", "uganda": "Uganda",
    "zimbabwe": "Zimbabwe", "ethiopia": "Ethiopia", "tanzania": "Tanzania", "sierra leone": "Sierra Leone",
    "ivory coast": "Ivory Coast", "cote d'ivoire": "Ivory Coast", "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates", "argentine": "Argentina", "brasil": "Brazil", "deutschland": "Germany",
    "espana": "Spain", "españa": "Spain", "italia": "Italy", "sverige": "Sweden", "danmark": "Denmark",
    "norge": "Norway", "suomi": "Finland", "schweiz": "Switzerland", "österreich": "Austria",
    "the philippines": "Philippines", "republic of korea": "South Korea", "s. korea": "South Korea",
    "papua new guinea": "Papua New Guinea", "png": "Papua New Guinea", "cook islands": "Cook Islands",
    "tahiti": "French Polynesia", "french polynesia": "French Polynesia", "guyana": "Guyana",
    # Oct 28 (hockey): the three-letter codes hockey rosters use (IOC and ISO), short forms and misspellings.
    # Not "ind" (Indiana), "can"/"aut" stay as they were, "den" is Denmark only after a comma.
    "swe": "Sweden", "swed": "Sweden", "sweeden": "Sweden", "se": "Sweden", "fin": "Finland", "fi": "Finland",
    "svk": "Slovakia", "slovak republic": "Slovakia", "cze": "Czech Republic", "cz": "Czech Republic",
    "czech rep": "Czech Republic", "the czech republic": "Czech Republic", "czechoslovakia": "Czech Republic",
    "lva": "Latvia", "lat": "Latvia", "lv": "Latvia", "blr": "Belarus", "belarus": "Belarus", "fra": "France",
    "nor": "Norway", "nw": "Norway", "sui": "Switzerland", "swi": "Switzerland", "swiss": "Switzerland",
    "che": "Switzerland", "den": "Denmark", "dnk": "Denmark", "dk": "Denmark", "deu": "Germany", "aut": "Austria",
    "rus": "Russia", "russian federation": "Russia", "kaz": "Kazakhstan", "kazakhstan": "Kazakhstan",
    "svn": "Slovenia", "slo": "Slovenia", "ita": "Italy", "hun": "Hungary", "pol": "Poland", "ukr": "Ukraine",
    "ua": "Ukraine", "gbr": "United Kingdom", "kor": "South Korea", "kr": "South Korea", "chn": "China",
    "ned": "Netherlands", "nld": "Netherlands", "est": "Estonia", "ltu": "Lithuania", "srb": "Serbia",
    "cro": "Croatia", "hrv": "Croatia", "bul": "Bulgaria", "rou": "Romania", "isl": "Iceland", "irl": "Ireland",
    "esp": "Spain", "bel": "Belgium", "nzl": "New Zealand", "isr": "Israel", "isreal": "Israel",
    "uzbekistan": "Uzbekistan", "luxembourg": "Luxembourg", "lux": "Luxembourg",
    # regions written where the country goes
    "østfold": "Norway", "ostfold": "Norway", "uusimaa": "Finland", "catalunya": "Spain", "catalonia": "Spain",
    "samara region": "Russia", "vic": "Australia",
    "mx": "Mexico", "venzuela": "Venezuela", "candada": "Canada", "brz": "Brazil", "panamá": "Panama",
    "hu": "Hungary", "tokyo": "Japan",
}
_COUNTRY_FIXES = {k: v for k, v in _COUNTRY_FIXES.items() if v}
_CANADIAN_PROVINCES = {
    "ont": "ON", "ontario": "ON", "on": "ON", "que": "QC", "quebec": "QC", "qc": "QC",
    "b.c": "BC", "bc": "BC", "british columbia": "BC", "alta": "AB", "alberta": "AB", "ab": "AB",
    "man": "MB", "manitoba": "MB", "sask": "SK", "saskatchewan": "SK", "n.s": "NS",
    "nova scotia": "NS", "n.b": "NB", "new brunswick": "NB", "p.e.i": "PE", "newfoundland": "NL",
    "ontario, canada": "ON", "québec": "QC", "nfld": "NL",
    # Oct 27: the postal codes (MB, SK, NS, ...) were missing, so "Winnipeg, MB" came out as a country "MB".
    # Not "NL": on rosters that is as often the Netherlands ("Spijkenisse, NL").
    "mb": "MB", "sk": "SK", "ns": "NS", "nb": "NB", "pe": "PE", "pei": "PE", "prince edward island": "PE",
    "newfoundland and labrador": "NL", "yt": "YT", "yukon": "YT", "nt": "NT", "northwest territories": "NT",
    "nu": "NU", "nunavut": "NU",
    "alb": "AB", "albt": "AB", "sask.": "SK", "qué": "QC", "que.": "QC", "p.q": "QC", "nfl": "NL",
    # Oct 28 (hockey). "N.L." and "N.F." with their dots are Newfoundland; plain "NL" is decided by the
    # geocoder (a Newfoundland town of that name, else the Netherlands).
    "pq": "QC", "queb": "QC", "n.l": "NL", "n.f": "NL", "nf": "NL", "nfld.": "NL", "newfoundland & labrador": "NL",
    "nwt": "NT", "n.w.t": "NT", "yukon territory": "YT", "nunuvat": "NU", "prince edward": "PE",
    "manatoba": "MB", "atla": "AB", "altberta": "AB", "albera": "AB", "ontartio": "ON", "onatrio": "ON", "mantoba": "MB",
    "manitboa": "MB", "saskatechewan": "SK", "sasketchewan": "SK", "saskatchwan": "SK", "novia scotia": "NS",
}




def _key(part: str) -> str:
    part = clean(part).replace("’", "'").replace("‘", "'").replace("ʻ", "'").replace("`", "'")
    return part.lower().rstrip(".").strip()


_PLACEHOLDERS = {"hometown", "n/a", "na", "-", "--", "tbd", "none", "unknown", "/"}

# Text from another column that some rosters put where the hometown goes: bats/throws ("R/R", "L/R"),
# a height ("5-7", "5'7\""), a role ("Manager"). Never a town.
_NOT_A_PLACE = re.compile(r"""(?ix)^(?:
    [LRSB]\s*/\s*[LRSB] | [LRSB] | right | left | switch | both
    | (?:student\s+)?manager | \d\s*[-'’]\s*\d{1,2}(?:"|''|”)? )$""")
# Bats/throws at the end of the field: "MSJC / R/R", "Fullerton College / L/R"
_TRAILING_BATS = re.compile(r"\s*/\s*[LRSB]\s*/\s*[LRSB]\s*$", re.I)


def not_a_place(text: str) -> bool:
    """'R/R', 'L', '5-7', 'Manager' -> True: something from another column, not a hometown."""
    return bool(_NOT_A_PLACE.match(clean(text)))


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


def _tidy_punctuation(raw: str) -> str:
    """Typing slips around the state: 'Randleman, N,C,' -> 'Randleman, N.C.'; 'New Ulm, Minn,.' ->
    'New Ulm, Minn.'; 'St, Joseph, Mo.' -> 'St. Joseph, Mo.'; 'Smithfield,Ga.' keeps working."""
    raw = re.sub(r",\s*([A-Za-z])\s*,\s*([A-Za-z])\s*[,.]*$", r", \1.\2.", raw)
    raw = re.sub(r",\s*\.$", ".", raw)
    raw = re.sub(r"^(St|Ste|Ft|Mt),\s+", r"\1. ", raw)
    return raw


def _region(token: str) -> dict | None:
    """A trailing region we know: a US state, a Canadian province, a country, or a province or region
    followed by its country ('Ontario Canada', 'B.C. Canada', 'Alberta-Canada', 'Lombardia Italy')."""
    k = _key(token)
    if _lookup(_STATE_ALIASES, k):
        return {"state": _lookup(_STATE_ALIASES, k), "country": "USA"}
    if _lookup(_CANADIAN_PROVINCES, k):
        return {"state": _lookup(_CANADIAN_PROVINCES, k), "country": "Canada"}
    if _lookup(_COUNTRY_FIXES, k):
        return {"state": "", "country": _lookup(_COUNTRY_FIXES, k)}
    words = re.split(r"[\s\-]+", k)
    for n in (2, 1):                                   # the country is the last one or two words
        if len(words) <= n:
            continue
        country = _lookup(_COUNTRY_FIXES, " ".join(words[-n:]))
        if not country:
            continue
        head = " ".join(words[:-n])
        if country == "Canada" and _lookup(_CANADIAN_PROVINCES, head):
            return {"state": _lookup(_CANADIAN_PROVINCES, head), "country": "Canada"}
        return {"state": "", "country": country}
    return None


_PROVINCE_CODES = {"AB", "BC", "B.C.", "MB", "SK", "ON", "QC", "NS", "NB", "PE", "PEI", "NL"}
_PROVINCE_NAMES = {"alberta", "british columbia", "manitoba", "saskatchewan", "ontario", "quebec", "québec",
                   "nova scotia", "new brunswick", "prince edward island", "newfoundland"}


def _canadian_without_comma(text: str) -> dict | None:
    """'Calgary AB', 'Okotoks Alberta', 'Chilliwack British Columbia', 'Delta BC Canada' (no comma) ->
    the town and province. Only Canada: a US state written without a comma is checked against the US
    town list by hometown_fixes.py suggest, since 'Port Washington' or 'Saint Louis' end in a state's name."""
    words = re.sub(r"[\s\-]+(canada|can)\.?$", "", clean(text), flags=re.I).split()
    for n in (3, 2, 1):
        if len(words) <= n:
            continue
        tail = " ".join(words[-n:])
        if tail.upper() in _PROVINCE_CODES and tail.upper() == tail or tail.lower() in _PROVINCE_NAMES:
            code = _lookup(_CANADIAN_PROVINCES, _key(tail))
            if code:
                return {"city": " ".join(words[:-n]).rstrip(" ,."), "state": code, "country": "Canada"}
    return None


# Places written with no comma before an unmistakable territory or country: "Cidra PR", "San Juan Puerto Rico",
# "Pago Pago AS", "Santo Domingo DR", "Valencia Venezuela", "Chitre Panama". Only these: most other endings
# ("Las Cruces New Mexico", "Port Washington") are part of a US town's name or a state.
_NO_COMMA_ENDINGS = [
    (re.compile(r"^(.+?)[\s.]+(?:PR|P\.R\.|Puerto Rico)$"), "PR", "USA"),
    (re.compile(r"^(.+?)[\s.]+(?:AS|American Samoa)$"), "AS", "USA"),
    (re.compile(r"^(.+?)[\s.]+(?:DR|D\.R\.|R\.D\.|Dominican Republic|Rep(?:ublica|\.)? Dominicana)$", re.I), "",
     "Dominican Republic"),
    (re.compile(r"^(.+?)\s+(Venezuela|Panama|Nicaragua|Colombia|Curacao|Aruba|Bahamas|Japan|Australia)$", re.I), "", None),
]


def _no_comma_ending(text: str) -> dict | None:
    for pat, state, country in _NO_COMMA_ENDINGS:
        m = pat.match(text)
        if not m:
            continue
        city = m.group(1).strip(" .,")
        if not city:      # (PR and AS match in capitals only: "Cidra PR", not "Cidra pr")
            continue
        return {"city": city, "state": state,
                "country": country or _lookup(_COUNTRY_FIXES, _key(m.group(2)))}
    return None


_HAWAII_ISLANDS = {"maui", "oahu", "o'ahu", "kauai", "kaua'i", "big island", "molokai", "moloka'i", "lanai", "lana'i"}

# Country names that are also US towns. Written alone, they're read as the town (its state is guessed from the
# school, like any town given without a state): "Lebanon" on an Ohio Northern roster is Lebanon OH, "Holland" on
# Hope's is Holland MI. A player from abroad gives a city too ("Beirut, Lebanon").
_ALSO_US_TOWNS = {"lebanon", "jordan", "peru", "cuba", "holland", "poland", "denmark", "turkey", "belgium", "norway",
                  "columbia"}   # "Columbia" alone: Columbia MS, SC, MO (with a city it's still read as Colombia)


def parse_hometown(raw: str) -> dict:
    """Return {'city','state','country'} from strings like 'Mobile, Ala.' or 'Sydney, Australia'."""
    raw = split_labeled_hometown(html.unescape(raw or ""))[0]
    raw = clean(raw).replace("’", "'").replace("‘", "'").replace("ʻ", "'")
    out = {"city": "", "state": "", "country": ""}
    raw = _TRAILING_BATS.sub("", raw).strip(' "')
    if not raw or raw.lower().strip(" .") in _PLACEHOLDERS or not_a_place(raw):
        return out
    raw = _tidy_punctuation(raw)
    raw = re.sub(r"^(hometown|home town)(\s*/\s*(last|high|previous) school)?\s*:?\s*", "", raw, flags=re.I)
    # Drop a school that shares the field: "Atlanta, Ga. / Westlake HS", "Houston, Texas - Lamar"
    raw = re.split(r"\s*/\s*|\s+[-\u2013\u2014]\s+", raw, maxsplit=1)[0].strip()
    if re.fullmatch(r"washington,?\s*d\.?\s*c\.?", raw, flags=re.I):
        return {"city": "Washington", "state": "DC", "country": "USA"}
    # "Pago Pago (AS)", "Lakewood (CA)": a state or territory code in brackets is the state
    m = re.match(r"^(.+?)\s*\(([A-Z]{2})\)$", raw)
    if m and m.group(2) in US_STATES:
        raw = f"{m.group(1)}, {m.group(2)}"
    # Drop parenthetical notes: "Miami, Fla. (Central HS)", "Houston, Texas (Alief Taylor)"
    raw = re.sub(r"\s*\([^)]*\)?\s*$", "", raw).strip().rstrip(",")
    if not raw:
        return out
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:
        k = _key(parts[0])
        if k in _HAWAII_ISLANDS:        # "Maui": the island, so it gets the island's dot, not Hawaii's middle
            return {"city": clean(parts[0]), "state": "HI", "country": "USA"}
        if _lookup(_STATE_ALIASES, k):  # just a state
            out.update(state=_lookup(_STATE_ALIASES, k), country="USA")
        elif _lookup(_COUNTRY_FIXES, k) and k not in _ALSO_US_TOWNS:
            out["country"] = _lookup(_COUNTRY_FIXES, k)
        else:
            out.update(_canadian_without_comma(parts[0]) or _no_comma_ending(parts[0]) or {"city": parts[0]})
        return out

    city, rest = parts[0].strip("'\" "), parts[1:]
    last = _key(rest[-1])
    # "Montreal, Quebec, Canada" -> keep the province
    if len(rest) >= 2 and last in ("canada", "can") and _key(rest[-2]) in _CANADIAN_PROVINCES:
        return {"city": city, "state": _CANADIAN_PROVINCES[_key(rest[-2])], "country": "Canada"}
    # "Brandon, Manitoba, CA": CA is Canada here, not California
    if len(rest) >= 2 and last == "ca" and _lookup(_CANADIAN_PROVINCES, _key(rest[-2])):
        return {"city": city, "state": _lookup(_CANADIAN_PROVINCES, _key(rest[-2])), "country": "Canada"}
    if last in ("usa", "u.s.a", "us", "u.s", "united states"):
        rest = rest[:-1] or rest
        last = _key(rest[-1])
    # "Rockledge, Fla. USA": the country written after the state with no comma
    if re.search(r"\s+(usa|u\.s\.a\.?)$", rest[-1], re.I):
        rest = rest[:-1] + [re.sub(r"\s+(usa|u\.s\.a\.?)$", "", rest[-1], flags=re.I)]
    # "Pago Pago. AS" was one part; "Hilo, Hawai`i \ Waiakea HS": a backslash before the school
    rest[-1] = re.split(r"\s*\\\s*", rest[-1])[0]
    region = _region(rest[-1])
    if region:
        out.update(city=city, **region)
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

__all__ = [n for n in dir() if not n.startswith('_')]   # what `from geocode import *` gives


# ==============================================================================================================
# Placing hometowns on the map   (was scripts/geocode_hometowns.py)
# ==============================================================================================================

GEOCODE_HOMETOWNS_DOC = 'Add latitude/longitude to scraped rosters so hometowns can be mapped.\n\nOffline sources (downloaded once into .cache/):\n  1. US Census Gazetteer places + county subdivisions (cities, towns, CDPs, townships)\n  2. USGS GNIS Populated Places (unincorporated communities and neighborhoods:\n     Cypress TX, Ellenwood GA, Kingwood TX, Pacoima CA, ...)\n  3. US Census Gazetteer counties ("Stafford, Va.", "Broward County, Fla.")  -> county centroid\n  4. Built-in centroids for US territories and common foreign countries      -> coarse fallback\nOptional online source (--online): OpenStreetMap Nominatim for whatever is left\n(foreign cities, typos), 1 request/second, cached in .cache/nominatim.json.\n\n    python scripts/geocode.py                       # the season files in rosters/football/\n    python scripts/geocode.py --online --contact you@example.com\n    python scripts/geocode.py --sport mens-basketball\n\nHometowns that don\'t match get a suggested fix (typos, wrong state, school text mixed in).\nSuggestions marked "fixed" are applied in the same run; "review" ones are applied only with\n--use-review. All suggestions are saved to config/<sport>/hometown_corrections.csv, where your\nhand edits are kept from run to run and win over the built-in rules.\n\nReads every player from the season files (rosters_<season>.csv), one row per player per school\n(built in memory, the same way scrape_rosters.py --combined writes players_unique.csv).\n\nWrites config/<sport>/hometown_corrections.csv (the fix table: status fixed / review / unfixable),\nand in rosters/<sport>/:\n  hometowns.csv               one row per hometown: what the roster said, the town it was read as,\n                              lat/lon, where the answer came from, and how many players. Open it\n                              to look anything up. Re-runs reuse it, so only new hometowns are\n                              looked up. To move a dot by hand, change its lat/lon and set its\n                              source to "manual"; manual rows are always kept. build.py map\n                              reads each player\'s dot from here.\n  unmatched_hometowns.csv     what still couldn\'t be placed, most common first\nGiven a CSV instead (geocode.py some.csv), it also writes some_geocoded.csv next to it: the\nrows + home_lat, home_lon, geo_source, geo_precision, with each hometown\'s corrected city/state/country.\n\nAfter changing the parser or this script, run with --refresh to look every hometown up again.\n'
import argparse
import csv
import html
import io
import json
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

import requests

from core import add_sport_argument, load_sport  # noqa: E402
from core import players  # noqa: E402

# In the repo folder (this script lives in scripts/), not the folder it's run from, so every run
# finds the same downloads and the same saved online answers.
CACHE = Path(__file__).resolve().parent.parent / ".cache"
GAZ_YEAR = 2024
GAZ_BASE = f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{GAZ_YEAR}_Gazetteer/"
GAZ_PLACES = f"{GAZ_YEAR}_Gaz_place_national.zip"
GAZ_COUSUBS = f"{GAZ_YEAR}_Gaz_cousubs_national.zip"
GAZ_COUNTIES = f"{GAZ_YEAR}_Gaz_counties_national.zip"
GNIS_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/Topical/PopulatedPlaces_National_Text.zip"
# A third, smaller list of ~30,000 US towns with lat/lon (the one hometown_fixes.py suggest uses), tried
# after the Census and USGS lists: it has towns those miss, and it still places the common unincorporated
# towns (Ellenwood GA, Loxahatchee FL, Cortlandt Manor NY) when the USGS file couldn't be downloaded.
US_TOWNS_URL = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"

_SUFFIXES = re.compile(
    r"\s+(city and borough|consolidated government|metro(politan)? government|metro township|unified government|"
    r"urban county|municipality|charter township|city|town|township|village|borough|CDP|"
    r"comunidad|zona urbana|plantation)$",
    re.I,
)
_COUNTY_SUFFIX = re.compile(r"\s+(county|parish|borough|census area|municipality|city and borough)$", re.I)
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

# Names rosters use that don't match the official place name.
ALIASES = {
    ("brooklyn", "NY"): "new york", ("bronx", "NY"): "new york", ("the bronx", "NY"): "new york",
    ("queens", "NY"): "new york", ("staten island", "NY"): "new york", ("manhattan", "NY"): "new york",
    ("washington", "DC"): "washington", ("nashville", "TN"): "nashville-davidson",
    ("louisville", "KY"): "louisville/jefferson county", ("lexington", "KY"): "lexington-fayette",
    ("augusta", "GA"): "augusta-richmond county", ("athens", "GA"): "athens-clarke county",
    ("macon", "GA"): "macon-bibb county", ("honolulu", "HI"): "urban honolulu",
    ("boise", "ID"): "boise city", ("lake worth", "FL"): "lake worth beach",
    ("hilton head", "SC"): "hilton head island", ("ventura", "CA"): "san buenaventura",
    ("st. johns", "FL"): "saint johns", ("ponte vedra", "FL"): "ponte vedra beach",
    ("new york city", "NY"): "new york", ("nyc", "NY"): "new york",
    # common misspellings seen on rosters
    ("philadephia", "PA"): "philadelphia", ("san bernadino", "CA"): "san bernardino",
    ("carrolton", "TX"): "carrollton", ("carrolton", "GA"): "carrollton", ("suwannee", "GA"): "suwanee",
    ("silver springs", "MD"): "silver spring", ("hazelhurst", "MS"): "hazlehurst",
    ("stillwell", "KS"): "stilwell", ("fort meyers", "FL"): "fort myers", ("ft. meyers", "FL"): "fort myers",
    ("patterson", "NJ"): "paterson", ("owings mill", "MD"): "owings mills",
    ("tallahasee", "FL"): "tallahassee", ("tallahasse", "FL"): "tallahassee",
    ("gainsville", "VA"): "gainesville", ("gainsville", "FL"): "gainesville", ("gainsville", "GA"): "gainesville",
    ("kileen", "TX"): "killeen", ("massilon", "OH"): "massillon", ("wycoff", "NJ"): "wyckoff",
    ("newman", "GA"): "newnan", ("downington", "PA"): "downingtown", ("rivera beach", "FL"): "riviera beach",
    ("fredricksburg", "VA"): "fredericksburg", ("forth worth", "TX"): "fort worth",
    ("meridan", "MS"): "meridian", ("milbrook", "AL"): "millbrook", ("murrietta", "CA"): "murrieta",
    ("floyd knobs", "IN"): "floyds knobs", ("mabelton", "GA"): "mableton", ("rosenburg", "TX"): "rosenberg",
    ("douglassville", "GA"): "douglasville", ("pritchard", "AL"): "prichard", ("lynwood", "WA"): "lynnwood",
    ("ponte verde", "FL"): "ponte vedra beach", ("burlington city", "NJ"): "burlington",
    # short or informal names for the official place
    ("hallandale", "FL"): "hallandale beach", ("daytona", "FL"): "daytona beach",
    ("deerfield", "FL"): "deerfield beach", ("dania", "FL"): "dania beach",
    ("palos verdes", "CA"): "palos verdes estates", ("carmel", "CA"): "carmel-by-the-sea",
    ("la canada", "CA"): "la canada flintridge", ("vestavia", "AL"): "vestavia hills",
    ("fuquay", "NC"): "fuquay-varina", ("miami garden", "FL"): "miami gardens",
    ("mililani", "HI"): "mililani town", ("la cañada", "CA"): "la canada flintridge",
    ("shawnee mission", "KS"): "overland park", ("north chesterfield", "VA"): "chesterfield",
    ("south chesterfield", "VA"): "chesterfield", ("lake minneola", "FL"): "minneola",
    ("daniel island", "SC"): "charleston", ("west orlando", "FL"): "orlando", ("lake nona", "FL"): "orlando",
    # neighborhoods -> their city
    ("liberty city", "FL"): "miami", ("overtown", "FL"): "miami", ("little haiti", "FL"): "miami",
    ("west hills", "CA"): "los angeles", ("south central los angeles", "CA"): "los angeles",
    ("south central", "CA"): "los angeles", ("crenshaw", "CA"): "los angeles",
    ("valley glen", "CA"): "los angeles", ("east oakland", "CA"): "oakland", ("natomas", "CA"): "sacramento",
    ("mission bay", "CA"): "san diego", ("southeast san diego", "CA"): "san diego",
    ("east riverside", "CA"): "riverside", ("west philadelphia", "PA"): "philadelphia",
    ("lake highlands", "TX"): "dallas", ("kingwood park", "TX"): "houston",
    ("green valley ranch", "CO"): "denver", ("liliha", "HI"): "honolulu", ("papakolea", "HI"): "honolulu",
    ("p.g. county", "MD"): "prince george's", ("pg county", "MD"): "prince george's",
    # Oct 28: left unplaced after the Oct 27 runs (several sports)
    ("woodlands", "TX"): "the woodlands", ("castleton", "NY"): "castleton-on-hudson",
    ("briarcliff", "NY"): "briarcliff manor", ("ny mills", "NY"): "new york mills",
    ("huntington", "CA"): "huntington beach", ("north richland", "TX"): "north richland hills",
    ("pompano", "FL"): "pompano beach", ("altamonte", "FL"): "altamonte springs", ("slc", "UT"): "salt lake city",
    ("south hayward", "CA"): "hayward", ("south buffalo", "NY"): "buffalo", ("east irondequoit", "NY"): "irondequoit",
    ("point pleasant boro", "NJ"): "point pleasant", ("hopewell valley", "NJ"): "hopewell",
    ("shoreham-wading river", "NY"): "shoreham", ("monroe-woodbury", "NY"): "monroe", ("haddam neck", "CT"): "haddam",
    ("brandon valley", "SD"): "brandon", ("sauk prairie", "WI"): "prairie du sac", ("west muskingum", "OH"): "zanesville",
    ("rehoboth", "DE"): "rehoboth beach", ("dr. phillips", "FL"): "doctor phillips", ("dr phillips", "FL"): "doctor phillips",
    ("kaneohe 'oahu", "HI"): "kaneohe", ("manoa", "HI"): "urban honolulu", ("venice beach", "CA"): "los angeles",
    ("arleta", "CA"): "los angeles", ("rockaway beach", "NY"): "new york", ("north rockland", "NY"): "stony point",
    ("virgina beach", "VA"): "virginia beach", ("tuscon", "AZ"): "tucson", ("pittsburg", "PA"): "pittsburgh",
    ("hillard", "OH"): "hilliard", ("bayton", "TX"): "baytown", ("coatsville", "PA"): "coatesville",
    ("mainville", "OH"): "maineville", ("landenburg", "PA"): "landenberg", ("chillocothe", "OH"): "chillicothe",
    ("pleasonton", "CA"): "pleasanton", ("vaccaville", "CA"): "vacaville", ("fredricksburg", "TX"): "fredericksburg",
    ("carrolton", "OH"): "carrollton", ("san jaun", "PR"): "san juan",
    ("cardiff", "CA"): "encinitas", ("cardiff by the sea", "CA"): "encinitas", ("lake travis", "TX"): "lakeway",
    ("indian land", "SC"): "fort mill", ("armwood", "FL"): "seffner", ("chichester", "PA"): "marcus hook",
    ("milmont park", "PA"): "folsom", ("north dinwiddie", "VA"): "dinwiddie", ("north prince george", "VA"): "prince george",
    ("onondaga nation", "NY"): "nedrow", ("imperial valley", "CA"): "el centro", ("tri-cities", "WA"): "kennewick",
    ("tri cities", "WA"): "kennewick", ("topsail island", "NC"): "surf city", ("smoky mountain", "NC"): "sylva",
    # school districts written as the hometown -> the district's main town
    ("sachem", "NY"): "holbrook", ("gates chili", "NY"): "gates", ("gates-chili", "NY"): "gates",
    ("harborfields", "NY"): "greenlawn", ("minisink valley", "NY"): "slate hill", ("shoreham wading river", "NY"): "shoreham",
    ("honeoye falls-lima", "NY"): "honeoye falls", ("maine-endwell", "NY"): "endwell", ("niagara wheatfield", "NY"): "sanborn",
    ("bayport bluepoint", "NY"): "bayport", ("bayport-blue point", "NY"): "bayport", ("west irondequoit", "NY"): "irondequoit",
    ("strath haven", "PA"): "wallingford", ("wallenpaupack", "PA"): "hawley", ("st. michael-albertville", "MN"): "st. michael",
    ("liberty eylau", "TX"): "texarkana", ("liberty-eylau", "TX"): "texarkana", ("north harford", "MD"): "pylesville",
    ("pocono mountains", "PA"): "pocono", ("poconos", "PA"): "pocono", ("north minneapolis", "MN"): "minneapolis",
    ("south jamaica", "NY"): "new york", ("tampa bay", "FL"): "tampa", ("syosset, long island", "NY"): "syosset",
    # misspellings and short names
    ("nobelsville", "IN"): "noblesville", ("westboro", "MA"): "westborough", ("marlboro", "MD"): "upper marlboro",
    ("watervilet", "NY"): "watervliet", ("fuquay-varnia", "NC"): "fuquay-varina", ("forrest hill", "MD"): "forest hill",
    ("stanford", "CT"): "stamford", ("inver grove", "MN"): "inver grove heights", ("lasuer", "MN"): "le sueur",
    ("romona", "CA"): "ramona", ("no. scituate", "RI"): "north scituate", ("alex city", "AL"): "alexander city",
    ("sandy spring", "GA"): "sandy springs", ("st. mckinney", "TX"): "mckinney", ("phillips ranch", "CA"): "pomona",
    ("weston ranch", "CA"): "stockton", ("lake view terrace", "CA"): "los angeles", ("manitou", "CO"): "manitou springs",
    ("oaha", "HI"): "urban honolulu", ("village of lakewood", "IL"): "lakewood",
    # Haudenosaunee and other nations on lacrosse rosters -> the community's town
    ("akwesasne", "NY"): "hogansburg", ("akwesasne reservation", "NY"): "hogansburg", ("st. regis mohawk", "NY"): "hogansburg",
    ("onondaga", "NY"): "nedrow", ("seneca nation", "NY"): "salamanca", ("the seneca nation", "NY"): "salamanca",
    ("oneida nation", "WI"): "oneida", ("tuscarora nation", "NY"): "lewiston", ("tonawanda seneca nation", "NY"): "basom",
}
# First Nations communities across the border, as lacrosse rosters write them ("Kahnawake Mohawk Territory")
NATIONS_ABROAD = {"kahnawake": ("Kahnawake", "QC", "Canada"), "tyendinaga": ("Deseronto", "ON", "Canada"),
                  "six nations": ("Ohsweken", "ON", "Canada"), "six nations of the grand river": ("Ohsweken", "ON", "Canada"),
                  "kanesatake": ("Oka", "QC", "Canada"), "wahta": ("Bala", "ON", "Canada"),
                  "akwesasne": ("Akwesasne", "ON", "Canada")}

# Islands and areas with no town of that name: a dot in the middle of where people live (precision "region")
AREAS = {
    ("longisland", "NY"): (40.80, -73.20), ("kentisland", "MD"): (38.95, -76.32), ("whidbeyisland", "WA"): (48.10, -122.60),
    ("oahu", "HI"): (21.40, -157.90), ("maui", "HI"): (20.83, -156.40), ("bigisland", "HI"): (19.60, -155.50),
    ("kauai", "HI"): (22.05, -159.50), ("cape cod", "MA"): (41.70, -70.30),
    ("marthasvineyard", "MA"): (41.40, -70.62), ("outerbanks", "NC"): (35.90, -75.60), ("eastshore", "MD"): (38.80, -76.00),
    ("southbay", "CA"): (33.85, -118.35), ("inlandempire", "CA"): (34.00, -117.40), ("bayarea", "CA"): (37.70, -122.20),
    ("southjersey", "NJ"): (39.75, -75.00), ("northshore", "MA"): (42.55, -70.90), ("westchester", "NY"): (41.12, -73.79),
    ("hamptons", "NY"): (40.93, -72.30), ("thehamptons", "NY"): (40.93, -72.30), ("lowcountry", "SC"): (32.70, -80.20),
}

# Coarse fallbacks (geo_precision = "region"/"country").
TERRITORIES = {"AS": (-14.2756, -170.7020), "GU": (13.4443, 144.7937), "VI": (18.3358, -64.8963),
               "MP": (15.1850, 145.7467), "PR": (18.2208, -66.5901)}
# Canadian provinces, for a town the offline lists can't place (they're US only): better than the middle
# of Canada. Roughly where most people in each province live.
PROVINCES = {"AB": (52.27, -113.81), "BC": (49.89, -122.0), "MB": (49.90, -98.0), "SK": (51.5, -105.5),
             "ON": (44.0, -79.5), "QC": (46.5, -72.5), "NS": (45.0, -63.5), "NB": (46.0, -66.0),
             "PE": (46.25, -63.13), "NL": (47.6, -53.0), "YT": (60.72, -135.06), "NT": (62.45, -114.37),
             "NU": (63.75, -68.52)}
COUNTRIES = {
    "Australia": (-25.27, 133.78), "Canada": (56.13, -106.35), "New Zealand": (-40.90, 174.89),
    "England": (52.36, -1.17), "United Kingdom": (55.38, -3.44), "Germany": (51.17, 10.45),
    "Nigeria": (9.08, 8.68), "Bahamas": (25.03, -77.40), "Jamaica": (18.11, -77.30),
    "Mexico": (23.63, -102.55), "Samoa": (-13.76, -172.10), "Tonga": (-21.18, -175.20),
    "Japan": (36.20, 138.25), "France": (46.23, 2.21), "Ireland": (53.41, -8.24),
    "Sweden": (60.13, 18.64), "Netherlands": (52.13, 5.29), "Austria": (47.52, 14.55),
    "Brazil": (-14.24, -51.93), "Ghana": (7.95, -1.02), "Cameroon": (7.37, 12.35),
    "Denmark": (56.26, 9.50), "Norway": (60.47, 8.47), "Finland": (61.92, 25.75),
    "Italy": (41.87, 12.57), "Spain": (40.46, -3.75), "Switzerland": (46.82, 8.23),
    "Belgium": (50.50, 4.47), "Poland": (51.92, 19.15), "Kenya": (-0.02, 37.91),
    "South Africa": (-30.56, 22.94), "Senegal": (14.50, -14.45), "Congo": (-4.04, 21.76),
    "Haiti": (18.97, -72.29), "Dominican Republic": (18.74, -70.16), "Puerto Rico": (18.22, -66.59),
    "Scotland": (56.49, -4.20), "Wales": (52.13, -3.78), "Fiji": (-17.71, 178.07),
    "Israel": (31.05, 34.85), "Czech Republic": (49.82, 15.47), "Ukraine": (48.38, 31.17),
    "Northern Ireland": (54.79, -6.49), "China": (35.86, 104.20), "Serbia": (44.02, 21.01),
    "Hungary": (47.16, 19.50), "South Korea": (35.91, 127.77), "Greece": (39.07, 21.82),
    "Russia": (61.52, 105.32), "Egypt": (26.82, 30.80), "Liberia": (6.43, -9.43), "Syria": (34.80, 38.99),
    "Panama": (8.54, -80.78), "Venezuela": (6.42, -66.59), "Croatia": (45.10, 15.20),
    "Gabon": (-0.80, 11.61), "Democratic Republic of the Congo": (-4.04, 21.76),
    "United Arab Emirates": (23.42, 53.85), "Guyana": (4.86, -58.93), "Portugal": (39.40, -8.22),
    "Colombia": (4.57, -74.30), "Argentina": (-38.42, -63.62), "Chile": (-35.68, -71.54),
    "Philippines": (12.88, 121.77), "India": (20.59, 78.96), "Turkey": (38.96, 35.24),
    "Trinidad and Tobago": (10.69, -61.22), "Puerto Rico": (18.22, -66.59), "Iceland": (64.96, -19.02),
    "Lithuania": (55.17, 23.88), "Latvia": (56.88, 24.60), "Estonia": (58.60, 25.01),
    "Slovenia": (46.15, 14.99), "Slovakia": (48.67, 19.70), "Romania": (45.94, 24.97),
    "Bulgaria": (42.73, 25.49), "Bosnia and Herzegovina": (43.92, 17.68), "Montenegro": (42.71, 19.37),
    "Angola": (-11.20, 17.87), "Uganda": (1.37, 32.29), "Ethiopia": (9.15, 40.49), "Zimbabwe": (-19.02, 29.15),
    "Sierra Leone": (8.46, -11.78), "Ivory Coast": (7.54, -5.55), "Togo": (8.62, 0.82), "Benin": (9.31, 2.32),
    "Rwanda": (-1.94, 29.87), "Tanzania": (-6.37, 34.89), "Sudan": (12.86, 30.22), "South Sudan": (6.88, 31.31),
    "Morocco": (31.79, -7.09), "Lebanon": (33.85, 35.86), "Jordan": (30.59, 36.24), "Iran": (32.43, 53.69),
    "Belize": (17.19, -88.50), "Honduras": (15.20, -86.24), "Costa Rica": (9.75, -83.75),
    "El Salvador": (13.79, -88.90), "Guatemala": (15.78, -90.23), "Cuba": (21.52, -77.78),
    "Barbados": (13.19, -59.54), "Bermuda": (32.32, -64.76), "Cayman Islands": (19.31, -81.25),
    "Peru": (-9.19, -75.02), "Ecuador": (-1.83, -78.18), "Vietnam": (14.06, 108.28), "Thailand": (15.87, 100.99),
    "Taiwan": (23.70, 120.96), "Singapore": (1.35, 103.82), "Papua New Guinea": (-6.31, 143.96),
    "French Polynesia": (-17.68, -149.41), "Cook Islands": (-21.24, -159.78),
    "Curacao": (12.17, -68.99), "Suriname": (3.92, -56.03), "Qatar": (25.35, 51.18), "Hong Kong": (22.32, 114.17),
    "British Virgin Islands": (18.42, -64.64), "Aruba": (12.52, -69.97), "Rwanda": (-1.94, 29.87),
}


def norm_city(name: str) -> str:
    # "La Cañada" and "La Canada" should match; so should "St.Louis" and "St. Louis".
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = n.lower().strip().replace("’", "'").replace("‘", "'").replace("ʻ", "'")
    n = re.sub(r"^(st|ste)(\.\s*|\s+)", "saint ", n)
    n = re.sub(r"^ft(\.\s*|\s+)", "fort ", n)
    n = re.sub(r"^mt(\.\s*|\s+)", "mount ", n)
    n = re.sub(r"^n\.\s+", "north ", n)
    n = re.sub(r"^s\.\s+", "south ", n)
    n = re.sub(r"^e\.\s*", "east ", n)        # Oct 28: "E. Setauket", "W. Bloomfield"
    n = re.sub(r"^w\.\s*", "west ", n)
    n = re.sub(r"\bmtn\b\.?", "mountain", n)    # "Stone Mtn"; the same words in the Census names are spelled out
    n = re.sub(r"\bjct\b\.?", "junction", n)    # "Essex Jct."
    n = re.sub(r"\bhts\b\.?", "heights", n)
    n = re.sub(r"\bspgs?\b\.?", "springs", n)
    n = re.sub(r"\bpt\.\s*", "point ", n)
    return re.sub(r"[^a-z0-9]", "", n)


# ---------------------------------------------------------------------------
# data loading

def _download(url: str, local: Path, label: str) -> Path:
    if not local.exists():
        print(f"Downloading {label} ...")
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        local.write_bytes(r.content)
    return local


def _read_zip_table(path: Path, delimiter: str) -> tuple[dict[str, int], list[list[str]]]:
    with zipfile.ZipFile(path) as zf:
        inner = next(n for n in zf.namelist() if n.lower().endswith((".txt", ".csv")))
        raw = zf.read(inner)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    # These files are plain tab/pipe text with no quoting. Read them that way: with the default
    # settings, one stray '"' in a place name swallows thousands of following rows (that is how
    # Rabun Gap GA and Ellenwood GA went missing).
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quoting=csv.QUOTE_NONE)
    header = [h.strip().lower() for h in next(reader)]
    return {h: i for i, h in enumerate(header)}, [[c.strip() for c in row] for row in reader if row]


class Gazetteer:
    def __init__(self):
        CACHE.mkdir(exist_ok=True)
        self.places: dict[tuple, tuple] = {}       # (norm name, ST) -> (lat, lon, rank)
        self.by_name: dict[str, list] = {}         # norm name -> [(aland, ST, lat, lon)] incorporated places
        self.gnis: dict[tuple, tuple] = {}
        self.counties: dict[tuple, tuple] = {}
        self._load_census(GAZ_PLACES, priority=0)
        self._load_census(GAZ_COUSUBS, priority=1)
        self._load_counties()
        self._load_gnis()
        self.towns: dict[tuple, tuple] = {}        # (norm name, ST) -> (lat, lon), the smaller US town list
        self._load_us_towns()
        # Each state's middle, as the average of its towns (so roughly where people live), for a hometown
        # that gives only a state ("MN", "Maryland"): a dot in the state, marked "region" like a province
        sums: dict[str, list] = {}
        for (_, st), (lat, lon, _) in self.places.items():
            t = sums.setdefault(st, [0.0, 0.0, 0])
            t[0] += lat; t[1] += lon; t[2] += 1
        self.state_center = {st: (a / n, b / n) for st, (a, b, n) in sums.items() if n}

    def _add_place(self, key, lat, lon, rank):
        if key not in self.places or rank < self.places[key][2]:
            self.places[key] = (lat, lon, rank)

    def _load_census(self, fname: str, priority: int) -> None:
        path = _download(GAZ_BASE + fname, CACHE / fname, f"{fname} from the Census Bureau")
        col, rows = _read_zip_table(path, "\t")
        for row in rows:
            state, name = row[col["usps"]], row[col["name"]]
            lat, lon = float(row[col["intptlat"]]), float(row[col["intptlong"]])
            is_cdp = name.endswith(" CDP")
            base = _SUFFIXES.sub("", re.sub(r"\s*\(balance\)$", "", name))
            rank = priority * 10 + (1 if is_cdp else 0)
            names = {base}
            paren = re.match(r"^(.*?)\s*\((.+)\)$", base)   # "San Buenaventura (Ventura)"
            if paren:
                names |= {paren.group(1), paren.group(2)}
            for n in names:
                self._add_place((norm_city(n), state), lat, lon, rank)
            aland = float(row[col["aland"]]) if "aland" in col and row[col["aland"]] else 0.0
            for n in names:  # incorporated places rank above CDPs of the same name, and both above towns
                # and townships (county subdivisions, Oct 28: so "Southington", "Glastonbury" and "Vestal",
                # New England and New York towns given with no state, can be guessed too)
                rank_here = (0 if is_cdp else 1) if priority == 0 else -1
                self.by_name.setdefault(norm_city(n), []).append((rank_here, aland, state, lat, lon))

    def _load_counties(self) -> None:
        path = _download(GAZ_BASE + GAZ_COUNTIES, CACHE / GAZ_COUNTIES, "county centroids from the Census Bureau")
        col, rows = _read_zip_table(path, "\t")
        for row in rows:
            name = _COUNTY_SUFFIX.sub("", row[col["name"]])
            self.counties[(norm_city(name), row[col["usps"]])] = (float(row[col["intptlat"]]),
                                                                  float(row[col["intptlong"]]))

    def _load_gnis(self) -> None:
        local = CACHE / "PopulatedPlaces_National_Text.zip"
        try:
            path = _download(GNIS_URL, local, "USGS populated places (one time, ~20 MB)")
            col, rows = _read_zip_table(path, "|")
        except Exception as exc:  # optional, but it places thousands of players
            local.unlink(missing_ok=True)
            print("\n" + "!" * 78)
            print(f"WARNING: couldn't load the USGS populated places file ({exc}).")
            print("Unincorporated towns and neighborhoods (Ellenwood GA, Mililani HI, Cypress TX, ...)")
            print("won't be placed. Download it in a browser from")
            print(f"  {GNIS_URL}")
            print(f"or the 'Populated Places' national text file at https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data")
            print(f"save it as {local}, and run this again.")
            print("!" * 78 + "\n")
            return
        name_c = next((i for h, i in col.items() if h in ("feature_name", "featurename")), None)
        st_alpha = next((i for h, i in col.items() if h == "state_alpha"), None)
        st_name = next((i for h, i in col.items() if h == "state_name"), None)
        lat_c = next((i for h, i in col.items() if "lat_dec" in h), None)
        lon_c = next((i for h, i in col.items() if "long_dec" in h or "lon_dec" in h), None)
        if None in (name_c, lat_c, lon_c) or (st_alpha is None and st_name is None):
            print(f"\nWARNING: the USGS file has unexpected columns {list(col)[:12]}; "
                  "unincorporated towns won't be placed.\n")
            return
        for row in rows:
            try:
                lat, lon = float(row[lat_c]), float(row[lon_c])
            except (ValueError, IndexError):
                continue
            if not lat or not lon:
                continue
            st = row[st_alpha] if st_alpha is not None else _STATE_BY_NAME.get(row[st_name].lower(), "")
            key = (norm_city(row[name_c]), st)
            self.gnis.setdefault(key, (lat, lon))
        print(f"  USGS populated places loaded: {len(self.gnis):,} names")

    def _load_us_towns(self) -> None:
        local = CACHE / "us_cities.csv"
        try:
            _download(US_TOWNS_URL, local, "the US town list (one time, ~2 MB)")
            with open(local, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    try:
                        self.towns.setdefault((norm_city(r["CITY"]), r["STATE_CODE"]),
                                              (float(r["LATITUDE"]), float(r["LONGITUDE"])))
                    except (KeyError, ValueError):
                        continue
        except Exception as exc:   # optional: the Census and USGS lists place nearly everything
            local.unlink(missing_ok=True)
            print(f"  (couldn't load the US town list: {exc}; carrying on without it)")

    # -----------------------------------------------------------------------
    def lookup_us(self, city: str, state: str) -> tuple | None:
        """Return (lat, lon, source, precision) for a US city/state, or None."""
        if not city:
            return None
        c = city.lower().strip()
        candidates = [ALIASES.get((c, state)), city]
        stripped = re.sub(r"\s+(township|twp\.?|village|borough|boro)$", "", city, flags=re.I)
        if stripped != city:
            candidates.append(stripped)
        for cand in filter(None, candidates):
            k = (norm_city(cand), state)
            if k in self.places:
                return (*self.places[k][:2], "census", "city")
            if (norm_city(cand) + "city", state) in self.places:          # "Amite" -> "Amite City"
                return (*self.places[(norm_city(cand) + "city", state)][:2], "census", "city")
            if k in self.gnis:
                return (*self.gnis[k], "usgs", "city")
        for cand in filter(None, candidates):
            if (norm_city(cand), state) in self.towns:
                return (*self.towns[(norm_city(cand), state)], "us_towns", "city")
        for cand in filter(None, candidates):
            county = norm_city(_COUNTY_SUFFIX.sub("", re.sub(r"\s+co\.?$", " county", cand, flags=re.I)))
            if (county, state) in self.counties:
                return (*self.counties[(county, state)], "census_county", "county")
        for cand in filter(None, candidates):
            if (norm_city(cand), state) in AREAS:
                return (*AREAS[(norm_city(cand), state)], "area", "region")
        return None

    def lookup_no_state(self, city: str, prefer: list[str] | tuple = ()) -> tuple | None:
        """'Houston' with no state -> a place with that name: in the first of `prefer` (the states
        the player's school recruits most) that has one, otherwise the largest one in the country."""
        if city.lower().strip() in ("honolulu", "urban honolulu"):
            city = "urban honolulu"
        city = re.sub(r"\s+(township|twp\.?)$", "", city.strip(), flags=re.I)   # "Liberty Township"
        options = self.by_name.get(norm_city(city))
        if not options:
            # A known other name in some state ("La Canada" -> La Canada Flintridge CA, "Queens" -> New York,
            # "Seneca Nation" -> Salamanca NY)
            c = city.lower()
            for (alias, st), real in ALIASES.items():
                if alias == c:
                    hit = self.lookup_us(real, st)
                    if hit:
                        return (hit[0], hit[1], f"census_guess_{st}", "city_guess")
            return None
        # A town or CDP in the first preferred state that has one; then a township there (Oct 28: so a
        # Muskingum player's "Columbus" is Columbus OH, not Columbus Township PA); then the largest town anywhere.
        towns = [o for o in options if o[0] >= 0]
        for group in (towns, options):
            for st in prefer:
                here = [o for o in group if o[2] == st]
                if here:
                    _, _, st, lat, lon = max(here)
                    return (lat, lon, f"census_guess_{st}", "city_guess")
        _, _, st, lat, lon = max(towns or options)
        return (lat, lon, f"census_guess_{st}", "city_guess")


class WorldCities:
    """Towns outside the US, from GeoNames' list of every place with 500+ people (the geonamescache
    package: pip install geonamescache). Without it, places abroad get their province's or country's dot."""

    # The geocoder's country names -> ISO codes, where GeoNames calls the country something else
    EXTRA = {"England": "GB", "Scotland": "GB", "Wales": "GB", "Northern Ireland": "GB", "United Kingdom": "GB",
             "South Korea": "KR", "Czech Republic": "CZ", "Ivory Coast": "CI", "Democratic Republic of the Congo": "CD",
             "Congo": "CG", "Bahamas": "BS", "Russia": "RU", "Vietnam": "VN", "Taiwan": "TW", "Iran": "IR",
             "Syria": "SY", "Curacao": "CW", "Hong Kong": "HK", "Samoa": "WS", "American Samoa": "AS",
             "Trinidad and Tobago": "TT", "British Virgin Islands": "VG", "Macedonia": "MK", "North Macedonia": "MK",
             "Bosnia and Herzegovina": "BA", "Saint Lucia": "LC", "Antigua and Barbuda": "AG", "Laos": "LA",
             "Micronesia": "FM", "Palestine": "PS", "Cape Verde": "CV", "Eswatini": "SZ", "Swaziland": "SZ"}
    # GeoNames' codes for the Canadian provinces -> the postal codes the parser gives
    CA_ADMIN1 = {"01": "AB", "02": "BC", "03": "MB", "04": "NB", "05": "NL", "07": "NS", "08": "ON", "09": "PE",
                 "10": "QC", "11": "SK", "12": "YT", "13": "NT", "14": "NU"}
    BIG = 100_000      # a town given with no state or country is only looked up abroad if it's this big (Tokyo)

    def __init__(self):
        self.by_key: dict[tuple, list] = {}      # (norm name, ISO) -> [(population, admin1, lat, lon)]
        self.big: dict[str, tuple] = {}          # norm name -> the largest town of that name, if it is big
        self.iso: dict[str, str] = {}
        self.ok = False
        try:
            import geonamescache
        except ImportError:
            print("  (no world town list: pip install geonamescache to place towns abroad on their own dots)")
            return
        gc = geonamescache.GeonamesCache(min_city_population=500)
        for code, c in gc.get_countries().items():
            self.iso[c["name"].lower()] = code
            self.iso[re.sub(r"^the\s+", "", c["name"].lower())] = code     # "The Netherlands"
        for name, code in self.EXTRA.items():
            self.iso[name.lower()] = code
        for c in gc.get_cities().values():
            entry = (int(c.get("population") or 0), c.get("admin1code", ""), float(c["latitude"]), float(c["longitude"]))
            names = {norm_city(c["name"])} | {norm_city(a) for a in (c.get("alternatenames") or []) if a}
            for n in filter(None, names):
                self.by_key.setdefault((n, c["countrycode"]), []).append(entry)
            n = norm_city(c["name"])
            if entry[0] >= self.BIG and entry[0] > self.big.get(n, (0,))[0]:
                self.big[n] = entry
        self.ok = True
        print(f"  GeoNames towns abroad loaded: {len(self.by_key):,} names")

    def lookup(self, city: str, country: str, state: str = "") -> tuple | None:
        if not (self.ok and city):
            return None
        code = self.iso.get(country.lower())
        options = self.by_key.get((norm_city(city), code)) if code else None
        if not options:
            return None
        if code == "CA" and state:
            here = [o for o in options if self.CA_ADMIN1.get(o[1]) == state]
            options = here or options
        _, _, lat, lon = max(options)
        return (lat, lon, "geonames", "city")

    def lookup_big(self, city: str) -> tuple | None:
        hit = self.big.get(norm_city(city)) if self.ok and city else None
        return (hit[2], hit[3], "geonames", "city") if hit else None


class Nominatim:
    URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, contact: str):
        self.path = CACHE / "nominatim.json"
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.headers = {"User-Agent": f"football-recruiting-map/1.0 ({contact})"}
        self.last = 0.0
        self.calls = 0      # new answers from OpenStreetMap (saved)
        self.hits = 0       # answers reused from earlier runs
        self.failed = 0     # errors; retried next run
        self.slowdowns = 0  # times OpenStreetMap asked us to slow down
        if self.cache:
            print(f"  {len(self.cache):,} online answers saved from earlier runs ({self.path})")

    def _get(self, query: str):
        wait = 1.1 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        return requests.get(self.URL, params={"q": query, "format": "json", "limit": 1},
                            headers=self.headers, timeout=30)

    def lookup(self, query: str):
        if query in self.cache:
            self.hits += 1
            return self.cache[query]
        try:
            r = self._get(query)
            if r.status_code in (429, 503):   # told to slow down: pause, then try once more
                self.slowdowns += 1
                time.sleep(30)
                r = self._get(query)
            if not r.ok:          # still refused: don't save, so it's retried next run
                self.failed += 1
                return None
            data = r.json()
        except (requests.RequestException, ValueError):
            self.failed += 1
            return None           # network trouble: don't save, or the town is never retried
        result = (float(data[0]["lat"]), float(data[0]["lon"])) if data else None
        self.cache[query] = result  # "no such place" is a real answer, so that one is cached
        self.calls += 1
        if self.calls % 25 == 0:
            self.path.write_text(json.dumps(self.cache))
            print(f"  ... {self.calls} online lookups")
        return result

    def save(self):
        self.path.write_text(json.dumps(self.cache))
        print(f"  online: {self.calls:,} new lookups, {self.hits:,} reused from earlier runs, "
              f"{self.failed:,} failed (retried next run)"
              + (f", slowed down by OpenStreetMap {self.slowdowns}x" if self.slowdowns else ""))
        if self.failed:
            print("  Many failures usually mean OpenStreetMap is limiting you: wait an hour and re-run,")
            print("  and make sure --contact is a real email address.")


# =============================================================================
# Hometown corrections: suggested fixes for strings the geocoder couldn't place.
# Edit CITY_FIX / OVERRIDE here, or edit hometown_corrections.csv directly.
# =============================================================================

# --- State / country normalisation -------------------------------------------
_USPS = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM",
    "NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA",
    "WV","WI","WY",
}
STATE_ALIASES = {
    # full names
    "alabama":"AL","alaska":"AK","arizona":"AZ","arkansas":"AR","california":"CA",
    "colorado":"CO","connecticut":"CT","delaware":"DE","florida":"FL","georgia":"GA",
    "hawaii":"HI","idaho":"ID","illinois":"IL","indiana":"IN","iowa":"IA","kansas":"KS",
    "kentucky":"KY","louisiana":"LA","maine":"ME","maryland":"MD","massachusetts":"MA",
    "michigan":"MI","minnesota":"MN","mississippi":"MS","missouri":"MO","montana":"MT",
    "nebraska":"NE","nevada":"NV","new hampshire":"NH","new jersey":"NJ",
    "new mexico":"NM","new york":"NY","north carolina":"NC","north dakota":"ND",
    "ohio":"OH","oklahoma":"OK","oregon":"OR","pennsylvania":"PA","rhode island":"RI",
    "south carolina":"SC","south dakota":"SD","tennessee":"TN","texas":"TX","utah":"UT",
    "vermont":"VT","virginia":"VA","washington":"WA","west virginia":"WV",
    "wisconsin":"WI","wyoming":"WY",
    # AP-style and misspellings seen in this file
    "ala":"AL","alab":"AL","ariz":"AZ","ari":"AZ","ark":"AR","calif":"CA","cal":"CA",
    "cali":"CA","ca":"CA","cailf":"CA","calf":"CA","claif":"CA","caif":"CA",
    "callif":"CA","calilf":"CA","colo":"CO","conn":"CT","dela":"DE","d.c":"DC",
    "fla":"FL","fia":"FL","forida":"FL","ga":"GA","haw":"HI","hawa'i":"HI",
    "hawai'i":"HI","o'ahu":"HI","oahu":"HI","ill":"IL","ind":"IN","kan":"KS","ky":"KY",
    "la":"LA","louisanna":"LA","louisianna":"LA","lousiana":"LA","mass":"MA",
    "md":"MD","mad":"MA","mich":"MI","minn":"MN","miss":"MS","mississippit":"MS",
    "missississippi":"MS","mis":"MO","misourri":"MO","mo":"MO","neb":"NE","nev":"NV",
    "n.c":"NC","n.j":"NJ","n.jj":"NJ","n.y":"NY","oh":"OH","ore":"OR","pa":"PA",
    "s.c":"SC","tenn":"TN","tenneesse":"TN","tex":"TX","texa":"TX","teas":"TX",
    "tesxas":"TX","tx":"TX","u.t":"UT","va":"VA","wash":"WA","wahs":"WA","wisc":"WI",
}
COUNTRY_ALIASES = {
    "south america": None,  # "Guyana, South America" -> country is the city field
    "democratic republic of congo":"Democratic Republic of the Congo",
    "dr of the congo":"Democratic Republic of the Congo",
    "kwara state of nigeria":"Nigeria","nigeria":"Nigeria",
    "czech rep":"Czech Republic","canda":"Canada","canada":"Canada",
    "german":"Germany","austrailia":"Australia","australia":"Australia",
    "american samoa":"American Samoa","america samoa":"American Samoa",
    "american samoa tuala":"American Samoa","uae":"United Arab Emirates",
}

# --- City spelling fixes (verified, high confidence) -------------------------
# These apply whatever the state is, so real towns (Greeneville TN, Taylorville IL,
# Jamesville NY, Eldorado TX, Lubeck WV) must not be "fixed" here. Use OVERRIDE for those.
CITY_FIX = {
    "Warner Robbins":"Warner Robins","North Olmstead":"North Olmsted",
    "Lundhurst":"Lyndhurst","Dearfield Beach":"Deerfield Beach",
    "Wiloughby":"Willoughby","Tamasse":"Tamassee","Bogalousa":"Bogalusa",
    "Massillion":"Massillon","Boyton Beach":"Boynton Beach",
    "Rohnhert Park":"Rohnert Park","Kailu-a-Kona":"Kailua-Kona",
    "Kailug-Kona":"Kailua-Kona","Pine Brooke":"Pine Brook",
    "Pfulgerville":"Pflugerville","Plugerville":"Pflugerville","Wailuki":"Wailuku",
    "Belleuve":"Bellevue","Bellvue":"Bellevue","Brookesville":"Brooksville",
    "Peculair":"Peculiar","Lawrencville":"Lawrenceville",
    "Fort Lauderale":"Fort Lauderdale","Ft. Lauderdale":"Fort Lauderdale",
    "Fontanay":"Fontana","Pittsurgh":"Pittsburgh","Musketine":"Muscatine",
    "Midlothain":"Midlothian","Merreville":"Merrillville","Collerville":"Collierville",
    "Antich":"Antioch","Sisun City":"Suisun City","Coster":"Closter","Napes":"Naples",
    "Talassee":"Tallassee","Mendenahall":"Mendenhall","Stateboro":"Statesboro",
    "Lexingon":"Lexington","Minneaplois":"Minneapolis","Pensecola":"Pensacola",
    "Pensacoloa":"Pensacola","Fairburgn":"Fairburn","Zephryhills":"Zephyrhills",
    "Crowly":"Crowley","Forrrest City":"Forrest City","Rockhill":"Rock Hill",
    "Blooming":"Bloomington","Harriston City":"Harrison City",
    "Killenn":"Killeen","Farminton":"Farmington","Mahasset":"Manhasset",
    "Strausburg":"Strasburg","Alendale":"Allendale","Kihel":"Kihei",
    "Vorrhees":"Voorhees","Winston-Salen":"Winston-Salem","Winson-Salem":"Winston-Salem",
    "LeGrange Park":"La Grange Park","Hillsdide":"Hillside","Elizabeh":"Elizabeth",
    "PG County":"Prince George's County","Greenvillle":"Greenville",
    "Washintgon":"Washington","Washington D.C.":"Washington","Clearrwater":"Clearwater",
    "Colingdale":"Collingdale","Centnnial":"Centennial","Pheniz":"Phenix City",
    "Hattiesberg":"Hattiesburg","Kahuka":"Kahuku","Plesanton":"Pleasanton",
    "Smryna":"Smyrna","Fritchburg":"Fitchburg","Maryvill":"Maryville",
    "Cookesville":"Cooksville","Eynan":"Eynon","Saiisbury":"Salisbury",
    "Plainfiled":"Plainfield","Planfield":"Plainfield","Lynnvile":"Lynnville",
    "Johns Greek":"Johns Creek","North Richlands":"North Richland Hills",
    "Olmstead Falls":"Olmsted Falls","Apopla":"Apopka","Durhman":"Durham",
    "Ewa":"Ewa Beach","McCleansville":"McLeansville","Carelton":"Carleton",
    "Kingsports":"Kingsport","Pratville":"Prattville","Tallhassee":"Tallahassee",
    "Tahallassee":"Tallahassee","Riveria Beach":"Riviera Beach",
    "Port Sulpher":"Port Sulphur","Carrol Stream":"Carol Stream",
    "New Reigel":"New Riegel","Bridgewatwer":"Bridgewater","Nashvillle":"Nashville",
    "Henrica":"Henrico","Floirissant":"Florissant",
    "Tuscalo":"Tuscola","Bay Minnett":"Bay Minette","Port St. Luice":"Port St. Lucie",
    "Browns Summitt":"Browns Summit","Clarkville":"Clarksville",
    "Fayettville":"Fayetteville","Slattington":"Slatington","Novao":"Novato",
    "Pompana Beach":"Pompano Beach","Honoulu":"Honolulu","Hunstville":"Huntsville",
    "Kahalu'u":"Kahaluu","Pasdena":"Pasadena","Port Neches Grove":"Port Neches",
    "Hai'ula":"Hauula","Hauuloa":"Hauula","Tuwila":"Tukwila","Mulkiteo":"Mukilteo",
    "Couer d'Alene":"Coeur d'Alene","Lompac":"Lompoc","Hyram":"Hyrum",
    "Reistertown":"Reisterstown","Shereville":"Schererville",
    "Rancho Cucamunga":"Rancho Cucamonga","Racnho Cucamonga":"Rancho Cucamonga",
    "Rancho Cucamongo":"Rancho Cucamonga","Rancho Cucamona":"Rancho Cucamonga",
    "Ceveland":"Cleveland","Godly":"Godley","Nacogoches":"Nacogdoches",
    "Livemore":"Livermore","Floyds Knobb":"Floyds Knobs","Narcross":"Norcross",
    "Wordridge":"Woodridge","Damascs":"Damascus","Bourbannais":"Bourbonnais",
    "Centeron":"Centerton","Smith Station":"Smiths Station","Tennile":"Tennille",
    "Big Prarie":"Big Prairie","Snelville":"Snellville","Snelleville":"Snellville",
    "Guttenburg":"Guttenberg","Gutenberg":"Guttenberg","Osala":"Ocala",
    "Des Plaine":"Des Plaines","Napoleanville":"Napoleonville","Bulington":"Burlington",
    "Burlongton":"Burlington","Mullica Hills":"Mullica Hill","Wrenthem":"Wrentham",
    "Seacaucus":"Secaucus","McSherrytown":"McSherrystown","Cladwell":"Caldwell",
    "Averne":"Arverne","Ponte Verde Beach":"Ponte Vedra Beach",
    "Cantoment":"Cantonment","Cannonsburg":"Canonsburg",
    "New Carrolton":"New Carrollton","Lawrenceberg":"Lawrenceburg",
    "New Ilberia":"New Iberia","Greatna":"Gretna","Waxhart":"Waxhaw",
    "Lithona":"Lithonia","Noorwood":"Norwood","Teanek":"Teaneck",
    "Forte Meade":"Fort Meade","Lawndals":"Lawndale","Menomonie Falls":"Menomonee Falls",
    "Loiusville":"Louisville","Medeira":"Madeira","Knoville":"Knoxville",
    "Knoxvile":"Knoxville","Neptue Township":"Neptune Township","Atalla":"Attalla",
    "Russlleville":"Russellville","Hopkinsivlle":"Hopkinsville","Pehlam":"Pelham",
    "Merrik":"Merrick","Massapegua":"Massapequa","Cateret":"Carteret",
    "Westhersfield":"Wethersfield","Halletsville":"Hallettsville",
    "Mariettta":"Marietta","East Pointe A La Hache":"Pointe a la Hache",
    "East Pointe a la Hache":"Pointe a la Hache","Ocford":"Oxford",
    "Piedmontm":"Piedmont","St. Augusttine":"St. Augustine",
    "Brooklynn Park":"Brooklyn Park","Yadkinsville":"Yadkinville",
    "North Arlingtong":"North Arlington","Seiverville":"Sevierville",
    "Onrario":"Ontario","Ontatio":"Ontario","San Deigo":"San Diego",
    "Elletsville":"Ellettsville","Highstown":"Hightstown","Millston":"Millstone",
    "Mateca":"Manteca","Rancho Sante Fe":"Rancho Santa Fe",
    "Westlakes Village":"Westlake Village","Aeia":"Aiea","McAlla":"McCalla",
    "Macadonia":"Macedonia","Clemonton":"Clementon",
    "Wycokoff":"Wyckoff","Wykoff":"Wyckoff","Brooklandale":"Brooklandville",
    "Sickerville":"Sicklerville","Gibsontown":"Gibsonton",
    "Famington Hills":"Farmington Hills","Melvern":"Malvern","Zainesville":"Zanesville",
    "Folcort":"Folcroft","Petosi":"Potosi","Metarlie":"Metairie","Merded":"Merced",
    "Island Lakes":"Island Lake","Wesiminster":"Westminster",
    "Fountian Inn":"Fountain Inn","Moncks Corber":"Moncks Corner",
    "Winnosboro":"Winnsboro","Bluffon":"Bluffton","Sedro-Wooley":"Sedro-Woolley",
    "Keenedale":"Kennedale","Frostrproof":"Frostproof","Winter Garder":"Winter Garden",
    "South Central L.A.":"Los Angeles","Donaldsville":"Donaldsonville",
    "Pataskla":"Pataskala","Grennsburg":"Greensburg","Rlato":"Rialto",
    "Wautaga":"Watauga","Boca Rotan":"Boca Raton","Monteballo":"Montebello",
    "Lenardtown":"Leonardtown","Broheadsville":"Brodheadsville","Coltsneck":"Colts Neck",
    "Lathrup Villiage":"Lathrup Village","Ducanville":"Duncanville",
    "Watinsville":"Watkinsville","New Port Richie":"New Port Richey",
    "New Port Rickey":"New Port Richey","Flroence":"Florence",
    "New Baunfels":"New Braunfels","Geismer":"Geismar","Bradenburg":"Brandenburg",
    "Highlands Rach":"Highlands Ranch","Shawnes Mission":"Shawnee Mission",
    "Le Puente":"La Puente","New Lexon":"New Lenox","Cilfton Park":"Clifton Park",
    "Bay Cities":"Bay City","Tupelp":"Tupelo","Hollsboro":"Hillsboro",
    "Alief (SWAT)":"Houston","Betonville":"Bentonville",
    "Washington Terrance":"Washington Terrace","Payallup":"Puyallup",
    "Chalottesville":"Charlottesville","Hyattville":"Hyattsville","Kaploei":"Kapolei",
    "Ovido":"Oviedo","Nokesvilla":"Nokesville","Melboune":"Melbourne",
    "San Bernardo":"San Bernardino","Plesant View":"Pleasant View",
    "Stone Mountian":"Stone Mountain","Lannett":"Lanett","Hochston":"Hoschton",
    "Charltote":"Charlotte","Swuannee":"Suwanee","Venura":"Ventura",
    "Gaithersburgh":"Gaithersburg","Harrisburgh":"Harrisburg","Sammamich":"Sammamish",
    "New Carlistle":"New Carlisle","Joilet":"Joliet","Steamwood":"Streamwood",
    "Glenn Ellyn":"Glen Ellyn","Macob":"Macomb","St. Petersberg":"St. Petersburg",
    "St. Petersburgh":"St. Petersburg","Milington":"Millington",
    "Noth Platte":"North Platte","Mission Viego":"Mission Viejo","Summitt":"Summit",
    "Homstead":"Homestead","Pearl Mississippi":"Pearl",
    "Bradford West Gwillimbury":"Bradford West Gwillimbury",
}

# --- Whole-string overrides: wrong state, ambiguous, foreign ------------------
# value: (city, state, country, status, note)
OVERRIDE = {
    "Guyana, South America": ("", "", "Guyana", "fixed", "country only"),
    "Dubai, UAE / Las Vegas, Nev.": ("Dubai", "", "United Arab Emirates", "review", "two hometowns; kept first"),
    "Lagos, Nigeria/Blanchester, Ohio": ("Lagos", "", "Nigeria", "review", "two hometowns; kept first"),
    "Warri, Nigeria/Browntown, Mich.": ("Warri", "", "Nigeria", "review", "two hometowns; kept first"),
    "Dallas, Texas by way of New Zealand": ("Dallas", "TX", "USA", "fixed", "dropped 'by way of'"),
    "Queensland, Australia / Ormiston College": ("", "Queensland", "Australia", "fixed", "region only"),
    "Ilofa, Kwara State of Nigeria": ("Offa", "Kwara", "Nigeria", "review", "guess: Ilofa -> Offa?"),
    "Pago Pago, American Samoa Tuala": ("Pago Pago", "AS", "USA", "fixed", ""),
    "Mapusaga, America Samoa": ("Mapusaga", "AS", "USA", "fixed", ""),
    "Bradford West Gwillimbury, Ontario, Canda": ("Bradford West Gwillimbury", "ON", "Canada", "fixed", ""),
    "Ajax, Canda": ("Ajax", "ON", "Canada", "fixed", ""),
    "Purcellville, Pa.": ("Purcellville", "VA", "USA", "review", "Purcellville is in VA, not PA"),
    "Sayreville, Pa.": ("Sayreville", "NJ", "USA", "review", "Sayreville is in NJ, not PA"),
    "Lindenhurst, N.J.": ("Lindenhurst", "NY", "USA", "review", "Lindenhurst is in NY (or IL), not NJ"),
    "Naperville, Ind.": ("Naperville", "IL", "USA", "review", "Naperville is in IL, not IN"),
    "Leonardtown, Pa.": ("Leonardtown", "MD", "USA", "review", "Leonardtown is in MD, not PA"),
    "Reynoldsburg, Md.": ("Reynoldsburg", "OH", "USA", "review", "Reynoldsburg is in OH, not MD"),
    "Mt. Belvieu, Lousiana": ("Mont Belvieu", "TX", "USA", "review", "Mont Belvieu is in TX"),
    "Rancho Cucamonga,TX": ("Rancho Cucamonga", "CA", "USA", "fixed", "state TX -> CA"),
    "Pearl Mississippi, Pa.": ("Pearl", "MS", "USA", "review", "read as Pearl, Mississippi"),
    "Port Gipson, TX": ("Port Gibson", "MS", "USA", "review", "guess: Port Gibson, MS"),
    "Swakopee": ("Shakopee", "MN", "USA", "review", "guess: Shakopee, MN"),
    "Durhman": ("Durham", "NC", "USA", "review", "no state given; assumed NC"),
    "Waxhah": ("Waxahachie", "TX", "USA", "review", "guess"),
    "Kinei, Haw.": ("Kihei", "HI", "USA", "review", "guess: Kihei"),
    "Kajukam, Hawaii": ("Kahuku", "HI", "USA", "review", "guess: Kahuku"),
    "Hua'ala, Haw.": ("Hauula", "HI", "USA", "review", "guess: Hauula"),
    "Plenticle, California": ("Placentia", "CA", "USA", "review", "guess: Placentia"),
    "Oxinghale, Pa.": ("Oxon Hill", "MD", "USA", "review", "guess: Oxon Hill, MD"),
    "South Bellemore, NY": ("Bellmore", "NY", "USA", "review", "no 'South Bellmore'; used Bellmore"),
    "Shelville, Ga.": ("Snellville", "GA", "USA", "review", "guess: Snellville"),
    "Greshman, SC": ("Gresham", "SC", "USA", "review", "guess"),
    "Tyrghe, Ga.": ("Tyrone", "GA", "USA", "review", "guess"),
    "Somas, WA": ("Sumas", "WA", "USA", "review", "guess: Sumas"),
    "Ranchgrobe, Calif.": ("Rancho Cordova", "CA", "USA", "review", "guess; could be Ranch Grove"),
    "Grentown, Pa.": ("Greentown", "PA", "USA", "review", "guess"),
    "Edord, La.": ("", "LA", "USA", "review", "city unrecognisable"),
    "Edmaton, Texas": ("", "TX", "USA", "review", "city unrecognisable (Edna? Edmonson?)"),
    "Blackhaven, Tenn.": ("", "TN", "USA", "review", "city unrecognisable"),
    "Teachy, S.C.": ("", "SC", "USA", "review", "city unrecognisable"),
    "Ozwitt": ("", "", "", "unfixable", "unrecognisable"),
    "Josh Shaw": ("", "", "", "unfixable", "a person's name, not a place"),
    "Number Retired in 2000": ("", "", "", "unfixable", "not a place"),
    "Hometown": ("", "", "", "unfixable", "column header scraped as data"),
    "": ("", "", "", "unfixable", "blank hometown"),
}

PREFIX = re.compile(r"^\s*Hometown/Last School:\s*", re.I)


def norm_state(tok):
    t = tok.strip().rstrip(".").strip()
    if not t:
        return "", ""
    if t.upper() in _USPS:
        return t.upper(), "USA"
    key = t.lower().rstrip(".")
    if key in STATE_ALIASES:
        return STATE_ALIASES[key], "USA"
    if key in COUNTRY_ALIASES and COUNTRY_ALIASES[key]:
        return "", COUNTRY_ALIASES[key]
    region = _region(t)             # the parser's tables: "Illi.", "Virg.", "MB", "B.C. Canada", "Curacao", ...
    if region and (region["country"] in ("USA", "Canada") or region["country"] in COUNTRIES):
        return region["state"], region["country"]
    return None, None


def _known_place(home: dict) -> bool:
    """The parser read a region the geocoder can at least put a coarse dot on (a country or province)."""
    return home["country"] == "Canada" or home["country"] in COUNTRIES


def suggest_correction(raw: str) -> tuple:
    """Best guess at what an unmatched hometown string meant: (city, state, country, status, note)."""
    s = html.unescape(raw).strip()
    if s in OVERRIDE:
        return OVERRIDE[s]
    if not_a_place(s):
        return ("", "", "", "unfixable", "not a hometown: bats/throws, a height or a role from another column")
    home = parse_hometown(s)
    if home["country"] not in ("", "USA") and _known_place(home):
        # Abroad, and the parser knows where: "Winnipeg, MB", "Brandon, Manitoba, CA" (Canada, not
        # California), "Bolton, Ontario Canada", "Willemstad, Curacao"
        return (home["city"], home["state"], home["country"], "fixed", f"read as {home['country']}")
    notes = []
    town, _ = split_labeled_hometown(s)   # "Hometown/Previous School(s): Omaha, Neb." -> "Omaha, Neb."
    if town != s:
        if not town:
            return ("", "", "", "unfixable", "roster label with no hometown after it")
        s = town
        notes.append("label text removed")
    if PREFIX.match(s):
        s = PREFIX.sub("", s)
        notes.append("stripped 'Hometown/Last School:' prefix")
    # drop school(s) after a slash, " - school", or "(college"
    for sep in ("/", " - ", "("):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            notes.append("dropped school text")
            break
    s = s.rstrip(" ,")
    if "," in s:
        city, state_tok = s.rsplit(",", 1)
    else:  # "Cape Coral FL." / "Carelton Mich." / "Waipahu O'ahu"
        parts = s.rsplit(" ", 1)
        city, state_tok = (parts[0], parts[1]) if len(parts) == 2 else (s, "")
    city = city.strip()
    state, country = norm_state(state_tok)
    if state is None:
        return (city, "", "", "review", f"unknown state/country '{state_tok.strip()}'")
    if city in CITY_FIX and CITY_FIX[city] != city:
        notes.append(f"spelling {city} -> {CITY_FIX[city]}")
        city = CITY_FIX[city]
    if state_tok.strip().rstrip(".") not in (state, ""):
        notes.append(f"state '{state_tok.strip()}' -> {state or country}")
    return (city, state, country, "fixed", "; ".join(notes))


def query_for(city, state, country):
    parts = [p for p in (city, state, country) if p]
    return ", ".join(parts)


# ---------------------------------------------------------------------------

_WORLD: WorldCities | None = None


def world() -> WorldCities:
    global _WORLD
    if _WORLD is None:
        _WORLD = WorldCities()
    return _WORLD


def _in_newfoundland(hit: tuple) -> bool:
    """WorldCities.lookup falls back to any Canadian town of the name; keep it only if it is in Newfoundland
    and Labrador (roughly east of 67.5 W and north of 46.5 N)."""
    return hit[0] > 46.5 and hit[1] > -67.5


def resolve(home: dict, gaz: Gazetteer, nom: Nominatim | None) -> tuple:
    city, state, country = home["city"], home["state"], home["country"]
    if not (city or state or country):
        return ("", "", "", "")
    if not country and not state and city and _STATE_BY_NAME.get(city.lower().strip(" .")) \
            and city.lower().strip(" .") not in ("washington", "georgia", "new york"):
        state, country, city = _STATE_BY_NAME[city.lower().strip(" .")], "USA", ""   # "Maryland" alone: the state
    if country == "USA" and state and not city and state in gaz.state_center and state not in TERRITORIES:
        return (*gaz.state_center[state], "state", "region")
    if country == "USA":
        hit = gaz.lookup_us(city, state)
        if hit:
            return hit
        if state in ("PR", "AS", "GU", "VI", "MP"):      # territories: GeoNames has their towns
            hit = world().lookup(city, {"PR": "Puerto Rico", "AS": "American Samoa", "GU": "Guam",
                                        "VI": "U.S. Virgin Islands", "MP": "Northern Mariana Islands"}[state])
            if hit:
                return hit
    elif not country and not state and city:
        key = re.sub(r"[\s,]+(mohawk territory|first nation|reservation|reserve|territory|nation)$", "", city.lower()).strip()
        if key in NATIONS_ABROAD:
            c, st, co = NATIONS_ABROAD[key]
            hit = world().lookup(c, co, st)
            if hit:
                return hit
        hit = gaz.lookup_no_state(city) or world().lookup_big(city)
        if not hit:      # "Pago Pago", "Hagatna": a town in a US territory
            for terr in ("American Samoa", "Puerto Rico", "Guam", "U.S. Virgin Islands", "Northern Mariana Islands"):
                hit = world().lookup(city, terr)
                if hit:
                    break
        if hit:
            return hit
    elif country == "NL" and city:
        # "NL" is Newfoundland and Labrador on hockey rosters ("St. John's, NL") and the Netherlands on others
        # ("Spijkenisse, NL"): a Newfoundland town of that name first, else a Dutch one.
        hit = world().lookup(city, "Canada", "NL")
        hit = hit if hit and _in_newfoundland(hit) else world().lookup(city, "Netherlands")
        if hit:
            return hit
    elif country and city:
        hit = world().lookup(city, country, state)       # Toronto ON, Santo Domingo, Sydney: the town's own dot
        if hit:
            return hit
    if nom and (city or country):
        parts = [city, state if country in ("USA", "Canada") else "", country or ""]
        q = ", ".join(p for p in parts if p)
        hit = nom.lookup(q)
        if hit:
            return (*hit, "nominatim", "city")
    if country == "USA" and state in TERRITORIES:
        return (*TERRITORIES[state], "territory", "region")
    if country == "Canada" and state in PROVINCES:
        return (*PROVINCES[state], "province", "region")
    if country in COUNTRIES:
        return (*COUNTRIES[country], "country_centroid", "country")
    return ("", "", "", "")


def campus_states() -> dict[str, str]:
    """school -> its campus's state, from config/shared/school_locations.csv (shared by every sport)."""
    import core
    path = core.CONFIG / "shared" / "school_locations.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["school"]: r["state"] for r in csv.DictReader(fh) if r.get("state") in US_STATES}


_FINENESS = {"city": 0, "city_guess": 1, "county": 2, "region": 3, "country": 4, "": 5}

CORR_FIELDS = ["hometown_raw", "city", "state", "country", "query", "status", "note", "players"]


def load_corrections(path: Path) -> dict[str, dict]:
    """hometown_raw -> row of hometown_corrections.csv (including your hand edits)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["hometown_raw"]: r for r in csv.DictReader(fh)}


def save_corrections(path: Path, table: dict[str, dict]) -> None:
    order = {"review": 0, "unfixable": 1, "fixed": 2}
    rows = sorted(table.values(), key=lambda r: (order.get(r["status"], 0), -int(r["players"] or 0)))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CORR_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def corrected_home(row: dict | None, statuses: set[str]) -> dict | None:
    if row and row.get("status") in statuses and (row.get("city") or row.get("state") or row.get("country")):
        return {"city": row.get("city", ""), "state": row.get("state", ""), "country": row.get("country", "")}
    return None


LOOKUP_FIELDS = ["hometown", "school", "city", "state", "country", "lat", "lon", "source", "precision", "players"]


def load_lookup(path: Path, refresh: bool) -> dict[tuple, dict]:
    """hometowns.csv -> {(hometown, school): row}. With --refresh only hand-set ("manual") rows are kept."""
    out: dict[tuple, dict] = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if refresh and r.get("source") != "manual":
                    continue
                out[(r.get("hometown", ""), r.get("school", ""))] = r
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=GEOCODE_HOMETOWNS_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rosters", type=Path, nargs="?",
                    help="a CSV of players to geocode, also written out as <name>_geocoded.csv "
                         "(default: every player in the season files in rosters/<sport>/, with no extra file)")
    add_sport_argument(ap)
    ap.add_argument("--online", action="store_true", help="look up leftovers with OpenStreetMap Nominatim")
    ap.add_argument("--contact", default="anonymous", help="email for the Nominatim User-Agent (their policy)")
    ap.add_argument("--corrections", type=Path, default=None,
                    help="fix table to read and update (default: config/<sport>/hometown_corrections.csv)")
    ap.add_argument("--use-review", action="store_true", help="also apply corrections marked 'review'")
    ap.add_argument("--refresh", action="store_true",
                    help="look every hometown up again instead of reusing hometowns.csv (keeps rows marked 'manual')")
    args = ap.parse_args(argv)
    sport = load_sport(args.sport)
    statuses = {"fixed", "review"} if args.use_review else {"fixed"}
    corr_path = args.corrections or sport.hometown_corrections_csv
    table = load_corrections(corr_path)
    lookup_path = sport.rosters_dir / "hometowns.csv"
    known = load_lookup(lookup_path, args.refresh)

    if args.rosters:
        with open(args.rosters, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    else:
        rows = players(sport.rosters_dir)
    players_per_raw: dict[str, int] = {}
    players_per_key: dict[tuple, int] = {}
    for r in rows:
        raw = r.get("hometown", "")
        players_per_raw[raw] = players_per_raw.get(raw, 0) + 1
        players_per_key[(raw, r["school"])] = players_per_key.get((raw, r["school"]), 0) + 1

    # Pass 0: reuse every hometown already in hometowns.csv. An unplaced one is tried again only
    # if its row in hometown_corrections.csv now says something different from what was tried.
    homes: dict[str, dict] = {}
    resolved: dict[str, tuple] = {}
    todo: list[str] = []
    for raw in players_per_raw:
        k = known.get((raw, ""))
        fix = corrected_home(table.get(raw), statuses)
        if k is not None and k.get("source") == "manual":
            # Moved by hand: kept as it is
            homes[raw] = {"city": k.get("city", ""), "state": k.get("state", ""), "country": k.get("country", "")}
            resolved[raw] = (k.get("lat", ""), k.get("lon", ""), k.get("source", ""), k.get("precision", ""))
            continue
        # Everything else is looked up again on every run (Oct 28). The lookups are quick, and before, a
        # hometown kept whatever it got the first time: towns the US town list or a parser fix could now
        # place stayed unplaced, and Toronto, Ontario stayed on the dot in the middle of Canada.
        todo.append(raw)
    guess_missing = any(resolved[raw][3] == "city_guess" and (raw, sch) not in known
                        for (raw, sch) in players_per_key if raw in resolved)
    print(f"{len(todo):,} hometowns to look up ({len(players_per_raw) - len(todo):,} moved by hand, kept)")

    gaz = Gazetteer() if (todo or guess_missing) else None
    nom = Nominatim(args.contact) if (args.online and todo) else None

    # Pass 1: new hometowns. Existing corrections first, otherwise the normal parser.
    kept_old = 0
    for raw in todo:
        homes[raw] = corrected_home(table.get(raw), statuses) or parse_hometown(raw)
        resolved[raw] = resolve(homes[raw], gaz, nom)
        if not resolved[raw][0] and homes[raw] != parse_hometown(raw):
            # A correction that places nothing (many were written by an older, simpler reading: "Maui" as a
            # town with no state) doesn't stop the parser's own reading from being tried
            alt = parse_hometown(raw)
            hit = resolve(alt, gaz, nom)
            if hit[0]:
                homes[raw], resolved[raw] = alt, hit
        old = known.get((raw, ""))
        if old is not None and old.get("lat") and old.get("source") == "nominatim" and \
                _FINENESS.get(old.get("precision", ""), 5) < _FINENESS.get(resolved[raw][3], 5):
            # An online answer (--online) finer than what the offline lists give: keep it
            homes[raw] = {"city": old.get("city", ""), "state": old.get("state", ""), "country": old.get("country", "")}
            resolved[raw] = (old["lat"], old["lon"], old["source"], old.get("precision", ""))
            continue
        if not resolved[raw][0] and old is not None and old.get("lat"):
            # Placed by an earlier run (an older version guessed close spellings: "Wauwautosa" -> Wauwatosa),
            # and nothing places it now: keep that dot rather than lose it
            homes[raw] = {"city": old.get("city", ""), "state": old.get("state", ""), "country": old.get("country", "")}
            resolved[raw] = (old["lat"], old["lon"], old.get("source", ""), old.get("precision", ""))
            kept_old += 1
    if kept_old:
        print(f"  {kept_old} hometowns nothing places now kept the dot an earlier run gave them")

    # Pass 2: suggest a fix for each new string that didn't place, and use it right away if confident.
    suggested = applied = 0
    for raw in todo:
        if resolved[raw][0] or raw in table or not raw.strip() or not_a_place(raw):   # nothing to fix
            continue
        city, state, country, status, note = suggest_correction(raw)
        if status != "unfixable" and not (city or state or country):
            status = "unfixable"
        table[raw] = {"hometown_raw": raw, "city": city, "state": state, "country": country,
                      "query": ", ".join(p for p in (city, state, country) if p),
                      "status": status, "note": note, "players": 0}
        suggested += 1
        fix = corrected_home(table[raw], statuses)
        if fix:
            hit = resolve(fix, gaz, nom)
            if hit[0]:
                homes[raw], resolved[raw] = fix, hit
                applied += 1
    if nom:
        nom.save()

    # Pass 3: a town with no state ("Pleasant Grove") is guessed per school. A BYU player from
    # "Pleasant Grove" is from Utah, not Alabama, so prefer the states that school recruits most.
    school_states: dict[str, dict[str, int]] = {}
    for (raw, sch), n in players_per_key.items():
        h = homes[raw]
        if h["country"] == "USA" and h["state"] and resolved[raw][0]:
            c = school_states.setdefault(sch, {})
            c[h["state"]] = c.get(h["state"], 0) + n
    top_states = {sch: [st for st, _ in sorted(c.items(), key=lambda kv: -kv[1])[:5]]
                  for sch, c in school_states.items()}
    # The campus's own state comes first (Oct 28): players who give only a town are mostly from near the
    # school, and a school whose listed players come mostly from elsewhere put Ohio towns in Pennsylvania.
    for sch, st in campus_states().items():
        top_states[sch] = [st] + [x for x in top_states.get(sch, []) if x != st]
    per_school: dict[tuple, tuple] = {}
    for (raw, sch) in players_per_key:
        h = homes[raw]
        if not (h["city"] and not h["state"] and not h["country"] and resolved[raw][3] == "city_guess"):
            continue
        k = known.get((raw, sch))
        if k is not None and raw not in todo and k.get("lat"):
            per_school[(raw, sch)] = (k["lat"], k["lon"], k.get("source", ""), k.get("precision", ""))
        else:
            gaz = gaz or Gazetteer()   # not loaded yet when every hometown was reused from hometowns.csv
            per_school[(raw, sch)] = gaz.lookup_no_state(h["city"], top_states.get(sch, ())) or resolved[raw]

    for raw, row in table.items():  # keep hand edits, refresh the counts
        if raw in players_per_raw:
            row["players"] = players_per_raw[raw]
    if table:
        save_corrections(corr_path, table)

    def with_guessed_state(h: dict, src: str) -> dict:
        h = dict(h)
        if src.startswith("census_guess_") and not h["state"]:
            h["state"], h["country"] = src.rsplit("_", 1)[1], "USA"  # so the map can label and filter it
        return h

    out_path = None
    if args.rosters:   # only for a CSV given by hand; the map build reads hometowns.csv
        out_path = args.rosters.with_name(args.rosters.stem + "_geocoded.csv")
        extra = ["home_city", "home_state", "home_country", "home_lat", "home_lon", "geo_source", "geo_precision"]
        fields = ([f for f in rows[0].keys() if f not in extra] if rows else []) + extra
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in rows:
                raw = r.get("hometown", "")
                lat, lon, src, prec = per_school.get((raw, r["school"]), resolved[raw])
                h = with_guessed_state(homes[raw], src)
                w.writerow({**r, "home_city": h["city"], "home_state": h["state"], "home_country": h["country"],
                            "home_lat": lat, "home_lon": lon, "geo_source": src, "geo_precision": prec})

    # hometowns.csv: one row per hometown string, plus one per school for towns given without a state.
    lookup_rows = []
    for raw, n in players_per_raw.items():
        lat, lon, src, prec = resolved[raw]
        lookup_rows.append({"hometown": raw, "school": "", **homes[raw], "lat": lat, "lon": lon,
                            "source": src, "precision": prec, "players": n})
    for (raw, sch), (lat, lon, src, prec) in per_school.items():
        lookup_rows.append({"hometown": raw, "school": sch, **with_guessed_state(homes[raw], src), "lat": lat,
                            "lon": lon, "source": src, "precision": prec, "players": players_per_key[(raw, sch)]})
    written = {(r["hometown"], r["school"]) for r in lookup_rows}
    lookup_rows += [k for key, k in known.items() if k.get("source") == "manual" and key not in written]
    lookup_rows.sort(key=lambda r: (-int(r["players"] or 0), r["hometown"], r["school"]))
    with open(lookup_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOOKUP_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(lookup_rows)

    # Players whose roster gives no hometown are counted on their own line: they aren't a town that
    # failed to place, so they stay out of the success rate and out of unmatched_hometowns.csv.
    counts: dict[str, int] = {}
    unmatched: dict[str, int] = {}
    no_hometown = 0
    for raw, n in players_per_raw.items():
        if not raw.strip() or not_a_place(raw):      # "R/R", "5-7": another column, not a town
            no_hometown += n
            continue
        prec = resolved[raw][3] or "unmatched"
        counts[prec] = counts.get(prec, 0) + n
        if not resolved[raw][0]:
            unmatched[raw] = n
    um_path = sport.rosters_dir / "unmatched_hometowns.csv"
    with open(um_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hometown_raw", "city", "state", "country", "status", "note", "players"])
        for raw, n in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            h, t = homes[raw], table.get(raw, {})
            w.writerow([raw, h["city"], h["state"], h["country"], t.get("status", ""), t.get("note", ""), n])

    total = len(rows) - no_hometown          # players with a hometown to place
    placed = total - counts.get("unmatched", 0)
    print(f"Geocoded {placed}/{total} players with a hometown ({placed / max(total, 1):.1%})"
          + (f" -> {out_path}" if out_path else ""))
    for prec in ("city", "city_guess", "county", "region", "country", "unmatched"):
        if counts.get(prec):
            print(f"  {prec:11s} {counts[prec]:7d}")
    if no_hometown:
        print(f"  {'no hometown':11s} {no_hometown:7d}   (roster gives none; kept, with no dot on the map)")
    print(f"Hometown lookup table ({len(lookup_rows):,} rows) -> {lookup_path}")
    print(f"{suggested} new correction suggestions ({applied} applied this run) -> {corr_path}")
    review = sum(1 for raw in unmatched if table.get(raw, {}).get("status") == "review")
    print(f"{len(unmatched)} hometowns still unmatched -> {um_path}"
          + (f"; {review} have a 'review' suggestion (check them, then re-run with --use-review)" if review else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
