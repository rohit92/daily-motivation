#!/usr/bin/env python3
"""
fetch_backgrounds.py — download copyright-safe background images.

All sources here are free for commercial use (safe for a monetized channel).
NEVER drop random Google-image-search results into assets/backgrounds/ — most
are copyrighted and will get your channel demonetized or struck.

Usage:
  # Keyless: random high-quality photos from Picsum (Unsplash license)
  python3 fetch_backgrounds.py --count 20

  # Themed: search Pexels (free API key from https://www.pexels.com/api/)
  python3 fetch_backgrounds.py --pexels-key YOUR_KEY --query "dark mountains" --count 20
"""

import argparse
import os
import sys
import urllib.request
import json as _json

HERE = os.path.dirname(os.path.abspath(__file__))
BG_DIR = os.path.join(HERE, "assets", "backgrounds")


def save(url, path, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if len(data) < 1000:
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def next_index():
    existing = [f for f in os.listdir(BG_DIR) if f.startswith("bg_")]
    return len(existing) + 1


def from_picsum(count, start):
    for i in range(count):
        n = f"{start + i:02d}"
        # random photo per request; seed keeps it reproducible
        url = f"https://picsum.photos/seed/mv{start+i}/1080/1920"
        path = os.path.join(BG_DIR, f"bg_{n}.jpg")
        ok = save(url, path)
        print(("ok   " if ok else "FAIL ") + f"bg_{n}")


def from_pexels(key, query, count, start):
    hdr = {"Authorization": key}
    url = (f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}"
           f"&orientation=portrait&per_page={count}&size=large")
    req = urllib.request.Request(url, headers=hdr)
    data = _json.loads(urllib.request.urlopen(req, timeout=30).read())
    photos = data.get("photos", [])
    if not photos:
        sys.exit("No results from Pexels for that query.")
    for i, p in enumerate(photos):
        n = f"{start + i:02d}"
        src = p["src"].get("portrait") or p["src"]["large"]
        path = os.path.join(BG_DIR, f"bg_{n}.jpg")
        ok = save(src, path, hdr)
        print(("ok   " if ok else "FAIL ") + f"bg_{n}  ({p.get('photographer','?')})")


def main():
    import urllib.parse  # noqa
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--pexels-key")
    ap.add_argument("--query", default="dark nature landscape")
    args = ap.parse_args()

    os.makedirs(BG_DIR, exist_ok=True)
    start = next_index()
    if args.pexels_key:
        from_pexels(args.pexels_key, args.query, args.count, start)
    else:
        from_picsum(args.count, start)
    print(f"\nDone. Backgrounds are in {BG_DIR}")


if __name__ == "__main__":
    import urllib.parse  # used in from_pexels
    main()
