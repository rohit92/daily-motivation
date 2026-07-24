#!/usr/bin/env python3
"""
make_schedule.py — builds a 180-day (6-month) day-by-day plan into schedule.csv.

  python3 make_schedule.py                    # start today
  python3 make_schedule.py --start 2026-07-04 # start on a date
  python3 make_schedule.py --days 180

Daily rhythm (≈15–30 min of human work):
  every day   : upload today's video to YouTube + Instagram Reels, reply to comments
  Monday      : click Generate on the dashboard (makes next 7 videos + metadata)
  Wednesday   : share one video to a community (group/story) — no spam
  Friday      : post an IG Story pointing to the product in bio
  Sunday      : 10-min analytics review — note best video of the week
Milestones baked in at days 7/30/60/90/120/150/180.
"""

import argparse
import csv
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "schedule.csv")

WEEKLY = {
    0: "GENERATE: open dashboard, click Generate (7 new videos + titles ready)",
    2: "SHARE: post one video to a community/group where it fits (no spam)",
    4: "PROMOTE: IG Story pointing to the product link in bio",
    6: "REVIEW: 10 min in YouTube Studio analytics — note best video + retention %",
}

MILESTONES = {
    7:   "Week 1 done — streak matters more than views right now",
    30:  "Month 1: check subs. Set Gumroad + affiliate links in links.json if not done",
    60:  "Month 2: compare your 5 best videos — tell the composer's themes via trend scan",
    90:  "Month 3: if any video >100k views, consider 2x/day posting",
    120: "Month 4: review income streams — product sales? affiliate clicks? adjust",
    150: "Month 5: check YPP eligibility progress (subs + views) in Studio -> Earn",
    180: "Month 6: half-year review — YPP application if eligible; scale or adjust niche",
    210: "Month 7: refresh backgrounds (fetch_backgrounds.py) + regenerate music if stale",
    240: "Month 8: pitch 1 app sponsorship if over ~10k followers",
    270: "Month 9: launch a 2nd product (planner/notion template) on Gumroad",
    300: "Month 10: audit which themes win; drop the weak ones from the composer",
    330: "Month 11: consider a 2nd higher-RPM channel (finance/tech)",
    365: "YEAR 1 DONE. Review total income, re-plan year 2. Consider re-subscribing "
         "to Claude for a fresh script bank + new features.",
}


def build(start, days):
    rows = []
    for i in range(1, days + 1):
        d = start + timedelta(days=i - 1)
        tasks = [f"Upload video #{i} to YouTube Shorts + Instagram Reels",
                 "Reply to every new comment"]
        w = WEEKLY.get(d.weekday())
        if w:
            tasks.append(w)
        m = MILESTONES.get(i)
        if m:
            tasks.append(f"MILESTONE: {m}")
        rows.append({
            "date": d.isoformat(),
            "day": i,
            "weekday": d.strftime("%A"),
            "video": i,
            "tasks": " | ".join(tasks),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=date.today().isoformat())
    ap.add_argument("--days", type=int, default=365)
    a = ap.parse_args()
    start = date.fromisoformat(a.start)
    rows = build(start, a.days)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "day", "weekday", "video", "tasks"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} days to schedule.csv "
          f"({rows[0]['date']} → {rows[-1]['date']})")


if __name__ == "__main__":
    main()
