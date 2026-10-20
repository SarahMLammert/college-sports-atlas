# D1 College Football Recruiting Map

Where college football players come from: the hometown of every FBS and FCS player on a roster
since 2016, scraped from each school's official athletics site and put on a world map.

- **264 schools**, about **137,000 player records** and about **10,000 hometowns**
- Seasons 2016–2019 and 2021–2026 (there's no 2020 data)
- One record per player per school, so a transfer appears once for each school he played for

The site lives in `docs/` and is plain static files, so GitHub Pages can host it for free. It has two
pages:

- **Recruiting Map** (`index.html`): a world map with a dot for every hometown.
- **Recruiting Footprints** (`compare.html`): up to four schools side by side on U.S. maps, each
  state shaded by its share of that school's roster.

## Using the map

The map fills the whole screen and opens zoomed to the U.S. Scroll or pinch to zoom out to the
rest of the world (countries are labeled in English as they come into view), and use ⟲ to come back.

The dot map starts empty: **pick a school** in the box in the middle (or under Filters) to fill it
in, or choose "show every school at once". The school you're showing appears as a chip under the
title; click its × (or "Clear map" in Filters) to empty the map again.

- **Dots** are hometowns, sized by the number of players and colored by the school that took the
  most players from that town. An outlined dot means the location is approximate (matched to a
  county or a same-name city).
- **Search** (top right) finds a player, hometown or high school and zooms the map to it. High
  schools are split by hometown state, because names like "Central" repeat across the country.
- **Filters** opens a dropdown under the button to narrow by school, division (FBS or FCS when the
  player joined), conference, season on roster (a player counts if he was on a roster in any season
  of the range), recruit type (high school or transfer) and position group. The button shows how
  many filters are on.
- **Players** (right side) opens when you click a dot or pick a search result, and lists those
  players: name, position, school, seasons, high school.
- **School stats** (the button in the bottom-left box) opens the numbers for what the map shows:
  totals, where the picked school ranks among D1 schools (players, high-school recruits, transfers,
  and players from a clicked state) with the schools ranked just above and below it, then top
  states, top hometowns, high-school pipelines and biggest rosters. Clicking a state opens it with
  that state's breakdown. With a conference filter on, ranks are within the conference.
- Dots grow when the map is sparse (one school's few hundred hometowns) so they're easier to hover
  and click, and stay small when every school is showing.
- **Compare** opens the Recruiting Footprints page. The first time it starts empty (no schools, no
  filters); after that it comes back with the schools and filters you last used there, remembered
  in your browser. A shared Footprints link always opens exactly what it describes.
- **Copy link** (the chain icon) copies a link that reopens exactly this view.

## Using Recruiting Footprints

Type a school into each of the four boxes. Each map shades every state by the share of that
school's roster from there, in the school's own color, on one scale for all four (the key at the
top shows 1%, 5%, 15%, 30% and 50%+), so a big program and a small one compare fairly. Under each
map, one line ranks the school's states with their shares; scroll it sideways for the rest.

Hover or tap a state on a map, or in its ranking line, to see that school's rank, raw player count
and share for the state; click to keep it shown, click again to clear. Each map highlights on its
own. On big screens the maps size themselves so all four fit in the window. Filters here cover
division, season on roster, recruit type and position (each box picks its own school, so there's
no school or conference filter). **Dot map** goes back with the same filters, showing the first
school you picked. Players from abroad or Puerto Rico aren't on these maps; each box says how many.

### Link format

Everything you see is saved in the part of the address after `#`, so links can also be typed by
hand. Leave out anything you don't need.

| key | example | meaning |
|---|---|---|
| `school` | `school=Alabama` | one school, or `school=all` for every school on the dot map |
| `conf` | `conf=SEC` | one conference (2026 alignment) |
| `div` | `div=FCS` | division when the player joined: `FBS` or `FCS` |
| `from`, `to` | `from=2019&to=2024` | players on a roster in any season of this range |
| `arrived` | `arrived=transfer` | recruit type: `hs` (high school) or `transfer` |
| `pos` | `pos=QB,WR` | position groups |
| `state` | `state=TX` | selected state |
| `town` | `town=Bastrop, TX` | selected hometown |
| `player` | `player=Name~School` | selected player (name and school, so links survive a data rebuild) |
| `hs` | `hs=IMG Academy~FL` | selected high school, optionally limited to one hometown state |
| `map` | `map=-96.50,38.50,1.00` | longitude, latitude and zoom at the center of the screen |

Recruiting Footprints links use the same `div`, `from`, `to`, `arrived` and `pos` keys, plus
`compare` for the schools: `compare.html#compare=Alabama|Georgia|Texas|LSU&from=2019`. Older
links to the map page that include `compare=` open this page.

## Publish the map on GitHub Pages
1. Push this repo to GitHub.
2. On GitHub: **Settings → Pages → Build and deployment → Deploy from a branch**,
   pick branch `main` and folder `/docs`, then **Save**.
3. After a minute the map is live at `https://<your-username>.github.io/<repo-name>/`.

To look at it on your own computer first: `cd docs && python3 -m http.server`, then open
http://localhost:8000. Opening `index.html` by double-clicking won't work, because browsers
block loading the data file from disk.

The pages load d3 and topojson from cdnjs, and the country and state outlines from jsDelivr
(`world-atlas` and `us-atlas`). If the outlines can't load, the dots still draw in the right
places.

## Folder layout
```
docs/                    the website (this is what GitHub Pages serves)
  index.html             Recruiting Map: the dot map, search, players panel and school stats
  compare.html           Recruiting Footprints: four schools on state-shaded U.S. maps
  common.js              shared by both: data loading, school colors, the Filters dropdown and its link keys
  common.css             shared by both: colors, type, title bar, buttons, the Filters dropdown
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
