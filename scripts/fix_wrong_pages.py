"""Trim eight softball school-seasons that the scraper over-read.

Each of these archive pages is a normal softball roster (checked in a browser, Oct 26 2026), but the
scraper saved several times as many people from it (Michigan 2018: 237 saved, 21 on the page). This
keeps only the players actually on each page, matched by name, and removes the rest.

Run from the project folder after the last softball scrape and before the build:
    python3 scripts/fix_wrong_pages.py
A later --retry-failed can save these pages again the wrong way, so run this again after any re-scrape.
"""
import csv
import re
import shutil
from collections import defaultdict
from pathlib import Path

ROSTERS = Path(__file__).resolve().parent.parent / "rosters" / "softball"

# The players on each page, copied from the school's own roster page.
REAL = {
    (2016, "Florida"): "Alex Voss; Aubree Munro; Kelsey Stewart; Aleshia Ocasio; Kelly Barnhill; Taylore Fuller; Amanda Lorenz; Chelsea Herndon; Theresa Swertfager; Kayli Kvistad; Nicole DeWitt; Kirsti Merritt; Janell Wheaton; Brooke Clemens; Delanie Gourley; Lily Mann; Taylor Schwarz; Justine McLean; Sophia Reynoso",
    (2016, "Maryland"): "Jacqui Pascual; Andi Jarvis; Madison Martin; Emily Libero; Skylynne Ellazar; Sami Main; Kristina Dillard; Corey Schwartz; Haley Clements; Hannah Dewey; Brenna Nation; Sarah Lang; Emma Mires; Kylie Datil; Juli Strange; Jordan Aughinbaugh; Ari Jarvis; Destiney Henderson; Sarah Calta; Lindsey Schmeiser",
    (2018, "Michigan"): "Aidan Falk; Abby Skvarce; Madison Uden; Nikki Wald; Meghan Beaubien; Natalie Peters; Amanda Vargas; Taylor Bump; Lou Allan; Alex Sobczak; Morgan Swift; Katie Alexander; Sarah Schaefer; Courtney Richardson; Natalia Rodriguez; Thais Gonzalez; Taylor Swearingen; Tera Blanco; Faith Canfield; Haley Hoogenraad; Mackenzie Nemitz",
    (2021, "Ole Miss"): "Blaise Biringer; Jess Acosta; Ava Tillmann; Mikayla Allee; Raegan Cheyne; Paige Smith; Katelin Cooper; Tate Whitley; Savannah Diederich; Macey Keester; Sydney Gutierrez; Kacey Hvitved; Aynslie Furbush; Lindsey Johnson; Jessica Puk; Anna Borgen; Ally Mena; Autumn Gillespie; Ashlee LaRue; Maddi Banks; Abbey Latham; Mac Barbara; Kelsha Loftin; Nyomi Jones; Landyn Bruce; Gabby Alvarez",
    (2023, "Ole Miss"): "Jalia Lassiter; Savana Sikes; Keila Kamoku; KK Esparza; Mikayla Allee; Brooke Barnard; Annie Orman; Paige Smith; Makenna Segal; Tate Whitley; Natalie Ray; Makenna Kliethermes; Catelyn Riley; Aynslie Furbush; Jenna Lord; Jamie Mackay; Grace Thompson; Taylor Malvin; Grace Sparks; Tenly Grisham; Angelina DeLeon; Lexie Brady; Mya Stevenson; Mackenzie White; Nyomi Jones; Landyn Bruce; Brooke Vestal",
    (2016, "Gardner-Webb"): "Megan Gibbons; Scarlett Harris; Mahaila Irvin; Breanna Blakley; Summer Darnell; Sam Harrell; Ashley Wark; Jill Blank; Megan Champion; Madi Lewis; Rachel Cumiskey; Allie Barrick; Mackenzie Thompson; Kaylee Wacaster; Amanda Gomes; Emma Megal; Callie Thornton; Devyn Terry",
    (2024, "Hampton"): "Kylee Quinn; Cheyenne Crenshaw; Meagan Ramos; Janae Lyles; Aitirihna Aiken; Camryn Thompson; Brooke Williams; Taylor Ivey; Simone Singleton; Taryn Bennett; Kylie Hill; Emily Workman; Jordyn Scott; Santrea Armstead; Jada Evans; Raven Jackson; Leah Maduro; Angelina Branch; Emily Kepple; Carmynn Bonner",
    (2017, "Gardner-Webb"): "Maddi Johnson; Megan Gibbons; Annamarie Warley; Olivia Henson; Alia Booth; Summer Darnell; Sam Harrell; Ashley Wark; Megan Champion; Madi Lewis; Rachel Cumiskey; Allie Barrick; Kaylin Schuda; Mackenzie Thompson; Kaylee Wacaster; Callie Thornton",
}


def key(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


by_season = defaultdict(dict)
for (season, school), names in REAL.items():
    by_season[season][school] = {key(n) for n in names.split(";")}

for season, schools in sorted(by_season.items()):
    path = ROSTERS / f"rosters_{season}.csv"
    if not path.exists():
        print(f"{path.name}: not found, skipped")
        continue
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    name_col = next((c for c in ("name", "player", "player_name") if c in fields), None)
    if "school" not in fields or not name_col:
        raise SystemExit(f"{path.name}: no 'school' or 'name' column (columns: {', '.join(fields)}); nothing changed")
    keep, seen, report = [], set(), defaultdict(lambda: [0, 0])
    for r in rows:
        school = r["school"]
        if school not in schools:
            keep.append(r)
            continue
        k = key(r[name_col])
        report[school][0] += 1
        if k in schools[school] and k not in seen:   # on the real page, and the first copy of her
            seen.add(k)
            keep.append(r)
            report[school][1] += 1
    for school, real in schools.items():
        before, after = report[school]
        warn = "  <- fewer matched than on the page: send this line to Claude" if after < 0.8 * len(real) else ""
        print(f"{season} {school}: {before} saved -> {after} kept (page has {len(real)}){warn}")
    if len(keep) != len(rows):
        shutil.copy(path, path.with_name(path.name + ".bak"))
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(keep)
# Seasons whose page couldn't be checked: print what was saved, so it can be looked at by hand.
REVIEW = [(2021, "Hampton")]   # the site has no 2021 page any more (404); 39 were saved
for season, school in REVIEW:
    path = ROSTERS / f"rosters_{season}.csv"
    if not path.exists():
        continue
    with path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["school"] == school]
    names = [r.get("name") or r.get("player") or r.get("player_name") or "" for r in rows]
    print(f"\nreview {season} {school}: {len(rows)} saved, {len({key(n) for n in names})} different names")
    print("  " + "; ".join(names))

print("done (backups end in .bak)")
