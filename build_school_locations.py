"""Pack config/school_locations.csv into docs/data/school_locations.json for the website.

Each school's campus city, state and coordinates. The map pages use it for the campus marker,
home-state share and distance from campus. Run it after editing the CSV:

    python build_school_locations.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "config" / "school_locations.csv"
OUT = ROOT / "docs" / "data" / "school_locations.json"


def main():
    schools = {}
    with SRC.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            schools[row["school"]] = [row["city"], row["state"], float(row["lat"]), float(row["lon"])]
    OUT.write_text(json.dumps({"fields": ["city", "state", "lat", "lon"], "schools": schools}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(schools)} schools to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
