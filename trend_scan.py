#!/usr/bin/env python3
"""
trend_scan.py — find what's getting PUSHED in your niche right now.

You cannot read YouTube's algorithm (nobody can). What you CAN do, using the
official YouTube Data API, is find the videos gaining views the FASTEST this
week. A video with a high "view velocity" (views per hour since it was posted)
is one the algorithm is actively pushing right now. This tool finds those and
extracts the patterns you can copy: hooks, hashtags, lengths, and post times.

Setup (free, ~3 min):
  1. Go to  https://console.cloud.google.com/
  2. Create a project -> "APIs & Services" -> "Enable APIs" -> enable
     "YouTube Data API v3".
  3. "Credentials" -> "Create credentials" -> "API key". Copy it.
  4. Give it to this script one of two ways:
       export YT_API_KEY=your_key_here          (recommended)
     or save the key into  assets/youtube_api_key.txt

Usage:
  python3 trend_scan.py
  python3 trend_scan.py --days 7 --region US
  python3 trend_scan.py --queries "motivation,discipline,stoic mindset"
  python3 trend_scan.py --demo        # prove the analysis works (no key needed)

Honest caveats:
  - "Pushed" here means "high recent view velocity" — inferred, not insider data.
  - You cannot see other channels' impressions/CTR; those are private.
  - Chasing TRENDING AUDIO can break monetization (copyright). Copy the
    FORMAT/HOOK/LENGTH patterns, not other people's music.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import netcfg
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "assets", "youtube_api_key.txt")
API = "https://www.googleapis.com/youtube/v3"

DEFAULT_QUERIES = ["motivation", "discipline", "self improvement",
                   "motivational speech", "success mindset"]

# What to search for on each channel. Until now every channel scanned the
# motivation queries and shared one report, so script_composer weighted the
# English channel and the facts channel by whatever motivational Shorts were
# trending. Facts came out with every theme at 1.0 — no trend signal at all on
# the channel that needs discovery most.
QUERIES_BY_NICHE = {
    "motivation": DEFAULT_QUERIES,
    "everyday-english": ["learn english", "english speaking practice",
                         "spoken english", "english vocabulary",
                         "english grammar tips"],
    "did-you-know-facts": ["did you know facts", "amazing facts",
                           "science facts", "interesting facts",
                           "mind blowing facts"],
}


def queries_for(channel):
    """The search terms that match what this channel actually publishes."""
    if not channel:
        return DEFAULT_QUERIES
    try:
        import paths as _paths
        niche = _paths.channel_meta(channel).get("niche", "motivation")
    except Exception:
        return DEFAULT_QUERIES
    return QUERIES_BY_NICHE.get(niche, DEFAULT_QUERIES)

STOPWORDS = set(
    "a an the this that these those and or but if then so of to in on for with "
    "your you my me we our it its is are be was were will just how why what when "
    "who from as at by new video shorts short reels reel viral fyp trending".split()
)


def get_key(cli_key):
    if cli_key:
        return cli_key
    if os.environ.get("YT_API_KEY"):
        return os.environ["YT_API_KEY"]
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            k = f.read().strip()
            if k:
                return k
    return None


def api_get(path, params):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    try:
        with netcfg.opener().open(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        msg = body
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            pass
        sys.exit(f"\nYouTube API error ({e.code}): {msg}\n"
                 f"Common causes: bad key, API not enabled, or daily quota used up.")


def search_ids(key, query, days, region):
    after = (datetime.now(timezone.utc)
             .replace(microsecond=0)).timestamp() - days * 86400
    published_after = datetime.fromtimestamp(after, timezone.utc).isoformat().replace("+00:00", "Z")
    data = api_get("search", {
        "part": "snippet", "type": "video", "q": query,
        "order": "viewCount", "publishedAfter": published_after,
        "videoDuration": "short", "maxResults": 50,
        "regionCode": region, "relevanceLanguage": "en", "key": key,
    })
    return [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]


def get_stats(key, ids):
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = api_get("videos", {
            "part": "statistics,contentDetails,snippet",
            "id": ",".join(chunk), "key": key,
        })
        out.extend(data.get("items", []))
    return out


def parse_duration(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def enrich(videos):
    now = datetime.now(timezone.utc)
    rows = []
    for v in videos:
        sn, st = v.get("snippet", {}), v.get("statistics", {})
        views = int(st.get("viewCount", 0))
        pub = sn.get("publishedAt")
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            continue
        hours = max((now - pub_dt).total_seconds() / 3600, 1.0)
        rows.append({
            "id": v.get("id"),
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "desc": sn.get("description", ""),
            "views": views,
            "likes": int(st.get("likeCount", 0) or 0),
            "hours": hours,
            "velocity": views / hours,
            "seconds": parse_duration(v.get("contentDetails", {}).get("duration")),
            "pub_hour_utc": pub_dt.hour,
        })
    return rows


def analyze(rows):
    rows = [r for r in rows if r["views"] > 0]
    rows.sort(key=lambda r: r["velocity"], reverse=True)

    tags = Counter()
    words = Counter()
    for r in rows:
        text = (r["title"] + " " + r["desc"]).lower()
        for t in re.findall(r"#\w+", text):
            tags[t] += 1
        for w in re.findall(r"[a-z']{3,}", r["title"].lower()):
            if w not in STOPWORDS and not w.startswith("#"):
                words[w] += 1

    shorts = [r for r in rows if r["seconds"] <= 60]
    hour_weight = Counter()
    for r in rows[:30]:
        hour_weight[r["pub_hour_utc"]] += r["velocity"]

    return {
        "count": len(rows),
        "top": rows[:15],
        "hashtags": tags.most_common(15),
        "hook_words": words.most_common(20),
        "median_len": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else 0,
        "pct_under_60": round(100 * len(shorts) / len(rows)) if rows else 0,
        "best_hours_utc": [h for h, _ in hour_weight.most_common(3)],
    }


def human(n):
    for unit in ["", "K", "M", "B"]:
        if abs(n) < 1000:
            return f"{n:.0f}{unit}" if unit == "" else f"{n:.1f}{unit}"
        n /= 1000
    return f"{n:.1f}T"


def print_report(a, days):
    print("\n" + "=" * 64)
    print(f"  WHAT'S BEING PUSHED — last {days} days  ({a['count']} videos analyzed)")
    print("=" * 64)

    print("\n TOP BY VIEW VELOCITY (views gained per hour = current push):\n")
    for i, r in enumerate(a["top"], 1):
        print(f" {i:2d}. {human(r['velocity'])}/hr  |  {human(r['views'])} views  |  "
              f"{r['seconds']}s")
        print(f"     {r['title'][:70]}")
        print(f"     — {r['channel']}   youtu.be/{r['id']}")

    print("\n MOST-USED HASHTAGS THIS WEEK:")
    print("   " + "  ".join(f"{t}({c})" for t, c in a["hashtags"]) if a["hashtags"] else "   (none)")

    print("\n MOST-USED HOOK WORDS IN WINNING TITLES:")
    print("   " + ", ".join(f"{w}({c})" for w, c in a["hook_words"]))

    print(f"\n FORMAT: {a['pct_under_60']}% are true Shorts (<=60s). "
          f"Median length: {a['median_len']}s")
    print(f" TOP PERFORMERS POSTED (UTC hour): {a['best_hours_utc']}  "
          f"(add +5:30 for IST, -4/-7 for US)")

    print("\n TAKEAWAYS:")
    print("  - Copy the HOOK PATTERNS and LENGTHS above, not the audio.")
    print("  - Use 2-3 of the top hashtags that actually fit your video.")
    print("  - Match the median length; the algorithm favors what's working.")
    print("=" * 64 + "\n")


DEMO = [
    {"id": "aaa", "snippet": {"title": "This is why you're STILL not disciplined #shorts #motivation",
     "channel": "GrindDaily", "channelTitle": "GrindDaily", "description": "#discipline #mindset #success",
     "publishedAt": "2026-06-29T07:00:00Z"}, "statistics": {"viewCount": "480000"},
     "contentDetails": {"duration": "PT31S"}},
    {"id": "bbb", "snippet": {"title": "Stop waiting. Start now. #motivation #discipline",
     "channelTitle": "MindsetFuel", "description": "#shorts #success #grind",
     "publishedAt": "2026-06-30T21:00:00Z"}, "statistics": {"viewCount": "210000"},
     "contentDetails": {"duration": "PT18S"}},
    {"id": "ccc", "snippet": {"title": "The 5am rule that changed my life #motivation",
     "channelTitle": "RiseUp", "description": "#discipline #shorts #habits",
     "publishedAt": "2026-06-28T06:30:00Z"}, "statistics": {"viewCount": "95000"},
     "contentDetails": {"duration": "PT44S"}},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--region", default="US")
    ap.add_argument("--queries", default=None,
                    help="override the search terms (default: this channel's niche)")
    ap.add_argument("--channel", default=None,
                    help="scan for this channel's niche and write its report")
    ap.add_argument("--key")
    ap.add_argument("--demo", action="store_true", help="run on baked-in sample data")
    args = ap.parse_args()
    if not args.queries:
        args.queries = ",".join(queries_for(args.channel))

    if args.demo:
        print_report(analyze(enrich(DEMO)), args.days)
        return

    key = get_key(args.key)
    if not key:
        sys.exit("No API key. Set YT_API_KEY, use --key, or fill "
                 f"{KEY_FILE}\n(See setup steps at the top of this file, "
                 "or run --demo to preview the output.)")

    ids, seen = [], set()
    for q in [x.strip() for x in args.queries.split(",") if x.strip()]:
        print(f"  searching: {q} ...")
        for vid in search_ids(key, q, args.days, args.region):
            if vid not in seen:
                seen.add(vid)
                ids.append(vid)

    print(f"  found {len(ids)} unique videos; fetching stats ...")
    videos = get_stats(key, ids)
    report = analyze(enrich(videos))

    print_report(report, args.days)
    try:
        import paths as _paths
        out = _paths.paths(args.channel)["trends"]
        os.makedirs(os.path.dirname(out), exist_ok=True)
    except Exception:
        out = os.path.join(HERE, "trends_report.json")
    with open(out, "w") as f:
        json.dump({
            "generated": datetime.now(timezone.utc).isoformat(),
            "days": args.days, "region": args.region,
            "top": report["top"], "hashtags": report["hashtags"],
            "hook_words": report["hook_words"],
            "median_len": report["median_len"],
            "best_hours_utc": report["best_hours_utc"],
        }, f, indent=2)
    print(f"Saved full data to {os.path.relpath(out, HERE)}\n")


if __name__ == "__main__":
    main()
