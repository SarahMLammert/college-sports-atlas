# Football rosters that are missing or incomplete

Written by `scripts/scrape_rosters.py` on 2026-10-22 from the scrape reports in `/tmp/roster_check` (a test run with --out) (seasons 2018, 2024, 2025, 2026). It is rewritten after every run, so don't edit it here: to explain a school, add a `note` to its row in the schools file, and that note becomes its reason below.

- **Failed**: no roster was saved for that season.
- **Partial**: the roster was saved, but most players have no hometown, so they get no dot on the map.
- Seasons before a program started or after it ended aren't listed: they're not failures.

| division | ok | partial | failed |
|---|---|---|---|
| FBS | 264 | 0 | 0 |
| FCS | 253 | 2 | 0 |
| D2 | 316 | 2 | 6 |
| D3 | 481 | 0 | 4 |
| NAIA | 151 | 2 | 13 |
| JUCO | 104 | 22 | 77 |

## FCS

### Partial

- **East Tennessee State** (2018: 103 players, 1 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Valparaiso** (2018: 108 players, 18 with a hometown): neither the roster page nor the players' own pages list most hometowns.

## D2

### Failed

- **Florida Tech** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: football ended after 2019; site no longer has football pages.
- **Indianapolis** (2018, 2024): Left out: uindyathletics.com refuses automated access (robots.txt, certificate errors), Oct 2026.
- **Johnson C. Smith** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no rosters before 2019 (checked Oct 2026).
- **Lane** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has rosters from 2021 only (checked Oct 2026).
- **Morehouse** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster; old seasons redirect to current (checked Oct 2026).

### Partial

- **Catawba** (2018: 88 players, 21 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Morehouse** (2024: 98 players, 39 with a hometown): the roster page has no hometowns; the players' own pages gave 39 of 98, the rest don't list one. Note: site has no 2018 roster; old seasons redirect to current (checked Oct 2026).

## D3

### Failed

- **Carleton** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site had no 2018 roster in Oct 2026 test.
- **Dubuque** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster.
- **Eastern** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster.
- **Waynesburg** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster.

## NAIA

### Failed

- **Arkansas Baptist** (2024): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: NJCAA through 2020-21; site has no rosters before 2022 (checked Oct 2026); site has rosters for 2022, 2023, 2025, 2026 only (checked Oct 2026).
- **Bethany (KS)** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Doane** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Graceland** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Morningside** (2018): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Nelson** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster; old seasons show the 2024 roster (checked Oct 2026).
- **Oklahoma Panhandle State** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Sterling** (2018): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Texas College** (2024): the site blocks plain downloads, and the pages the browser opened had no roster.

### Partial

- **Cumberland (TN)** (2018: 114 players, 39 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Kentucky Christian** (2018: 122 players, 1 with a hometown): neither the roster page nor the players' own pages list most hometowns.

## JUCO

### Failed

- **American River College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Antelope Valley College** (2018, 2024): couldn't connect to the site: the address in the schools file may be wrong or dead.
- **Arkansas Baptist** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: NJCAA through 2020-21; site has no rosters before 2022 (checked Oct 2026); site has rosters for 2022, 2023, 2025, 2026 only (checked Oct 2026).
- **Butte College** (2018, 2024): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Cabrillo College** (2018, 2024): couldn't connect to the site: the address in the schools file may be wrong or dead.
- **Chaffey College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Coalinga College** (2018, 2024): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **College of the Canyons** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **College of the Desert** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **College of the Siskiyous** (2018): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Compton College** (2018): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **De Anza College** (2018): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Diablo Valley College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **East Los Angeles College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Feather River College** (2018, 2024): couldn't connect to the site: the address in the schools file may be wrong or dead.
- **Foothill College** (2018, 2024): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Fresno City College** (2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Fullerton College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Gavilan College** (2018): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Golden West College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Hartnell College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Kilgore College** (2018): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Lackawanna College** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster; old seasons redirect or are not found (checked Oct 2026).
- **Laney College** (2018, 2024): Left out: rosters are PDFs only (2025, 2026), no web roster pages, Oct 2026.
- **Long Beach City College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Los Angeles Harbor College** (2018, 2024): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Los Angeles Pierce College** (2018): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Minnesota State CTC** (2018, 2024): couldn't connect to the site: the address in the schools file may be wrong or dead.
- **Minnesota West CTC** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Modesto JC** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Mt. San Jacinto College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Navarro College** (2018): the site has no roster for this season: its old-season addresses lead to a newer roster. Note: site has no 2018 roster; old seasons show the 2026 roster (checked Oct 2026).
- **Palomar College** (2018, 2024): no roster page at any of the usual addresses: the site may have moved or use another layout.
- **Pasadena City College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Reedley College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Sacramento City College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Saddleback College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **San Bernardino Valley College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **San Diego Mesa College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **San Joaquin Delta College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **San Jose City College** (2018, 2024): 2018: no roster page at any of the usual addresses: the site may have moved or use another layout; 2024: the site has no roster for this season: its old-season addresses lead to a newer roster.
- **Santa Ana College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Santa Barbara City College** (2024): the site blocks plain downloads, and the pages the browser opened had no roster.
- **Shasta College** (2018, 2024): the site blocks plain downloads, and the pages the browser opened had no roster.

### Partial

- **Blinn** (2018: 78 players, 1 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Chabot College** (2018: 71 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Cisco** (2018: 107 players, 0 with a hometown; 2024: 88 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Citrus College** (2018: 62 players, 17 with a hometown; 2024: 84 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **College of DuPage** (2018: 86 players, 25 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **College of San Mateo** (2018: 79 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **De Anza College** (2024: 64 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Fresno City College** (2018: 65 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Garden City CC** (2018: 66 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Grossmont College** (2018: 71 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Independence CC** (2024: 60 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Moorpark College** (2018: 86 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **North Dakota State College of Science** (2024: 96 players, 5 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Santa Rosa JC** (2018: 74 players, 0 with a hometown; 2024: 80 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Sierra College** (2018: 74 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Trinity Valley CC** (2018: 92 players, 15 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Tyler JC** (2018: 97 players, 1 with a hometown; 2024: 70 players, 1 with a hometown): neither the roster page nor the players' own pages list most hometowns.
- **Victor Valley College** (2018: 64 players, 0 with a hometown): neither the roster page nor the players' own pages list most hometowns.

## Skipped: no athletics site in the schools file

### Current programs (23)

These play now, but no roster site is known: worth finding.

- Central Lakes (JUCO)
- Coahoma CC (JUCO): no athletics roster site found (searched Oct 2026)
- College of the Redwoods (JUCO): no athletics roster site found (searched Oct 2026)
- Community Christian (CA) (JUCO)
- Community Christian (MI) (JUCO)
- Concordia (NE) (NAIA): rosters only as PDF press guides on cune.edu; no roster page to scrape
- Contra Costa College (JUCO): no 2024 season (sat out)
- Fond du Lac (JUCO)
- Itasca CC (JUCO)
- Keiser (NAIA): athletics pages are on keiseruniversity.edu, not Sidearm/PrestoSports; no roster page found
- Los Angeles Southwest College (JUCO)
- Los Angeles Valley College (JUCO)
- Los Medanos College (JUCO)
- Merced College (JUCO)
- Mesabi Range (JUCO)
- Monterey Peninsula College (JUCO)
- Northeastern Oklahoma A&M (JUCO): no athletics roster site found (searched Oct 2026)
- Ottawa (AZ) (NAIA): no athletics roster site found (searched Oct 2026)
- Rochester CTC (JUCO)
- Southwestern College (CA) (JUCO)
- Valley City State (NAIA): no athletics roster site found (searched Oct 2026)
- Vermilion CC (JUCO)
- West Los Angeles College (JUCO)

### Closed or dropped programs (49)

No team now, so nothing to scrape.

- ASA College (JUCO)
- ASA College Miami (JUCO)
- Alderson Broaddus (D2)
- Anna Maria (D3)
- Arizona Western College (JUCO)
- Bacone (NAIA)
- Becker (D3)
- Birmingham-Southern (D3)
- Cheyney (D2)
- College of Marin (JUCO)
- Concordia (MI) (NAIA)
- Dakota College at Bottineau (JUCO)
- Eastern Arizona College (JUCO)
- Finlandia (D3)
- Fort Scott CC (JUCO)
- Glendale CC (AZ) (JUCO)
- Grand Rapids CC (JUCO)
- Harper College (JUCO)
- Haskell (NAIA)
- Humboldt State (D2)
- Iowa Wesleyan (D3)
- Jacksonville (FCS): Pioneer; program dropped after 2019
- Joliet JC (JUCO)
- LIU Brooklyn (FCS): NEC; merged into LIU in 2019
- LIU Post (D2)
- LSU-Eunice (JUCO)
- Limestone (D2)
- Lindenwood-Belleville (NAIA)
- MacMurray (D3)
- Mendocino College (JUCO)
- Mesa CC (JUCO)
- Mississippi College (D2)
- Mount Ida (D3)
- Notre Dame College (D2)
- Phoenix College (JUCO)
- Pima CC (JUCO)
- Ridgewater (JUCO)
- Robert Morris (IL) (NAIA): football moved to Roosevelt in 2020
- Saint Augustine's (D2)
- Saint Joseph's (IN) (D2)
- San Antonio College (JUCO)
- Scottsdale CC (JUCO)
- Siena Heights (NAIA)
- Trinity Bible (NAIA)
- Trinity International (NAIA)
- Urbana (D2)
- Valley Forge Military College (JUCO)
- Wesley (D3)
- Yuba College (JUCO)
