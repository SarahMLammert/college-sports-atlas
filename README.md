# D1 College Football Recruiting Map

Where college football players come from: the hometown of every FBS and FCS player on a roster
since 2016, scraped from each school's official athletics site and put on a world map.

- **264 schools**, about **137,000 player records** and about **10,000 hometowns**
- Seasons 2016–2019 and 2021–2026 (there's no 2020 data)
- One record per player per school, so a transfer appears once for each school he played for

The map lives in `docs/` and is a single static page, so GitHub Pages can host it for free.

## Using the map

The map fills the whole screen and opens zoomed to the U.S. Scroll or pinch to zoom out to the
rest of the world, and use ⟲ to come back.

- **Dots** are hometowns, sized by the number of players and colored by the school that took the
  most players from that town. An outlined dot means the location is approximate (matched to a
  county or a same-name city).
- **Search** (top right) finds a player, hometown or high school and zooms the map to it. High
  schools are split by hometown state, because names like "Central" repeat across the country.
- **Filters** opens a panel to narrow by school, conference, division, first season, high school
  or transfer, and position group, or to switch to a heat map. The button shows how many filters
  are on.
- **Details** shows totals and top lists (states, hometowns, schools, players from outside the
  50 states) for whatever the filters leave. Click a dot to list its players, or a state to see
  which schools recruit it.
- **Copy link** (the chain icon) copies a link that reopens exactly this view.

### Link format

Everything you see is saved in the part of the address after `#`, so links can also be typed by
hand. Leave out anything you don't need.

| key | example | meaning |
|---|---|---|
| `school` | `school=Alabama` | one school |
| `conf` | `conf=SEC` | one conference (2026 alignment) |
| `div` | `div=FCS` | division when the player joined: `FBS` or `FCS` |
| `from`, `to` | `from=2019&to=2024` | range of first seasons on a roster |
| `arrived` | `arrived=transfer` | `hs` (from high school) or `transfer` |
| `pos` | `pos=QB,WR` | position groups |
| `view` | `view=heat` | heat map instead of dots |
| `state` | `state=TX` | selected state |
| `town` | `town=Bastrop, TX` | selected hometown |
| `player` | `player=Name~School` | selected player (name and school, so links survive a data rebuild) |
| `hs` | `hs=IMG Academy~FL` | selected high school, optionally limited to one hometown state |
| `map` | `map=-96.50,38.50,1.00` | longitude, latitude and zoom at the center of the screen |

## Publish the map on GitHub Pages
1. Push this repo to GitHub.
2. On GitHub: **Settings → Pages → Build and deployment → Deploy from a branch**,
   pick branch `main` and folder `/docs`, then **Save**.
3. After a minute the map is live at `https://<your-username>.github.io/<repo-name>/`.

To look at it on your own computer first: `cd docs && python3 -m http.server`, then open
http://localhost:8000. Opening `index.html` by double-clicking won't work, because browsers
block loading the data file from disk.

The page loads d3 and topojson from cdnjs, and the country and state outlines from jsDelivr
(`world-atlas` and `us-atlas`). If the outlines can't load, the dots still draw in the right
places.

## Folder layout
```
docs/                    the website (this is what GitHub Pages serves)
  index.html             the map page: layout, styles and code are all in this one file
  data/map_data.json     every player, packed small; made by build_map_data.py
  .nojekyll              tells GitHub Pages to serve the files as they are
scrape_rosters.py        step 1: scrape rosters (fetching, parsing and cleaning all live here)
geocode_hometowns.py     step 2: hometown -> lat/lon, plus suggested fixes for hometowns it can't place
build_map_data.py        step 3: pack everything into docs/data/map_data.json
config/
  schools.csv            school, division, conference, domain, roster_url
  division_history.csv   schools that changed division, and when
  school_colors.csv      each school's primary and secondary color, for the map dots
tests/                   parser tests: python -m pytest tests -q
requirements.txt
```
`scrape_rosters.py` and `geocode_hometowns.py` must stay in the same folder (the geocoder
borrows the scraper's hometown parser).

## Rebuild the data
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scrape_rosters.py --seasons 2016-2019,2021-2026                 # about 1-2 hours
python scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed  # second pass on failures
python geocode_hometowns.py data/players_unique.csv
#   check the "review" rows in data/hometown_corrections.csv, change any you agree with to "fixed",
#   then run the geocode line again (or add --use-review to accept them all)
python build_map_data.py                                               # writes docs/data/map_data.json
```
Then commit `docs/data/map_data.json` and push; the live map updates on its own.

Quick test on a few schools: `python scrape_rosters.py --only "Alabama,Clemson,North Dakota State"`.
For sites that only show the roster after JavaScript runs, add `--render` (needs
`pip install playwright && playwright install chromium`).

## Working files (not committed)
`data/` and `.cache/` are in `.gitignore`: they're large and can be rebuilt.

| file | contents |
|---|---|
| `data/seasons/rosters_<season>.csv` | one row per player that season |
| `data/reports/scrape_report_<season>.csv` | per school: ok / partial / failed, players found, URL used, errors |
| `data/rosters_all_seasons.csv` | every season stacked |
| `data/players_unique.csv` | one row per player per school, with first and last season |
| `data/players_unique_geocoded.csv` | the above plus latitude and longitude |
| `data/hometown_corrections.csv` | suggested hometown fixes; your edits here are kept between runs |
| `data/unmatched_hometowns.csv` | hometowns that still couldn't be placed |

If you'd rather keep the hometown corrections you've made by hand under version control, remove
`data/hometown_corrections.csv` from the ignore list (see `.gitignore`).

## How the scraper works
Almost every FBS/FCS site is built on **Sidearm** or **WMT**, and both ship the roster as a
Nuxt JSON payload inside the page. Each page is tried with five parsers (Nuxt data, classic
Sidearm markup, Sidearm cards, HTML tables, other embedded JSON) and the best result is kept.
Requests to one site are spaced 1.5 seconds apart, and raw pages are cached in `.cache/html/`.

For past seasons it tries each site's archive URL styles (`/roster/2019`, `/roster/season/2019/`,
`/roster/2019-20`, ...) or a `roster_url` template from `config/schools.csv`. Every archive page
is checked for its year so a site quietly showing this year's roster isn't saved as 2019.

## Fixing a school that fails
Check `data/reports/scrape_report_*.csv`, then fix its `domain` or paste its exact roster page
into `roster_url` in `config/schools.csv` (it may contain `{season}`), and run again with
`--retry-failed`.

## Known issues
- Some player names start with a jersey number (for example "89 Mason Thomas"), which comes
  from roster pages that put the number in the name field.
- The same high-school name can belong to schools in different towns; the map can't tell them
  apart beyond the player's hometown state.
- Links that include `map=` made before the switch to the world map open at the wrong zoom;
  everything else in them still works.
