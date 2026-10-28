#!/usr/bin/env python3
"""Compress the downloaded pages in .cache/html (each <name>.html becomes <name>.html.gz, ~14x smaller).

Since Oct 28 the scraper saves pages compressed and reads both kinds, so this only frees the space the
pages saved before then take (64 GB -> ~5 GB). Safe to stop at any time and run again: it carries on
where it stopped. Don't run it while a scrape of any sport is running.

    python3 scripts/compress_cache.py               # everything (about 10-20 minutes)
    python3 scripts/compress_cache.py --minutes 5   # stop after 5 minutes
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import Fetcher  # noqa: E402

CACHE = Path(__file__).resolve().parent.parent / ".cache" / "html"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=0, help="stop after this many minutes (default: run to the end)")
    ap.add_argument("--cache", type=Path, default=CACHE)
    args = ap.parse_args(argv)
    stop = time.monotonic() + args.minutes * 60 if args.minutes else None
    done = before = after = left = 0
    with os.scandir(args.cache) as it:
        names = [e.name for e in it]
    for name in names:
        path = args.cache / name
        if name.endswith((".part", ".tmp")) or ".html.gz." in name:
            path.unlink(missing_ok=True)            # left over from a stopped download or an earlier stopped run
            continue
        if not name.endswith(".html"):
            continue
        if stop and time.monotonic() > stop:
            left += 1
            continue
        try:
            size = path.stat().st_size
            Fetcher.write_cached(path, path.read_text(encoding="utf-8", errors="replace"))
            before += size
            after += Fetcher.gz_path(path).stat().st_size
            done += 1
        except FileNotFoundError:
            continue
        if done % 2000 == 0:
            print(f"  {done:,} pages, {before / 1e9:.1f} GB -> {after / 1e9:.2f} GB", flush=True)
    print(f"Compressed {done:,} pages: {before / 1e9:.1f} GB -> {after / 1e9:.2f} GB."
          + (f" {left:,} left: run it again to finish." if left else " All done."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
