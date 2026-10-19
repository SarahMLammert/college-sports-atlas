# Gridiron Pipelines

Where college football players come from: the hometown of every FBS and FCS player on a roster
since 2016 (there's no 2020 data), scraped from each school's official athletics site and mapped.

The map lives in `docs/` and is a single static page, so GitHub Pages can host it for free.

## Publish the map on GitHub Pages
1. Push this repo to GitHub.
2. On GitHub: **Settings → Pages → Build and deployment → Deploy from a branch**,
   pick branch `main` and folder `/docs`, then **Save**.
3. After a minute the map is live at `https://<your-username>.github.io/<repo-name>/`.

To look at it on your own computer first: `cd docs && python3 -m http.server`, then open
http://localhost:8000. Opening `index.html` by double-clicking won't work, because browsers
block loading the data file from disk.

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
| `data/hometowns.csv` | one row per hometown: the town it was read as, lat/lon, source, players. Re-runs reuse it; to move a dot, edit its lat/lon and set source to `manual`. `--refresh` looks everything up again |
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
