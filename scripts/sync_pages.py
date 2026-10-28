#!/usr/bin/env python3
"""Copy football's map pages to every other sport, so a fix made once reaches all of them.

    python3 scripts/sync_pages.py           # write docs/<sport>/players-*.html for every sport but football
    python3 scripts/sync_pages.py --check   # only say which pages differ from football's beyond their own words

docs/football/players-dotmap.html, players-heatmap.html and players-transfers.html are the masters: edit those,
then run this. Each other sport keeps its own words, taken from its current page: the <title>, the description,
the <h1> heading and the subtitle (id="sub"); women's sports also get she/her for he/his/him. Everything else comes
from football's page. (Before Oct 28 the pages were edited one by one, and the other sports never got football's
multi-conference filter: picking two conferences there left the heading at "All-school stats".)
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT, available_sports  # noqa: E402

PAGES = ["players-dotmap.html", "players-heatmap.html", "players-transfers.html"]
MASTER = "football"
WOMEN = {"softball", "lacrosse-womens"}
# The lines a sport keeps from its own page: one pattern per line, matched against the whole line
OWN_LINES = [re.compile(p) for p in (r"^\s*<title>.*</title>\s*$", r'^\s*<meta name="description" .*>\s*$',
                                      r"^\s*<h1>.*</h1>\s*$", r'^\s*<p class="sub" id="sub">.*</p>\s*$')]
_PRONOUNS = {"he": "she", "his": "her", "him": "her", "He": "She", "His": "Her"}


def build(master: str, own: str, women: bool) -> str:
    """The sport's page: the master's lines, with the sport's own title, description, heading and subtitle."""
    mine = {}
    for line in own.splitlines():
        for i, pat in enumerate(OWN_LINES):
            if i not in mine and pat.match(line):
                mine[i] = line
    out = []
    for line in master.splitlines():
        hit = next((i for i, pat in enumerate(OWN_LINES) if pat.match(line)), None)
        if hit is not None and hit in mine:
            line = mine[hit]
        elif women:
            line = re.sub(r"\b(he|his|him|He|His)\b", lambda m: _PRONOUNS[m.group(1)], line)
        out.append(line)
    return "\n".join(out) + ("\n" if master.endswith("\n") else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="don't write: list the pages that differ and how many lines")
    args = ap.parse_args(argv)
    docs = ROOT / "docs"
    stale = 0
    for sport in available_sports():
        if sport == MASTER:
            continue
        for page in PAGES:
            master_path, path = docs / MASTER / page, docs / sport / page
            if not path.exists() or not master_path.exists():
                continue
            old = path.read_text(encoding="utf-8")
            new = build(master_path.read_text(encoding="utf-8"), old, sport in WOMEN)
            if new == old:
                continue
            stale += 1
            changed = sum(1 for d in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
                          if d[:1] in "+-" and not d.startswith(("+++", "---")))
            print(f"{'differs' if args.check else 'updated'}: docs/{sport}/{page} ({changed} lines)")
            if not args.check:
                path.write_text(new, encoding="utf-8")
    if not stale:
        print("Every sport's pages match football's.")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
