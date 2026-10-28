from __future__ import annotations

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
    town list by suggest_hometown_fixes.py, since 'Port Washington' or 'Saint Louis' end in a state's name."""
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
