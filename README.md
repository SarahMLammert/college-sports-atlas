# D1 College Football Recruiting Map

Where college football players come from: the hometown of every FBS and FCS player on a roster
since 2016, scraped from each school's official athletics site and put on a world map.

- **264 schools**, about **137,000 player records** and about **11,000 hometowns**
- Seasons 2016–2019 and 2021–2026 (there's no 2020 data)
- About 40,900 transfers (30% of player records), 19,350 of them between two D1 schools in this data (so the school he left is known)
- One record per player per school, so a transfer appears once for each school he played for

The site lives in `docs/` and is plain static files, so GitHub Pages can host it for free. It has three
pages, linked from each other's title bars:

- **Recruiting Map** (`index.html`): a world map with a dot for every hometown.
- **Recruiting Footprints** (`compare.html`): up to four schools side by side on U.S. maps, each
  state shaded by its share of that school's roster.
- **Transfer Map** (`transfers.html`): lines from campus to campus for every player who moved
  between two D1 schools.

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
  players from a clicked state, share from its home state, and typical distance from campus) with the schools ranked just above and below it, then top
  states, top hometowns, high-school pipelines and biggest rosters. Clicking a state opens it with
  that state's breakdown. With a conference filter on, ranks are within the conference.
- Dots grow when the map is sparse (one school's few hundred hometowns) so they're easier to hover
  and click, and stay small when every school is showing.
- **Compare** opens the Recruiting Footprints page. The first time it starts empty (no schools, no
  filters); after that it comes back with the schools and filters you last used there, remembered
  in your browser. A shared Footprints link always opens exactly what it describes.
- **Transfers** opens the Transfer Map with its last-used view.
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

### Head to head

Under the maps (or jump there with "Head-to-head stats ↓"), five panels compare the picked schools,
all following the page's filters:

- **Scorecard**: players; share of high-school recruits and transfers; how many states each school
  recruits from; its top state and that state's share; and the fewest states that make up half the
  roster (1–2 is very local, 6+ is national).
- **Battleground states**: states where at least two of the schools have 5+ players, with bars on
  one shared scale, e.g. Georgia: Georgia 327, Alabama 58, LSU 34.
- **Shared high schools**: high schools that sent players to two or more of the schools, grouped
  by school name and the players' home state.
- **Footprint over time**: one line per school by season, showing either how many states that
  season's roster came from or the share from the school's overall top state. Hover for every
  school's value that season; a dashed rule marks 2021, the first transfer-portal cycle. Lines
  whose school colors look alike are drawn dashed, and every line is labeled by name.
- **Position pipelines**: each school's top home state for every position group, with how many of
  that group came from there.

The scorecard also shows each school's campus, its share of players from its home state, and its
typical distance from campus (the median straight-line distance from hometown to campus), and the
trend chart can show home-state share by season. Each map marks the campus with a dot.

## Using the Transfer Map

Each line runs from the school a player left to the D1 school he joined, thicker for more players.
Every school shows as a dot on its campus, sized by how many players moved in and out.

- With no school picked, the map draws the 450 busiest routes, and the lists beside it rank the
  biggest destinations, the biggest sources and the most common moves (all of them counted, not
  just the drawn ones). Hover a move in the list to find it on the map.
- **Pick a school** (click its campus, a name in a list, or the School box in Filters) to see who
  came in (orange) and who left (blue), with the totals, the net and lists of where they came from
  and went. Hover a line or campus for its numbers; "All schools" or Esc goes back.
- **Filters** cover school, division and season on the new school's roster, conference (moves to
  or from a school in it) and position group.
- Only transfers whose previous D1 school is known can be drawn: about 19,350 of them. The rest (junior
  colleges, Division II, or no school named) are counted as "other transfers" but have no line.
- The lines need `docs/data/school_locations.json`; without it the page says so and the lists
  still work. Big one-season moves are often a coach taking players with him (Iowa State → Penn
  State 2026, Toledo → UConn 2026, Gardner-Webb → East Tennessee State 2024).

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

Transfer Map links use the `school`, `conf`, `div`, `from`, `to` and `pos` keys:
`transfers.html#school=Penn State&from=2024`. Like the other pages, it reopens with the last view
you used when opened without a link.

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
  transfers.html         Transfer Map: school-to-school moves on a U.S. map, with source and destination lists
  common.js              shared by all three: data loading, school colors, the Filters dropdown and its link keys
  common.css             shared by all three: colors, type, title bar, buttons, the Filters dropdown
  data/map_data.json     every player, packed small; made by build_map_data.py
  data/school_locations.json   each school's campus; made by build_school_locations.py
  .nojekyll              tells GitHub Pages to serve the files as they are
scrape_rosters.py        step 1: scrape rosters (fetching, parsing and cleaning all live here)
geocode_hometowns.py     step 2: hometown -> lat/lon, plus suggested fixes for hometowns it can't place
fix_hometown_spellings.py  adds checked fixes for misspelled hometowns to data/hometown_corrections.csv
check_frozen_classes.py  step 3: find seasons whose class years can't be trusted (see How transfers are recognized)
build_map_data.py        step 4: pack everything into docs/data/map_data.json
build_school_locations.py  packs config/school_locations.csv for the site
config/
  schools.csv            school, division, conference, domain, roster_url
  division_history.csv   schools that changed division, and when
  school_colors.csv      each school's primary and secondary color, for the map dots
  school_locations.csv   each school's campus city, state, latitude and longitude
tests/                   parser tests: python -m pytest tests -q
                         (tests/test_previous_school.py also runs on its own: python tests/test_previous_school.py)
requirements.txt
```
`config/school_locations.csv` holds each school's campus city, state and coordinates; after editing
it, run `python build_school_locations.py` to rebuild `docs/data/school_locations.json` (the pages
use it for the campus star, home-state share and distance from campus, and still work without it).

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
python check_frozen_classes.py                                         # writes data/frozen_class_seasons.csv
python build_map_data.py                                               # writes docs/data/map_data.json
```
Run both from the repo's root folder: `build_map_data.py` reads the list `check_frozen_classes.py`
writes, and without it trusts every season's class years (it prints a warning).
Then commit `docs/data/map_data.json` and push; the live map updates on its own.

After changing the scraper's cleaning rules, `python scrape_rosters.py --recombine` re-cleans every saved
season and rebuilds `rosters_all_seasons.csv` and `players_unique.csv` without downloading anything
(a minute instead of hours); then run `geocode_hometowns.py`, `check_frozen_classes.py` and
`build_map_data.py` as usual.

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
| `data/frozen_class_seasons.csv` | school-seasons whose class years can't be trusted; the build skips its class-year rule for them |

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

## How transfers are recognized
Roster sites label a player's old school in different ways: "Previous School", "Last School" (a
high school for freshmen, a college for transfers), "College", or one field like "Lamar HS / Texas
Tech". The scraper sorts every school field it finds: a college goes to `previous_school`, a high
school to `high_school`. It knows a college by words like University, College, CC or JC, or by its
name in `config/schools.csv` or a list of well-known junior colleges. A lone "previous school" that
isn't recognizably a college is treated as the high school (Ohio State's site, for one, files every
high school there), and "Menard" next to "Menard HS" is one school, not a transfer.
`build_map_data.py` uses the same rules (it imports them from `scrape_rosters.py`, so keep the two
together), and also counts players it finds on an earlier
D1 roster, and newcomers who arrive as juniors or older (see Known issues).

`build_map_data.py` prints any "thin rosters" (a school-season with fewer than 40 players). The ones
in the data now are seasons the schools' sites simply don't have: Ohio State 2016, Jackson State
2016–17, Samford 2016–17, Alabama A&M 2019, LIU 2016–18 and 2021, Yale 2016, UAB 2016 (no team) and
Saint Francis (PA) 2026. Re-scraping won't fill them. The build skips its "arrived as a junior or
older" transfer rule for the season after each one, so a missing roster can't make returning players
look like transfers.

Some schools' archive pages also show the wrong class year: each player appears with a later class
(often his final one) instead of that season's, so freshmen look like juniors. Ohio State 2017–2022
is the clearest case; the rule had counted 40% of its players as transfers. `check_frozen_classes.py`
finds these seasons by following returning players from one season to the next: normally about a
quarter don't move up a class (mostly redshirt years), but on a frozen archive nearly all of them
stay put. It counts only players who were freshmen, sophomores or juniors the season before, so
seniors repeating a year (the COVID free year) don't count, unless too few of those remain to judge.
When 60% or more don't advance, both seasons of the pair go into `data/frozen_class_seasons.csv`,
and `build_map_data.py` skips its class-year rule for them. Players there still count as transfers
when the roster lists a previous college or they were on an earlier D1 roster.

## Fixing a school that fails
Check `data/reports/scrape_report_*.csv`, then fix its `domain` or paste its exact roster page
into `roster_url` in `config/schools.csv` (it may contain `{season}`), and run again with
`--retry-failed`.

## Known issues
- A few school-seasons have no roster on the school's site (listed under "Rebuild the data"), so
  those seasons undercount that school's players.
- Transfers: many roster pages never list a previous school (Notre Dame, SMU, Arkansas State, Sam
  Houston and others), so `build_map_data.py` also counts a player as a transfer when he was on
  another D1 roster earlier with the same name and hometown, or when he's new to a roster whose
  previous season is also in the data and he's already a junior, senior or grad (so a season that
  failed to scrape doesn't make returning players look like transfers). The class-year rule is
  skipped for seasons whose class years can't be trusted (see How transfers are recognized), so
  transfers from outside D1 with no listed previous school are missed in those seasons. It also
  misses a transfer from outside D1 whose class year looks like a freshman's or sophomore's, and two different players with the same name and hometown on two
  rosters in different years would be read as one transfer (rare; same-season pairs are skipped).
- Some roster pages put the jersey number in the name field ("89 Mason Thomas", "13d Drew
  Melaragno"); `build_map_data.py` removes it from the names on the site and when matching transfers.
- High-school names that differ only in "HS", "High School" or "H.S." (and punctuation) are merged
  by `build_map_data.py` and shown under the most common spelling. Names that differ in other ways
  ("Cedar Park" and "Cedar Park HS") stay separate, since they could be different schools.
- Misspelled hometowns ("Douglasvillle, GA") show up as an extra dot next to the real town.
  `fix_hometown_spellings.py` holds a checked list of them; after running it, geocode and build again.
- The same high-school name can belong to schools in different towns; the map can't tell them
  apart beyond the player's hometown state.
- Links that include `map=` made before the switch to the world map open at the wrong zoom;
  everything else in them still works.
