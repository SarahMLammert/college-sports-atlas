"""Run on your Mac from the project folder:  python scripts/find_athletics_domains.py
Follows each link in rosters/football/redirect_check.csv (athletics pages on a college's main site)
to where it ends up, and fills in that domain in config/football_schools.csv when the school's
domain is still blank. Prints what it did; nothing else is changed.
"""
import csv
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "rosters" / "football" / "redirect_check.csv"
SCHOOLS = ROOT / "config" / "football_schools.csv"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) college-sports-atlas"}

found = {}
for r in csv.DictReader(open(CHECK)):
    try:
        with urllib.request.urlopen(urllib.request.Request(r["ncaa_url"], headers=UA), timeout=30) as resp:
            final = resp.geturl()
    except Exception as e:  # noqa: BLE001
        print(f"  {r['school']}: could not open ({e})")
        continue
    host = urlparse(final).netloc.lower().removeprefix("www.")
    path = urlparse(final).path.strip("/")
    if path and "athletic" in path.lower():
        print(f"  {r['school']}: still on the college site ({final}); set roster_url by hand")
        continue
    found[r["school"]] = host
    print(f"  {r['school']}: {host}")

rows = list(csv.DictReader(open(SCHOOLS)))
fields = list(rows[0])
n = 0
for x in rows:
    if x["school"] in found and not x["domain"] and x["division"] in ("D2", "D3"):
        x["domain"] = found[x["school"]]
        n += 1
with open(SCHOOLS, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
print(f"filled {n} rows")
