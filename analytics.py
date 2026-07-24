#!/usr/bin/env python3
"""
analytics.py — the numbers YouTube hides from the public: RETENTION.

Views tell you a video was tested; retention (% of the video people actually
watch) tells you WHY it won or died — it's the single number the algorithm
uses to decide whether to push a Short wider. This pulls it per video from
the YouTube Analytics API, plus where your views come from.

Needs the one-time Google connect (dashboard Settings → YouTube connection).

  python3 analytics.py --sync     # pull retention + traffic → library.json
  python3 analytics.py --report   # print the retention report

After a sync, the Progress tab shows retention per video, and the AI coach
starts using retention (not just views) to judge what's working.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

import yt_auth
import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARY = _paths.paths(None)["library"]
CHANNEL = _paths.DEFAULT_CHANNEL
START = "2026-07-01"                      # channel's first upload


def set_channel(channel):
    global LIBRARY, CHANNEL
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    LIBRARY = _paths.paths(CHANNEL)["library"]
    yt_auth.set_channel(CHANNEL)


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def sync():
    lib = load(LIBRARY, {"videos": {}})
    live = (lib.get("channel", {}).get("live_videos") or [])
    if not live:
        sys.exit("No live videos in library.json — run 'Sync my stats' first.")
    ids = [v["id"] for v in live]

    try:
        yta = yt_auth.analytics_api(interactive=False)
    except yt_auth.NotConnected as e:
        sys.exit(f"✗ {e}")

    end = date.today().isoformat()

    # per-video: retention + watch time + subs earned
    r = yta.reports().query(
        ids="channel==MINE", startDate=START, endDate=end,
        metrics=("views,estimatedMinutesWatched,averageViewDuration,"
                 "averageViewPercentage,likes,subscribersGained"),
        dimensions="video", filters="video==" + ",".join(ids),
        maxResults=200).execute()
    cols = [c["name"] for c in r.get("columnHeaders", [])]
    by_video = {}
    for row in r.get("rows", []):
        d = dict(zip(cols, row))
        by_video[d["video"]] = {
            "views": int(d.get("views", 0)),
            "watch_min": round(float(d.get("estimatedMinutesWatched", 0)), 1),
            "avg_sec": round(float(d.get("averageViewDuration", 0)), 1),
            "avg_pct": round(float(d.get("averageViewPercentage", 0)), 1),
            "likes": int(d.get("likes", 0)),
            "subs_gained": int(d.get("subscribersGained", 0)),
        }

    # where views come from (channel-wide)
    t = yta.reports().query(
        ids="channel==MINE", startDate=START, endDate=end,
        metrics="views", dimensions="insightTrafficSourceType",
        sort="-views", maxResults=10).execute()
    traffic = [{"source": row[0], "views": int(row[1])}
               for row in t.get("rows", [])]

    lib.setdefault("channel", {})["analytics"] = {
        "synced": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "videos": by_video,
        "traffic": traffic,
    }
    json.dump(lib, open(LIBRARY, "w"), indent=2)
    print(f"✓ Retention synced for {len(by_video)} videos "
          f"+ {len(traffic)} traffic sources.")
    report(lib)


def report(lib=None):
    lib = lib or load(LIBRARY, {"videos": {}})
    ch = lib.get("channel", {})
    an = ch.get("analytics")
    if not an:
        print("No retention data yet. Connect YouTube (Settings) and run "
              "'Sync retention'.")
        return
    titles = {v["id"]: v["title"].split("#")[0].strip()[:44]
              for v in ch.get("live_videos", [])}
    rows = sorted(an["videos"].items(), key=lambda kv: -kv[1]["avg_pct"])
    print("=" * 74)
    print(f"  RETENTION REPORT  ·  synced {an['synced']}")
    print("  >70% avg = the algorithm pushes it wider. <50% = the hook loses them.")
    print("=" * 74)
    print(f"{'watched':>8} {'avg sec':>8} {'views':>7} {'+subs':>6}  video")
    for vid, d in rows:
        print(f"{d['avg_pct']:>7.0f}% {d['avg_sec']:>8} {d['views']:>7} "
              f"{d['subs_gained']:>6}  {titles.get(vid, vid)}")
    if an.get("traffic"):
        print("\nWhere your views come from:")
        total = sum(t["views"] for t in an["traffic"]) or 1
        for t in an["traffic"]:
            print(f"  {t['views']:>6} ({t['views']/total*100:.0f}%)  {t['source']}")
    print("=" * 74)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--report", action="store_true")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)
    if a.sync:
        sync()
    else:
        report()


if __name__ == "__main__":
    main()
