#!/usr/bin/env python3
"""Add latitude/longitude to scraped rosters so hometowns can be mapped.

Offline sources (downloaded once into .cache/):
  1. US Census Gazetteer places + county subdivisions (cities, towns, CDPs, townships)
  2. USGS GNIS Populated Places (unincorporated communities and neighborhoods:
     Cypress TX, Ellenwood GA, Kingwood TX, Pacoima CA, ...)
  3. US Census Gazetteer counties ("Stafford, Va.", "Broward County, Fla.")  -> county centroid
  4. Built-in centroids for US territories and common foreign countries      -> coarse fallback
Optional online source (--online): OpenStreetMap Nominatim for whatever is left
(foreign cities, typos), 1 request/second, cached in .cache/nominatim.json.

    python scripts/geocode_hometowns.py                       # data/football/players_unique.csv
    python scripts/geocode_hometowns.py --online --contact you@example.com
    python scripts/geocode_hometowns.py --sport mens-basketball

Hometowns that don't match get a suggested fix (typos, wrong state, school text mixed in).
Suggestions marked "fixed" are applied in the same run; "review" ones are applied only with
--use-review. All suggestions are saved to hometown_corrections.csv, where your hand edits
are kept from run to run and win over the built-in rules.

Writes next to the input:
  <input>_geocoded.csv        the rows + home_lat, home_lon, geo_source, geo_precision
  hometowns.csv               one row per hometown: what the roster said, the town it was read as,
                              lat/lon, where the answer came from, and how many players. Open it
                              to look anything up. Re-runs reuse it, so only new hometowns are
                              looked up. To move a dot by hand, change its lat/lon and set its
                              source to "manual"; manual rows are always kept.
  hometown_corrections.csv    the fix table (status: fixed / review / unfixable)
  unmatched_hometowns.csv     what still couldn't be placed, most common first

After changing the parser or this script, run with --refresh to look every hometown up again.
"""
from __future__ import annotations

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.hometowns import US_STATES, parse_hometown  # noqa: E402
from core.paths import add_sport_argument, load_sport  # noqa: E402

# In the repo folder (this script lives in scripts/), not the folder it's run from, so every run
# finds the same downloads and the same saved online answers.
CACHE = Path(__file__).resolve().parent.parent / ".cache"
GAZ_YEAR = 2024
GAZ_BASE = f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{GAZ_YEAR}_Gazetteer/"
GAZ_PLACES = f"{GAZ_YEAR}_Gaz_place_national.zip"
GAZ_COUSUBS = f"{GAZ_YEAR}_Gaz_cousubs_national.zip"
GAZ_COUNTIES = f"{GAZ_YEAR}_Gaz_counties_national.zip"
GNIS_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/Topical/PopulatedPlaces_National_Text.zip"

_SUFFIXES = re.compile(
    r"\s+(city and borough|consolidated government|metro(politan)? government|unified government|"
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
}

# Coarse fallbacks (geo_precision = "region"/"country").
TERRITORIES = {"AS": (-14.2756, -170.7020), "GU": (13.4443, 144.7937), "VI": (18.3358, -64.8963),
               "MP": (15.1850, 145.7467)}
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
            if priority == 0:
                aland = float(row[col["aland"]]) if "aland" in col and row[col["aland"]] else 0.0
                for n in names:  # incorporated places rank above CDPs of the same name
                    self.by_name.setdefault(norm_city(n), []).append((0 if is_cdp else 1, aland, state, lat, lon))

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

    # -----------------------------------------------------------------------
    def lookup_us(self, city: str, state: str) -> tuple | None:
        """Return (lat, lon, source, precision) for a US city/state, or None."""
        if not city:
            return None
        c = city.lower().strip()
        candidates = [ALIASES.get((c, state)), city]
        stripped = re.sub(r"\s+(township|twp\.?|village|borough)$", "", city, flags=re.I)
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
            county = norm_city(_COUNTY_SUFFIX.sub("", cand))
            if (county, state) in self.counties:
                return (*self.counties[(county, state)], "census_county", "county")
        return None

    def lookup_no_state(self, city: str, prefer: list[str] | tuple = ()) -> tuple | None:
        """'Houston' with no state -> a place with that name: in the first of `prefer` (the states
        the player's school recruits most) that has one, otherwise the largest one in the country."""
        if city.lower().strip() in ("honolulu", "urban honolulu"):
            city = "urban honolulu"
        options = self.by_name.get(norm_city(city))
        if not options:
            return None
        for st in prefer:
            here = [o for o in options if o[2] == st]
            if here:
                _, _, st, lat, lon = max(here)
                return (lat, lon, f"census_guess_{st}", "city_guess")
        _, _, st, lat, lon = max(options)
        return (lat, lon, f"census_guess_{st}", "city_guess")


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
    return None, None


def suggest_correction(raw: str) -> tuple:
    """Best guess at what an unmatched hometown string meant: (city, state, country, status, note)."""
    s = html.unescape(raw).strip()
    if s in OVERRIDE:
        return OVERRIDE[s]
    notes = []
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

def resolve(home: dict, gaz: Gazetteer, nom: Nominatim | None) -> tuple:
    city, state, country = home["city"], home["state"], home["country"]
    if not (city or state or country):
        return ("", "", "", "")
    if country == "USA":
        hit = gaz.lookup_us(city, state)
        if hit:
            return hit
    elif not country and not state and city:
        hit = gaz.lookup_no_state(city)
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
    if country in COUNTRIES:
        return (*COUNTRIES[country], "country_centroid", "country")
    return ("", "", "", "")


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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rosters", type=Path, nargs="?",
                    help="CSV from scrape_rosters.py (default: data/<sport>/players_unique.csv)")
    add_sport_argument(ap)
    ap.add_argument("--online", action="store_true", help="look up leftovers with OpenStreetMap Nominatim")
    ap.add_argument("--contact", default="anonymous", help="email for the Nominatim User-Agent (their policy)")
    ap.add_argument("--corrections", type=Path, default=None,
                    help="fix table to read and update (default: hometown_corrections.csv next to the input)")
    ap.add_argument("--use-review", action="store_true", help="also apply corrections marked 'review'")
    ap.add_argument("--refresh", action="store_true",
                    help="look every hometown up again instead of reusing hometowns.csv (keeps rows marked 'manual')")
    args = ap.parse_args(argv)
    args.rosters = args.rosters or load_sport(args.sport).data_dir / "players_unique.csv"
    statuses = {"fixed", "review"} if args.use_review else {"fixed"}
    corr_path = args.corrections or args.rosters.with_name("hometown_corrections.csv")
    table = load_corrections(corr_path)
    lookup_path = args.rosters.with_name("hometowns.csv")
    known = load_lookup(lookup_path, args.refresh)

    with open(args.rosters, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
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
        if k is not None:
            tried = {"city": k.get("city", ""), "state": k.get("state", ""), "country": k.get("country", "")}
            if k.get("lat") or not fix or fix == tried:
                homes[raw] = tried
                resolved[raw] = (k.get("lat", ""), k.get("lon", ""), k.get("source", ""), k.get("precision", ""))
                continue
        todo.append(raw)
    guess_missing = any(resolved[raw][3] == "city_guess" and (raw, sch) not in known
                        for (raw, sch) in players_per_key if raw in resolved)
    print(f"{len(players_per_raw) - len(todo):,} hometowns reused from {lookup_path}, {len(todo):,} to look up")

    gaz = Gazetteer() if (todo or guess_missing) else None
    nom = Nominatim(args.contact) if (args.online and todo) else None

    # Pass 1: new hometowns. Existing corrections first, otherwise the normal parser.
    for raw in todo:
        homes[raw] = corrected_home(table.get(raw), statuses) or parse_hometown(raw)
        resolved[raw] = resolve(homes[raw], gaz, nom)

    # Pass 2: suggest a fix for each new string that didn't place, and use it right away if confident.
    suggested = applied = 0
    for raw in todo:
        if resolved[raw][0] or raw in table:
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
    per_school: dict[tuple, tuple] = {}
    for (raw, sch) in players_per_key:
        h = homes[raw]
        if not (h["city"] and not h["state"] and not h["country"] and resolved[raw][3] == "city_guess"):
            continue
        k = known.get((raw, sch))
        if k is not None and raw not in todo and k.get("lat"):
            per_school[(raw, sch)] = (k["lat"], k["lon"], k.get("source", ""), k.get("precision", ""))
        else:
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

    counts: dict[str, int] = {}
    unmatched: dict[str, int] = {}
    for raw, n in players_per_raw.items():
        prec = resolved[raw][3] or "unmatched"
        counts[prec] = counts.get(prec, 0) + n
        if not resolved[raw][0]:
            unmatched[raw] = n
    um_path = args.rosters.with_name("unmatched_hometowns.csv")
    with open(um_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hometown_raw", "city", "state", "country", "status", "note", "players"])
        for raw, n in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            h, t = homes[raw], table.get(raw, {})
            w.writerow([raw, h["city"], h["state"], h["country"], t.get("status", ""), t.get("note", ""), n])

    total = len(rows)
    placed = total - counts.get("unmatched", 0)
    print(f"Geocoded {placed}/{total} players ({placed / max(total, 1):.1%}) -> {out_path}")
    for prec in ("city", "city_guess", "county", "region", "country", "unmatched"):
        if counts.get(prec):
            print(f"  {prec:11s} {counts[prec]:7d}")
    print(f"Hometown lookup table ({len(lookup_rows):,} rows) -> {lookup_path}")
    print(f"{suggested} new correction suggestions ({applied} applied this run) -> {corr_path}")
    review = sum(1 for raw in unmatched if table.get(raw, {}).get("status") == "review")
    print(f"{len(unmatched)} hometowns still unmatched -> {um_path}"
          + (f"; {review} have a 'review' suggestion (check them, then re-run with --use-review)" if review else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
