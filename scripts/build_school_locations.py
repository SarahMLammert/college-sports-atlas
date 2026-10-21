"""Pack config/school_locations.csv into docs/<sport>/school_locations.json for the website.

Each school's campus city, state and coordinates. The map pages use it for the campus marker,
home-state share and distance from campus. The CSV is shared by every sport; each sport's JSON only
holds that sport's schools (from config/<sport>_schools.csv) when that file exists. Run it after
editing the CSV:

    python scripts/build_school_locations.py                 # football
    python scripts/build_school_locations.py --sport mens-basketball
"""
import argparse
import csv
import json

from paths import ROOT, add_sport_argument, load_schools, load_sport


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_sport_argument(ap)
    sport = load_sport(ap.parse_args(argv).sport)
    wanted = {s["school"] for s in load_schools(sport.schools_csv)} if sport.schools_csv.exists() else None
    schools = {}
    with sport.locations_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if wanted is None or row["school"] in wanted:
                schools[row["school"]] = [row["city"], row["state"], float(row["lat"]), float(row["lon"])]
    out = sport.site_dir / "school_locations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"fields": ["city", "state", "lat", "lon"], "schools": schools}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(schools)} schools to {out.relative_to(ROOT)}")
    if wanted:
        missing = sorted(wanted - set(schools))
        if missing:
            print(f"no campus in {sport.locations_csv.relative_to(ROOT)} for:", ", ".join(missing))


if __name__ == "__main__":
    main()
