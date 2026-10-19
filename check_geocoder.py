"""Check which geocoder version is in this folder and test a few towns that didn't place.

    python check_geocoder.py
"""
from pathlib import Path

src = Path("geocode_hometowns.py").read_text(encoding="utf-8")
print("geocoder has the latest fixes:", "school recruits most" in src)
print("geocoder has the hometown aliases:", '"hallandale beach"' in src)

import geocode_hometowns as g  # noqa: E402

print("\nLoading place data (about a minute)...")
gaz = g.Gazetteer()
print(f"Census places: {len(gaz.places):,}   USGS places: {len(gaz.gnis):,}   counties: {len(gaz.counties):,}")
for name, state in [("Rabun Gap", "GA"), ("Ellenwood", "GA"), ("Loxahatchee", "FL"), ("Mililani", "HI"),
                    ("Hallandale", "FL"), ("Indian Land", "SC"), ("Cypress", "TX")]:
    print(f"  {name}, {state}: {gaz.lookup_us(name, state)}")
print("\nUSGS keys that start with 'rabun' or 'ellenwood':",
      [k for k in gaz.gnis if k[0].startswith(("rabun", "ellenwood"))][:10])
print("Census keys that start with 'rabun':", [k for k in gaz.places if k[0].startswith("rabun")][:10])
