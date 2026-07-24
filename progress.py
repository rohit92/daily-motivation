#!/usr/bin/env python3
"""
progress.py — your channel's progress, in one place.

Two jobs:
  1. summary()  — compute real metrics from library.json (subs, views, top
     videos, what's working by theme, cadence) for the dashboard's Progress tab.
  2. profile    — an editable "about my channel" record (goal, audience, style,
     notes) stored in profile.json. The local AI reads it (via ai_brain) so its
     scripts and coaching are tailored to YOUR channel, not generic.

  python3 progress.py            # print the computed summary as JSON
  python3 progress.py --context  # print the compact text the AI sees
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
_P = _paths.paths(None)
LIBRARY = _P["library"]
CONFIG = _P["config"]
PROFILE = _P["profile"]   # shared


def set_channel(channel):
    global LIBRARY, CONFIG, PROFILE
    P = _paths.paths(channel or _paths.DEFAULT_CHANNEL)
    LIBRARY, CONFIG, PROFILE = P["library"], P["config"], P["profile"]

# What we ask the creator to describe. The AI reads all of it.
DEFAULT_PROFILE = {
    "goal": "",
    "audience": "",
    "style": "",
    "notes": "",
}


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, data):
    json.dump(data, open(path, "w"), indent=2)


# ---------- editable channel profile ----------

def get_profile():
    return {**DEFAULT_PROFILE, **(load(PROFILE, {}) or {})}


def save_profile(d):
    cur = get_profile()
    for k in DEFAULT_PROFILE:
        if k in d and isinstance(d[k], str):
            cur[k] = d[k].strip()
    save(PROFILE, cur)
    return cur


# ---------- computed metrics ----------

def _num(v, k):
    return v.get(k) or 0     # treat None / missing as 0


# keyword → theme, so live videos (which only carry a title) can be grouped
THEME_WORDS = {
    "discipline": ["disciplin"],
    "consistency": ["consisten", "every day", "everyday", "habit", "show up",
                    "keep going"],
    "focus": ["focus", "distract", "attention", "phone", "scroll"],
    "self-belief": ["believ", "doubt", "fear", "yourself", "your mind"],
    "hard work": ["work", "grind", "sweat", "reps", "earn", "hustle", "champion",
                  "pain", "strength"],
    "comeback": ["comeback", "fall", "fail", "rise", "back up", "setback", "quit"],
    "starting": ["start", "begin", "year from now", "waiting", "decision"],
}


def _infer_theme(title):
    # only the hook matters — strip hashtags so #discipline etc. don't skew it
    t = (title or "").split("#")[0].lower()
    for theme, keys in THEME_WORDS.items():
        if any(k in t for k in keys):
            return theme
    return "motivation"


def _post_dates(live):
    """IST calendar dates the channel actually published on (from the real
    publishedAt timestamps channel_stats now stores)."""
    dates = set()
    for v in live:
        p = v.get("published")
        if not p:
            continue
        try:
            dt = datetime.fromisoformat(p.replace("Z", "+00:00")).astimezone(IST)
            dates.add(dt.date())
        except ValueError:
            continue
    return dates


def streak_info(live):
    """(streak_days, days_since_post). The streak survives until a full IST
    day is missed — posting is 'alive' if the last post was today or yesterday.
    Returns (None, None) when publish dates haven't been synced yet."""
    dates = _post_dates(live)
    if not dates:
        return None, None
    today = datetime.now(IST).date()
    days_since = (today - max(dates)).days
    if days_since > 1:
        return 0, days_since
    day = today if today in dates else today - timedelta(days=1)
    streak = 0
    while day in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak, days_since


def summary():
    lib = load(LIBRARY, {"videos": {}}) or {"videos": {}}
    ch = lib.get("channel", {})
    vids = lib.get("videos", {})
    values = list(vids.values())
    ready = [v for v in values if v.get("status") == "ready"]
    live = ch.get("live_videos") or []
    subs = ch.get("subs", 0)

    if live:                    # REAL channel data — what's actually on YouTube
        source = [{"title": v.get("title", ""), "views": _num(v, "views"),
                   "likes": _num(v, "likes"), "comments": _num(v, "comments"),
                   "theme": _infer_theme(v.get("title", ""))} for v in live]
        posted = ch.get("video_count", len(live))
        last_posted = None
    else:                       # fallback — our locally-tracked uploads
        up = [v for v in values if v.get("status") == "uploaded"]
        source = [{"title": v.get("title", ""), "views": _num(v, "views"),
                   "likes": _num(v, "likes"), "comments": _num(v, "comments"),
                   "theme": (v.get("theme") or "").strip() or "unlabeled"} for v in up]
        posted = len(up)
        dates = sorted(v.get("created") for v in up if v.get("created"))
        last_posted = dates[-1] if dates else None

    with_views = [v for v in source if v["views"] > 0]
    video_views = sum(v["views"] for v in source)
    likes = sum(v["likes"] for v in source)
    comments = sum(v["comments"] for v in source)
    avg_views = round(video_views / len(with_views)) if with_views else 0
    top = sorted(with_views, key=lambda v: -v["views"])[:5]

    themes = defaultdict(lambda: {"count": 0, "views": 0})
    for v in source:
        themes[v["theme"]]["count"] += 1
        themes[v["theme"]]["views"] += v["views"]
    theme_rows = sorted(themes.items(), key=lambda kv: -kv[1]["views"])
    best_theme = next((t for t, d in theme_rows
                       if d["views"] > 0 and t not in ("unlabeled", "motivation")), None)

    streak, days_since = streak_info(live)

    return {
        "title": ch.get("title", "Mindset Refuel"),
        "streak": streak,
        "days_since_post": days_since,
        "subs": subs,
        "channel_total_views": ch.get("total_views", 0),
        "posted": posted,
        "ready": len(ready),
        "tracked": len(values),
        "video_views": video_views,
        "likes": likes,
        "comments": comments,
        "avg_views": avg_views,
        "top": [{"title": v["title"], "views": v["views"], "likes": v["likes"],
                 "theme": v["theme"]} for v in top],
        "themes": [{"theme": t, "count": d["count"], "views": d["views"]}
                   for t, d in theme_rows],
        "best_theme": best_theme,
        "last_posted": last_posted,
        "subs_to_1k": max(0, 1000 - subs),
    }


def context_block():
    """Compact text the local model sees, so it tailors output to this channel.
    Kept short on purpose (small local models have limited context)."""
    s = summary()
    p = get_profile()
    lines = []
    if any(p.values()):
        lines.append("About this channel (creator's own words):")
        if p["goal"]:
            lines.append(f"  Goal: {p['goal']}")
        if p["audience"]:
            lines.append(f"  Audience: {p['audience']}")
        if p["style"]:
            lines.append(f"  Voice/style: {p['style']}")
        if p["notes"]:
            lines.append(f"  Notes: {p['notes']}")
    lines.append(
        f"Progress: {s['subs']} subs, {s['posted']} posted, "
        f"{s['video_views']:,} total views on tracked videos, "
        f"avg {s['avg_views']} views/video.")
    if s["best_theme"]:
        lines.append(f"Best-performing theme so far: {s['best_theme']}.")
    if s["top"]:
        lines.append("Top videos: " + "; ".join(
            f"{t['title'][:40]} ({t['views']:,} views)" for t in s["top"][:3]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", action="store_true",
                    help="print the compact text the AI sees")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)
    if a.context:
        print(context_block())
    else:
        print(json.dumps(summary(), indent=2))


if __name__ == "__main__":
    main()
