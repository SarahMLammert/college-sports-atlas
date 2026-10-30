# college-sports-atlas

Where college players come from and where coaches move, sport by sport. Rosters and staff lists are scraped
from each school's athletics site, hometowns are placed on a map, and everything is published as a static
site in `docs/` (GitHub Pages).

| sport | folder | schools | players | seasons |
|---|---|---|---|---|
| Football | `football` | 831 (FBS, FCS, D2, D3, NAIA, JUCO) | 446K | 2016–2019, 2021–2026 (no 2020) |
| Baseball | `baseball` | 1,082 (D1, D2, D3, NAIA, JUCO) | 218K | 2016–2027 |
| Softball | `softball` | 1,118 (D1, D2, D3, NAIA, JUCO) | 115K | 2016–2027 |
| Lacrosse (Men's) | `lacrosse-mens` | 431 (D1, D2, D3, NAIA, JUCO) | 69K | 2016–2027 |
| Lacrosse (Women's) | `lacrosse-womens` | 583 (D1, D2, D3, NAIA, JUCO) | 58K | 2016–2027 |
| Hockey (Men's) | `hockey-mens` | 162 (NCAA D1, D2, D3) | 18K | 2016–2027 |
| Hockey (Women's) | `hockey-womens` | 126 (National Collegiate = D1 and D2 schools, D3) | 11K | 2016–2027 |
| Basketball (Men's) | `basketball-mens` | 1,292 (D1, D2, D3, NAIA, JUCO) | 113K | 2016–2027 |
| Basketball (Women's) | `basketball-womens` | 1,299 | 86K | 2016–2027 |
| Volleyball (Women's) | `volleyball-womens` | 1,274 | 90K | 2016–2026 (fall) |
| Soccer (Men's) | `soccer-mens` | 1,046 | 120K (re-run pending) | 2016–2026 (fall) |
| Soccer (Women's) | `soccer-womens` | 1,248 | 145K | 2016–2026 (fall) |

Football, volleyball and soccer are named by the fall they're played in. Spring and winter sports are named by the
spring the season ends in (2025-26 = 2026); from August the current season is next spring's. A sport appears on the
front page once it has been built.

## The site

`docs/index.html` is the sport picker (its numbers come from each sport's `summary.json`). Each sport's folder
has five pages:

- **Recruiting Map** (`players-dotmap.html`): a dot for every hometown, worldwide; filters for school,
  conference, division, seasons, transfers and positions; search for a school, player or town.
- **Recruiting Footprints** (`players-heatmap.html`): up to four schools compared, state by state.
- **Transfer Map** (`players-transfers.html`): school-to-school moves.
- **Coaching Moves** (`staff-moves.html`): coaches moving between schools (head coach jobs, coaching jobs or any staff job).
- **Staff Directory** (`staff-directory.html`): a school's staff by season, its head coaches over time, and any
  person's career.

Football and baseball come in two files: the dot map opens on the D1 schools (`map_data.json`) and loads the
other divisions (`map_data_more.json`) only when a view or a search needs them. Map and staff data are packed
(`build.py`, `staff.py`) and unpacked by `docs/common.js`.

The pages show seasons as school years (2023-24); links and the data files keep the season number.

Every view is saved in the address after `#` (e.g. `football/players-dotmap.html#school=Alabama&pos=QB`), so links can be shared.
The pages are football's: edit `docs/football/*.html`, then `python3 scripts/build.py sync` copies them to every
sport (`--check` only reports differences; a test fails if they differ).

**Publish:** GitHub → Settings → Pages → deploy from branch `main`, folder `/docs`. To look locally:
`cd docs && python3 -m http.server`, then http://localhost:8000.

## Running it

Setup once: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
(add `pip install playwright && playwright install chromium` for the browser retries).

```
caffeinate -i python3 scripts/pipeline.py all              # every sport, every step
python3 scripts/pipeline.py softball hockey-mens           # some sports
python3 scripts/pipeline.py baseball --steps geocode,build # some steps
python3 scripts/pipeline.py football --from geocode        # start at a step
python3 scripts/pipeline.py softball --dry-run             # print the commands only
python3 -m pytest tests -q                                 # the tests
```

Steps, in order: `scrape` (quick pass) → `retry` (slow pass with a browser) → `redo-current` (only with
`--redo-current`) → `geocode` → `fix-hometowns` → `frozen` → `build` → `locations` → `staff` → `check`.
Useful options: `--rescrape` (every school again, not just what's missing), `--only "A,B"`, `--division D1`,
`--seasons 2024-2026`, `--retry-given-up`, `--keep-going`. A sport can't be run twice at once (a lock in `rosters/<sport>/`).

The terminal shows one line per school and short summaries; long lists of schools go to
`rosters/<sport>/notes_*.txt`. Each sport's full output is saved in `rosters/<sport>/pipeline.log`.

The steps one by one:

| command | does |
|---|---|
| `scrape_rosters.py --sport X` | download and read rosters (`--problems` only rewrites `MISSING_ROSTERS.md`) |
| `geocode.py --sport X` | place hometowns (`rosters/<sport>/hometowns.csv`, `unmatched_hometowns.csv`) |
| `hometown_fixes.py suggest --sport X [--accept-likely]` | suggest fixes for unplaced hometowns |
| `hometown_fixes.py spellings --sport X` | fix misspelled towns from the geocoder's table |
| `build.py frozen / map / locations / check / sync` | class-year check, map data, campus file, roster check, page sync |
| `staff.py scrape / build --sport X` | coaches from the roster pages, then the staff data |
| `core.py compress-cache` | compress the page cache |

## Folders

```
config/shared/         school_colors.csv, school_locations.csv (every sport)
config/<sport>/        settings.json        roster paths, roster size, positions, divisions, seasons
                       schools.csv          every college: division, conference, site, seasons, notes
                       hometown_corrections.csv   hometown fixes (status fixed / review / unfixable)
                       wrong_seasons.csv, season_pages.csv   pages to skip or to use (optional)
rosters/<sport>/       working files, not committed: rosters_<season>.csv, scrape reports, MISSING_ROSTERS.md,
                       attempts.csv, hometowns.csv, staff_<season>.csv, notes and logs
docs/                  the site; docs/<sport>/ has the pages plus map_data.json, names.txt, summary.json,
                       school_locations.json, staff_data.json
scripts/               core.py (paths, downloads, season files, levels), sidearm.py (reading roster pages),
                       scrape_rosters.py, geocode.py, hometown_fixes.py, build.py, staff.py, pipeline.py
tests/                 test_atlas.py (python3 -m pytest tests -q)
.cache/                downloaded pages (gzip) and town lists, not committed; it makes reruns fast. Plan: delete
                       it once every sport is added and checked (the next run would then download everything again)
```

## How it works

- **Schools.** `config/<sport>/schools.csv` lists every college the sport knows. Rows with a season range record
  moves between divisions, programs that started, stopped or closed ("none"), and colleges kept only so a
  transfer's old school gets a level ("level only"). A note starting "left out" means the site is never contacted.
- **Scraping.** For each school-season it tries the usual Sidearm/WMT/Presto addresses, then a browser.
  A page is rejected if it's another sport's, shows another season, is a main page still showing last
  season, or has an abnormal number of players for the sport. Schools whose site never works are skipped:
  a school-season that fails 3 runs in a row is given up (`attempts.csv`; `--retry-given-up` tries again).
  Pages are cached, so reruns are fast; 404s are remembered for 60 days.
- **Fixing a school.** See `rosters/<sport>/MISSING_ROSTERS.md`. Set `domain` or `roster_url` in `schools.csv`;
  list a season whose page is really another year in `wrong_seasons.csv`, or give the right page in `season_pages.csv`.
- **Hometowns.** Read from the roster text (US states, Canadian provinces, countries, hockey's three-letter
  codes like SWE/CZE), then placed with Census, USGS and GeoNames town lists. Plain "NL" is a Newfoundland town
  if one has that name, otherwise Dutch. Fixes go in `hometown_corrections.csv`; `suggest --accept-likely`
  also takes clear misspellings and a wrong state only when the right one is a neighbour. Rows marked
  `manual` in `hometowns.csv` are never changed.
- **Transfers.** A player counts as a transfer if the roster names a college as his previous school, he was on
  another school's roster in this data first, or he arrives as a junior or older. Junior hockey teams ("(USHL)")
  are never colleges; for hockey only a known college counts. Old schools get a level (D1, D2, D3, NAIA,
  JUCO, club, unknown). Seasons whose class years never advance ("frozen") don't use the class-year rule.
- **Staff.** Coaches are read from the roster pages (or the coaches page). People are matched by name; a
  move is a person's last season at one school followed by their first at another within two seasons.
  Titles become roles (head, associate, assistant, coordinator, graduate, volunteer, support).

## Adding a sport

1. Make `config/<sport>/` (name: sport, then sex if both, e.g. `basketball-womens`) with `settings.json`
   (copy one and change the roster paths, roster size, positions and divisions) and `schools.csv`.
2. Add any new schools' colors and campuses to `config/shared/`.
3. Copy football's pages into `docs/<sport>/`, change their titles, and add the sport to `docs/index.html`.
4. Run `python3 scripts/pipeline.py <sport>`.

## Known issues

- Junior colleges with no known roster site are listed but not scraped; NJCAA's own stats pages could fill them.
- Coaches are matched by name only, so two people with the same name can be mixed up.
- `rosters/` was committed until Oct 28, so the git history is large (about 580 MB) until it's rewritten without it.
