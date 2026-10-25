# college-sports-atlas

Where college players come from, sport by sport, scraped from each school's official athletics site
and put on a map. Football is live: the hometown of every FBS and FCS player on a roster since 2016.

- **264 schools**, about **137,000 player records** and about **11,000 hometowns**
- Seasons 2016–2019 and 2021–2026 (there's no 2020 data)
- About 40,700 transfers (30% of player records), 19,350 of them between two D1 schools in this data (so the school he left is known);
  the other 21,300 are sorted by the level of the school they came from (junior college, Division II, Division III, NAIA,
  a D1 school he wasn't matched to, or unknown)
- One record per player per school, so a transfer appears once for each school he played for

The site lives in `docs/` and is plain static files, so GitHub Pages can host it for free. It opens
on a sport picker (`index.html`), and each sport has its own folder. Football's three pages are in
`docs/football/`, linked from each other's title bars:

- **Recruiting Map** (`football/players-dotmap.html`): a world map with a dot for every hometown.
- **Recruiting Footprints** (`football/players-heatmap.html`): up to four schools side by side on
  U.S. maps, each state shaded by its share of that school's roster.
- **Transfer Map** (`football/players-transfers.html`): lines from campus to campus for every player
  who moved between two D1 schools.

Page names start with `players-` or `staff-` and say what kind of map they are, so every sport's
folder can use the same names.

## In progress: every division of football

D2, D3, NAIA and junior-college (NJCAA and California's CCCAA) football are being added to the same
map, with a division filter of FBS, FCS, D2, D3, NAIA and JUCO. The full plan and its progress log
are in the plan file, `football-all-divisions-plan.txt`. Where things stand:

- **Done:** `config/football_schools.csv` has an athletics site for 865 colleges across all six levels
  (the 264 D1 schools, 411 D2 and D3 schools and most NAIA and junior-college programs). Another 77
  have no site, mostly closed or dropped programs, and are skipped.
  Colors and campuses for the new schools are in `school_colors.csv` and `school_locations.csv`
  (most junior colleges have no colors and draw gray). The scripts handle every division (see
  How the scraper works and The schools file), and all tests pass.
- **Next:** finish the sample scrape (`--retry-failed`, then `--render` for sites like Tyler JC),
  add last seasons for closed programs and rows for new NAIA programs (Bismarck State, Calumet
  College of St. Joseph, Midway, Stillman, Wilberforce, Manchester), run the full scrape, then
  update the pages: titles become "College Football Recruiting Map", "College Football Recruiting
  Footprints" and "College Football Transfer Map", and the division filter gets all six levels.
- Until that build runs, the map and the numbers above are still D1 only.

## The sport picker

`index.html` shows every sport on a ring around a center circle. Hovering or tapping a sport shows
its numbers in the middle; the jersey button next to it opens its players pages and the whistle
button its coaches and staff pages. Sports and pages that aren't built yet show as "coming soon".
On phones the ring becomes a list. The `SPORTS` list at the top of its script says which pages
exist: set a sport's `players` or `staff` to a page and its button starts working.

Every page's title bar has a round button (a ring of dots) that goes back to the picker.

The picker's footer has an **Information about the data** button that opens `sources.html`, a plain-language
page for visitors. It opens with the line "Rosters scraped from each school's official athletics site" and covers where the rosters come from (each school's own athletics site), which sports, schools
and seasons are covered, how hometowns are placed on the map, how transfers are counted, the known gaps,
and where the map outlines come from. It's written by hand, so update it when a sport goes live or the
numbers change (its "What's covered" list and the football numbers at the top).

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
- Only transfers whose previous D1 school is known can be drawn: about 19,350 of them. The rest are
  counted as "other transfers" with no line, and the panel beside the map splits them by the level of
  the school the roster names: junior college (about 7,800), Division II (2,000), Division III (540),
  NAIA (400), "D1 school, not matched" (6,000) and unknown (4,500). The split follows the filters and
  the picked school. See How transfer levels are decided.
- The lines need `docs/football/school_locations.json`; without it the page says so and the lists
  still work. Big one-season moves are often a coach taking players with him (Iowa State → Penn
  State 2026, Toledo → UConn 2026, Gardner-Webb → East Tennessee State 2024).

### Link format

Everything you see is saved in the part of the address after `#`, so links can also be typed by
hand. Leave out anything you don't need. Dot map links look like
`football/players-dotmap.html#school=Alabama&pos=QB`.

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
`compare` for the schools: `football/players-heatmap.html#compare=Alabama|Georgia|Texas|LSU&from=2019`.

Transfer Map links use the `school`, `conf`, `div`, `from`, `to` and `pos` keys:
`football/players-transfers.html#school=Penn State&from=2024`. Like the other pages, it reopens
with the last view you used when opened without a link.

## Publish the map on GitHub Pages
1. Push this repo to GitHub.
2. On GitHub: **Settings → Pages → Build and deployment → Deploy from a branch**,
   pick branch `main` and folder `/docs`, then **Save**.
3. After a minute the site is live at `https://<your-username>.github.io/<repo-name>/`.

To look at it on your own computer first: `cd docs && python3 -m http.server`, then open
http://localhost:8000. Opening the pages by double-clicking won't work, because browsers
block loading the data file from disk.

The pages load d3 and topojson from cdnjs, and the country and state outlines from jsDelivr
(`world-atlas` and `us-atlas`). If the outlines can't load, the dots still draw in the right
places.

## Folder layout
```
docs/                    the website (this is what GitHub Pages serves)
  index.html             the sport picker: every sport on a ring, with players and staff buttons
  sources.html           Information about the data: the visitor-facing page linked from the picker's footer
  common.js              shared by every sport's pages: data loading, school colors, the Filters dropdown and its link keys
  common.css             shared by every sport's pages: colors, type, title bar, buttons, the Filters dropdown
  .nojekyll              tells GitHub Pages to serve the files as they are
  football/
    players-dotmap.html      Recruiting Map: the dot map, search, players panel and school stats
    players-heatmap.html     Recruiting Footprints: four schools on state-shaded U.S. maps
    players-transfers.html   Transfer Map: school-to-school moves on a U.S. map, with source and destination lists
    map_data.json            every player, packed small; made by build_map_data.py
    school_locations.json    each school's campus; made by build_school_locations.py
scripts/                 the data pipeline; every script takes --sport (default: football)
  scrape_rosters.py        step 1: scrape rosters
  geocode_hometowns.py     step 2: hometown -> lat/lon, plus suggested fixes for hometowns it can't place
  check_frozen_classes.py  step 3: find seasons whose class years can't be trusted (see How transfers are recognized)
  build_map_data.py        step 4: pack everything into docs/<sport>/map_data.json
  build_school_locations.py  packs config/school_locations.csv for a sport's pages
  fix_hometown_spellings.py  adds checked fixes for misspelled hometowns to config/<sport>_hometown_corrections.csv
  check_geocoder.py        checks the geocoder has its fixes and looks up a few towns that once failed
  paths.py                 shared: where a sport's files are, and its settings from config/<sport>.json
  fetch.py                 shared: downloading pages: retries, pacing per site, the page cache
  sidearm.py               shared: reading Sidearm/WMT and PrestoSports pages: roster URLs, season check, the five parsers,
                           cleaning names, telling a college from a high school
  hometowns.py             shared: cleaning hometowns, class years, heights and weights
  seasons.py               shared: reading the season files and making one row per player per school from them
  levels.py                shared: the level of a transfer's previous school (D1, D2, D3, NAIA, JUCO, unknown)
rosters/<sport>/         the cleaned rosters and the scripts' other working files, not committed (see The rosters folder)
config/
  school_colors.csv      each school's primary and secondary color, for the map dots (every sport)
  school_locations.csv   each school's campus city, state, latitude and longitude (every sport)
  football.json          football's settings (see Adding a sport)
  football_schools.csv   every college: school, division, conference, domain, roster_url, first_season,
                         last_season, aliases, note (see The schools file)
  football_hometown_corrections.csv   hometown fixes: the geocoder's suggestions and your edits
tests/                   parser tests: python -m pytest tests -q (conftest.py lets them import from scripts/)
  sidearm_classic.html, sidearm_nextgen_table.html   saved roster pages the tests read
requirements.txt
```
The pages in a sport's folder load `../common.js` and `../common.css`, and `common.js` loads
`map_data.json` next to the page, so each sport reads its own data.

`config/school_locations.csv` holds each school's campus city, state and coordinates; after editing
it, run `python scripts/build_school_locations.py` to rebuild `docs/football/school_locations.json`
(only that sport's schools; the pages use it for the campus star, home-state share and distance from
campus, and still work without it).

Each script finds `config/`, `rosters/` and `docs/` from its own location (`scripts/paths.py`), so it
doesn't matter which folder you run it from. Code more than one script needs lives in the shared modules
next to them (`paths.py`, `fetch.py`, `sidearm.py`, `hometowns.py`, `levels.py`); `scrape_rosters.py`
still answers older imports like `from scrape_rosters import parse_hometown`.

## Adding a sport

1. Add two files to `config/`, named for the sport the way the athletics sites name it
   (`mens-basketball`, `baseball`):
   - `<sport>.json`: copy `football.json` and change `label`, `roster_paths` (the roster page's path
     on the sites, e.g. `/sports/mens-basketball/roster`), `presto_paths` (the same for PrestoSports
     sites, with `{season}` and `{next_yy}`, e.g. `/sports/mbkb/{season}-{next_yy}/roster`), `min_players` (fewer players than this on a
     page means a bad scrape), `junior_colleges`, and the position settings (`position_groups`,
     the roster abbreviations in each, words a spelled-out position starts with, and
     `position_fallback` for anything else).
   - `<sport>_schools.csv`, as for football (see The schools file): the D1 schools to scrape, their
     seasons in another division, and the sport's non-D1 colleges so its other transfers get a level.
   The geocoder makes `<sport>_hometown_corrections.csv` on its first run.
2. Add any new schools' colors and campuses to `config/school_colors.csv` and `school_locations.csv`.
3. Run the steps under Rebuild the data with `--sport <sport>`.
4. Copy football's three pages from `docs/football/` to `docs/<sport>/` (not its `.json` files), change the page titles, and set the
   sport's `players` page in the `SPORTS` list in `docs/index.html`.
5. Add the sport to "What's covered" in `docs/sources.html`, with its schools and seasons.

Each sport's pages remember their own last view in the browser (the key starts with the sport).

## Rebuild the data
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026                 # about 1-2 hours for D1 alone
python scripts/scrape_rosters.py --seasons 2016-2019,2021-2026 --retry-failed  # second pass on failures
#   add --report to either line to also save the scrape reports and MISSING_ROSTERS.md (see Fixing a school that fails)
python scripts/geocode_hometowns.py                                    # reads the season files, writes rosters/football/hometowns.csv
#   check the "review" rows in config/football_hometown_corrections.csv, change any you agree with to "fixed",
#   then run the geocode line again (or add --use-review to accept them all)
python scripts/check_frozen_classes.py                                 # writes rosters/football/frozen_class_seasons.csv
python scripts/build_map_data.py                                       # writes docs/football/map_data.json
```
Every step after the scraper reads the season files (`rosters_<season>.csv`) directly and makes the
one-row-per-player list from them in memory (`scripts/seasons.py`), so there's no combined file to keep up
to date. The map build places each player's hometown from `hometowns.csv`, so run the geocoder before it
whenever new seasons or schools come in.
Run `check_frozen_classes.py` before `build_map_data.py`: the build reads the list it writes, and
without it trusts every season's class years (it prints a warning).
Then commit `docs/football/map_data.json` and push; the live map updates on its own.

After changing the scraper's cleaning rules, `python scripts/scrape_rosters.py --recombine` re-cleans every saved
season file in place without downloading anything (a minute instead of hours); then run `geocode_hometowns.py`, `check_frozen_classes.py` and
`build_map_data.py` as usual.

To get every season in one file for a spreadsheet, add `--combined` to a scrape or to `--recombine`: it also
writes `rosters_all_seasons.csv` and `players_unique.csv`. Nothing else needs them.

To scrape one level at a time, add `--division` with `FBS`, `FCS`, `D2`, `D3`, `NAIA`, `JUCO` or `all`
(the scraper also lists the colleges it skips because they have no athletics site).

Quick test on a few schools: `python scripts/scrape_rosters.py --only "Alabama,Clemson,North Dakota State"`
(add `--out /tmp/roster_test` to keep a test's files out of `rosters/`).
For another sport, add `--sport <sport>` to every command.
For sites that only show the roster after JavaScript runs, add `--render` (needs
`pip install playwright && playwright install chromium`). For rosters that list the players but not their
hometowns (Morehouse), add `--bios`: it reads each player's own page for his hometown, high school and
previous school (one request per player, so slow; it stops after 5 pages if those have nothing either).
The usual second pass is `--retry-failed --render --bios`.

Pressing Ctrl-C saves the schools that finished; the ones still running keep their earlier results,
and `--retry-failed` picks them up next time.

## The rosters folder (not committed)
`rosters/` and `.cache/` are in `.gitignore`: they're large and can be rebuilt. Each sport has one
folder, with no folders inside it; football's is `rosters/football/`.

Every roster file holds only the cleaned version: names without jersey numbers or captain marks
("89 Mason Thomas", "13d Drew Melaragno", "Mason Thomas (C)" are all "Mason Thomas" / "Drew Melaragno"),
coaches and staff dropped, hometowns read into city, state and country, and high school and previous
school sorted out. Each run of the scraper cleans the season files themselves with the current rules,
so nothing scraped under older rules is left behind. The downloaded pages in `.cache/html/` are the raw
copy: if a cleaning rule changes, `--recombine` (or a re-scrape, which reads the cache instead of
downloading) applies it everywhere.

| file | contents |
|---|---|
| `rosters_<season>.csv` | one row per player that season; every later step reads these |
| `rosters_all_seasons.csv` | only with `--combined`: every season stacked |
| `players_unique.csv` | only with `--combined`: one row per player per school, with first and last season |
| `scrape_report_<season>.csv` | only with `--report`: per school: ok / partial / failed, players found, URL used, errors (the first 3 and last 5) |
| `MISSING_ROSTERS.md` | only with `--report`: the schools whose roster failed or is partial, by division, each with its seasons and the reason in words, plus the colleges skipped for having no site; rewritten after every `--report` run (see Fixing a school that fails) |
| `hometowns.csv` | the geocoder's table of every hometown it has placed, with its corrected city, state and country; re-runs reuse it, and the map build reads each player's dot from it |
| `unmatched_hometowns.csv` | hometowns that still couldn't be placed |
| `frozen_class_seasons.csv` | school-seasons whose class years can't be trusted; the build skips its class-year rule for them |
| `transfer_levels.csv` | every previous-school name of a transfer with no line, the level it got and how many players; made by `build_map_data.py` for checking |

If the season files are missing but a `rosters_all_seasons.csv` is there (from `--combined`), the scraper splits it back
into season files before it does anything else, so a partial run (`--only`) can't wipe the other schools.

Your hometown fixes live in `config/football_hometown_corrections.csv`, so they're committed with the
rest of the config and kept safe.

## How the scraper works
Almost every FBS/FCS site is built on **Sidearm** or **WMT**, and both ship the roster as a
Nuxt JSON payload inside the page. Each page is tried with five parsers (Nuxt data, classic
Sidearm markup, Sidearm cards, HTML tables, other embedded JSON) and the best result is kept.
Requests to one site are spaced 1.5 seconds apart, and raw pages are cached in `.cache/html/`.

For past seasons it tries each site's archive URL styles (`/roster/2019`, `/roster/season/2019/`,
`/roster/2019-20`, ...) or a `roster_url` template from `config/football_schools.csv`. Every archive page
is checked for its year so a site quietly showing this year's roster isn't saved as 2019.

Many D2, D3, NAIA and junior-college sites use **PrestoSports** instead, whose roster pages look like
`/sports/fball/2023-24/roster` (the `presto_paths` setting in `config/football.json`). These are tried
after the Sidearm/WMT URLs, with the list view (`?view=list`) first, since some sites (Morningside) only
have the roster table there, and on `www.` as well as the bare domain, since some sites (Hutchinson,
Iowa Western, Kilgore, Riverside) only answer on `www.`. The table parser drops phone-only cells
(class `d-md-none`, as on Avila's site) that would shift the columns, and reads combined columns like
"High School/HS City" in either order.

## How transfers are recognized
Roster sites label a player's old school in different ways: "Previous School", "Last School" (a
high school for freshmen, a college for transfers), "College", or one field like "Lamar HS / Texas
Tech". The scraper sorts every school field it finds: a college goes to `previous_school`, a high
school to `high_school`. It knows a college by words like University, College, CC or JC, or by the
name of a D1 school in `config/football_schools.csv` or a junior college listed in `config/football.json`. A lone "previous school" that
isn't recognizably a college is treated as the high school (Ohio State's site, for one, files every
high school there), and "Menard" next to "Menard HS" is one school, not a transfer.
`build_map_data.py` uses the same rules (it imports them from `sidearm.py`, so both steps agree), and also counts players it finds on an earlier
D1 roster, and newcomers who arrive as juniors or older (see Known issues).

`build_map_data.py` prints any "thin rosters" (a school-season with fewer than 40 players). The ones
in the D1 data now are seasons the schools' sites simply don't have: Ohio State 2016, Samford
2016–17 and Yale 2016. Re-scraping won't fill them. The build skips its "arrived as a junior or
older" transfer rule for the season after each one, so a missing roster can't make returning players
look like transfers.

Some schools' archive pages also show the wrong class year: each player appears with a later class
(often his final one) instead of that season's, so freshmen look like juniors. Ohio State 2017–2022
is the clearest case; the rule had counted 40% of its players as transfers. `check_frozen_classes.py`
finds these seasons by following returning players from one season to the next: normally about a
quarter don't move up a class (mostly redshirt years), but on a frozen archive nearly all of them
stay put. It counts only players who were freshmen, sophomores or juniors the season before, so
seniors repeating a year (the COVID free year) don't count, unless too few of those remain to judge.
When 60% or more don't advance, both seasons of the pair go into `rosters/football/frozen_class_seasons.csv`,
and `build_map_data.py` skips its class-year rule for them. Players there still count as transfers
when the roster lists a previous college or they were on an earlier D1 roster.

## The schools file
`config/football_schools.csv` holds every college the project knows, one row per school (or per school
and season range):

| column | meaning |
|---|---|
| `school` | the name used everywhere (a D1 school's name must match `school_colors.csv` and `school_locations.csv`) |
| `division` | `FBS`, `FCS`, `D2`, `D3`, `NAIA`, `JUCO`, `HS` (a high school whose name looks like a college) or `none` (no team) |
| `conference` | its conference in 2026, for current programs |
| `domain`, `roster_url` | the athletics site, for every college the scraper downloads |
| `first_season`, `last_season` | the seasons the row covers; blank means open-ended |
| `aliases` | other spellings rosters use, separated by `\|` |
| `note` | anything worth knowing (when a school moved, closed or merged, or a season its site doesn't have); shown in `MISSING_ROSTERS.md`, and a note starting with "left out" makes the scraper skip the school |

The scraper downloads every FBS, FCS, D2, D3, NAIA and JUCO college with a `domain` or `roster_url`
(865 of them; `load_schools()` in `scripts/paths.py`, while `d1_schools()` returns just the 264 D1
schools). A program that moved has a row for each level with its seasons (Thomas More: D3 through 2018,
NAIA 2019–2022, D2 from 2023; "Tarleton State, D2, last_season 2019"), and the scraper records each
season under the division its row gives. For scraping it picks one row per college: the row with no
season range, else its open-ended range, else its latest range, borrowing the domain from the college's
other rows. A season outside every range of a college that only has ranged rows counts as `none` and is
skipped (Mount Mercy before 2026, a program that closed); a `none` row skips seasons a team sat out.
Colleges without a site are still used to sort transfers by level. Rows with division `HS` are only
used for that.

## How transfer levels are decided
`build_map_data.py` gives every transfer without a line the level of the school his roster names
(`scripts/levels.py`), in the season before he joined, so "Tarleton State" is Division II for a
player who left before 2020 and D1 after. It checks, in order:

1. A name in `config/football_schools.csv` (or one of its aliases), compared loosely: "Valdosta St.",
   "Valdosta State University" and "valdosta state" are one name; "UW-Whitewater" is "Wisconsin-Whitewater";
   "(Kan.)" or "(MO)" after a name is read as a state. Rows can have a season range, so a school that moved
   (Thomas More: D3, then NAIA, then D2) or closed (Notre Dame College, D2 until 2023) has the right level.
2. Two-year college wording: CC, JC, Community College, Junior College, City College.
3. The name without "College" or "CC" ("Hope College" is Hope, "Iowa Western" is Iowa Western CC).
4. A field with several schools ("Wawasee | Ball State | Bethel (Tenn.)") uses the last one that matches.

A name that fits schools at two levels ("Bethel", "Concordia", "Butler", "Saint Francis") stays
unknown rather than guessed, and so does a high school whose name looks like a college; those are rows
with division `HS` ("St. John's College", "Gonzaga College"). Unknown also covers transfers whose roster
names no school (counted because they arrived as juniors or older). To fix a name, add it to the
`aliases` of the right row (separated by `|`), or add a row; then run `build_map_data.py` and look at
`rosters/football/transfer_levels.csv`.

"D1 school, not matched" means the roster names a D1 school but the player wasn't found on that
school's roster in this data. About 4,800 of these name a school whose roster for the seasons before
is in the data, so most are real D1-to-D1 moves that the name-and-hometown match missed (a different
spelling of his name or hometown); some are high schools with a D1 school's name (Princeton HS, Notre
Dame HS). They aren't drawn as lines yet.

## Fixing a school that fails
Every run ends with a short "Failed or partial" list, one line per school with the reason in a few words.
The report files are only written when you add `--report`: then `rosters/football/scrape_report_*.csv` has
the full errors, with web addresses, `rosters/football/MISSING_ROSTERS.md` has the same schools by division
with the reasons written out, and `--problems` prints the list again from the saved reports without scraping.
Without `--report` only the roster files are written. `--retry-failed` doesn't need the reports: it tells
which school-seasons are done from the saved rosters (enough players, most with a hometown).

- Wrong or dead site: fix its `domain`, or paste its exact roster page into `roster_url` in
  `config/football_schools.csv` (it may contain `{season}`), and run again with `--retry-failed`.
- A season before the program started or after it ended: set `first_season` or `last_season`, and it
  counts as "no program" instead of a failure.
- A season the school's own site doesn't have (old archives are often missing): add a `note` saying so.
  `MISSING_ROSTERS.md` shows it as that school's note, so the gap is explained.
- A site that refuses automated visitors: give it a `note` starting with "left out". The school stays in
  the list and the counts, but the scraper never contacts it and records it as failed, with the note as
  the reason (Indianapolis).

## Known issues
- A few school-seasons have no roster on the school's site (listed under How transfers are recognized), so
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
- Valparaiso's roster puts each player's major ("Business", "Sport Management") in the previous-school
  field. `build_map_data.py` doesn't count a major as a previous school (`is_major()` in
  `scripts/levels.py`), so those players aren't transfers unless another rule says so.
- Some roster pages put the jersey number or a captain mark in the name field ("89 Mason Thomas", "13d Drew
  Melaragno", "Mason Thomas (C)"); the scraper removes them (`clean_name()` in `scripts/sidearm.py`) before
  anything is saved.
- High-school names that differ only in "HS", "High School" or "H.S." (and punctuation) are merged
  by `build_map_data.py` and shown under the most common spelling. Names that differ in other ways
  ("Cedar Park" and "Cedar Park HS") stay separate, since they could be different schools.
- Misspelled hometowns ("Douglasvillle, GA") show up as an extra dot next to the real town.
  `fix_hometown_spellings.py` holds a checked list of them; after running it, geocode and build again.
- The same high-school name can belong to schools in different towns; the map can't tell them
  apart beyond the player's hometown state.
- `check_frozen_classes.py` needs 30 returning players per school-season to judge one, which fits
  football rosters; small-roster sports (basketball) will need that lowered.
- About 6,000 transfers name a D1 school but weren't matched to its roster, so they have no line on the
  Transfer Map (see How transfer levels are decided). Drawing them needs a guard against high schools
  with a D1 school's name.
- Lower divisions: see `rosters/football/MISSING_ROSTERS.md` (from a `--report` run) for every school-season that failed and why.
  Some PrestoSports sites answer simple scripts with a bot check (HTTP 202) and only work with `--render`;
  a site whose bot check turns the browser away too is left out, never worked around. The NJCAA's app
  (Tyler JC) only shows its roster after JavaScript runs, and lists hometowns for few players. De Anza
  leaves every hometown blank. About 21 colleges have no known athletics
  site (Keiser, Concordia (NE), several Minnesota and California junior colleges); some post rosters
  only as PDFs, and conference sites or njcaa.org's stats pages
  (`njcaa.org/sports/fball/<season>/teams/<team>/roster.html`) may be the way to get them.
- Recognizing a college in a "previous school" field still uses D1 names only, since lower-division
  names like "Central", "Union" or "Franklin" are also high schools.
- The "arrived as a junior or older" transfer rule hasn't been checked on junior-college rosters,
  which only have freshmen and sophomores.
- `map_data.json` is 6.8 MB with D1 only and could pass 15 MB with every division; if it loads
  slowly, it may need one file per division.
- `scrape_staff.py` (coaches and staff pages) is planned but not written; it should reuse the shared modules in `scripts/`.
