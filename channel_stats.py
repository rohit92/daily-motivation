#!/usr/bin/env python3
"""
channel_stats.py — the system analyzes YOUR channel by itself.

Uses your YouTube Data API key + your channel handle (from config.json) to pull
your real, public per-video stats (views, likes, comments) and your subscriber
count, then writes the view counts straight into library.json — so the
dashboard's Top Performers panel fills in automatically. No more typing numbers.

  python3 channel_stats.py                 # sync using config.json handle
  python3 channel_stats.py --handle @name  # override the handle

Note: this reads PUBLIC data (what anyone can see on your videos). Deep private
analytics (retention %, audience geography) need a bigger OAuth setup — public
view counts already tell you which videos are winning, which is what matters.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import netcfg
import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "assets", "youtube_api_key.txt")  # shared API key
_P = _paths.paths(None)
CONFIG = _P["config"]
LIBRARY = _P["library"]
API = "https://www.googleapis.com/youtube/v3"


def set_channel(channel):
    global CONFIG, LIBRARY
    P = _paths.paths(channel or _paths.DEFAULT_CHANNEL)
    CONFIG, LIBRARY = P["config"], P["library"]


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def get_key():
    if os.environ.get("YT_API_KEY"):
        return os.environ["YT_API_KEY"]
    if os.path.exists(KEY_FILE):
        return open(KEY_FILE).read().strip()
    sys.exit("No YouTube API key. Put it in assets/youtube_api_key.txt")


def api(path, params):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    try:
        with netcfg.opener().open(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = str(e)
        sys.exit(f"YouTube API error ({e.code}): {msg}")


def normalize(title):
    """Reduce a title to its comparable hook: text before the first hashtag,
    letters/digits only, lowercased."""
    head = title.split("#")[0]
    return re.sub(r"[^a-z0-9]", "", head.lower())


def resolve_channel(key, handle, channel_id):
    params = {"part": "contentDetails,statistics,snippet", "key": key}
    if channel_id:
        params["id"] = channel_id
    elif handle:
        params["forHandle"] = handle.lstrip("@")
    else:
        sys.exit("Set channel_handle or channel_id in config.json")
    data = api("channels", params)
    items = data.get("items")
    if not items:
        sys.exit(f"Channel not found for {handle or channel_id}. "
                 "Check the handle in config.json (must match your channel exactly).")
    ch = items[0]
    return {
        "id": ch.get("id", ""),
        "title": ch["snippet"]["title"],
        "subs": int(ch["statistics"].get("subscriberCount", 0)),
        "total_views": int(ch["statistics"].get("viewCount", 0)),
        "video_count": int(ch["statistics"].get("videoCount", 0)),
        "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def all_uploads(key, playlist):
    ids, token = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist,
                  "maxResults": 50, "key": key}
        if token:
            params["pageToken"] = token
        data = api("playlistItems", params)
        ids += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def video_stats(key, ids):
    out = []
    for i in range(0, len(ids), 50):
        data = api("videos", {"part": "snippet,statistics",
                              "id": ",".join(ids[i:i+50]), "key": key})
        for v in data.get("items", []):
            out.append({
                "id": v["id"],
                "url": f"https://www.youtube.com/shorts/{v['id']}",
                "title": v["snippet"]["title"],
                "published": v["snippet"].get("publishedAt", ""),
                "views": int(v["statistics"].get("viewCount", 0)),
                "likes": int(v["statistics"].get("likeCount", 0)),
                "comments": int(v["statistics"].get("commentCount", 0)),
            })
    return out


def recent_comments(key, videos, own_channel_id="", limit=30):
    """Latest public comments across the channel's videos (read-only, API key
    only — no OAuth needed). Feeds the dashboard's comment inbox so the user
    can reply fast (replies are the #1 growth signal at this stage).
    Skips the channel's OWN comments (pinned questions) and keeps the thread
    id so the dashboard's send-reply button can answer in place."""
    out = []
    for v in videos:
        if not v.get("comments"):
            continue                      # no comments on this one — save quota
        try:
            data = api("commentThreads", {
                "part": "snippet", "videoId": v["id"], "maxResults": 20,
                "order": "time", "textFormat": "plainText", "key": key})
        except SystemExit:                # comments disabled or quota — skip
            continue
        for th in data.get("items", []):
            c = th["snippet"]["topLevelComment"]["snippet"]
            author_id = (c.get("authorChannelId") or {}).get("value", "")
            if own_channel_id and author_id == own_channel_id:
                continue                  # our own pinned question, not inbox
            out.append({
                "thread_id": th.get("id", ""),
                "video_id": v["id"],
                "video": v["title"].split("#")[0].strip()[:48],
                "url": v.get("url", ""),
                "author": c.get("authorDisplayName", "someone"),
                "text": c.get("textDisplay", "")[:400],
                "likes": int(c.get("likeCount", 0)),
                "published": c.get("publishedAt", ""),
                "replies": int(th["snippet"].get("totalReplyCount", 0)),
            })
    out.sort(key=lambda c: c["published"], reverse=True)
    return out[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle")
    _paths.add_channel_arg(ap)
    args = ap.parse_args()
    set_channel(args.channel)

    cfg = load(CONFIG, {})
    key = get_key()
    handle = args.handle or cfg.get("channel_handle", "")
    ch = resolve_channel(key, handle, cfg.get("channel_id", ""))

    print(f"Channel: {ch['title']}  |  {ch['subs']:,} subs  |  "
          f"{ch['total_views']:,} total views  |  {ch['video_count']} videos")

    uploaded = video_stats(key, all_uploads(key, ch["uploads"]))
    by_hook = {normalize(v["title"]): v for v in uploaded}

    lib = load(LIBRARY, {"videos": {}})
    matched = 0
    for name, entry in lib["videos"].items():
        hook = normalize(entry["title"])
        hit = by_hook.get(hook)
        if not hit:  # fallback: prefix match
            hit = next((v for k, v in by_hook.items()
                        if k and (k.startswith(hook[:20]) or hook.startswith(k[:20]))), None)
        if hit:
            entry["views"] = hit["views"]
            entry["likes"] = hit["likes"]
            entry["comments"] = hit["comments"]
            if entry.get("status") == "ready":
                entry["status"] = "uploaded"   # it's live, so mark it
            matched += 1

    comments = recent_comments(key, uploaded, own_channel_id=ch.get("id", ""))

    prev = lib.get("channel", {})
    lib["channel"] = {
        "id": ch.get("id", ""),
        "title": ch["title"], "subs": ch["subs"],
        "total_views": ch["total_views"], "video_count": ch["video_count"],
        # full real list of what's LIVE on YouTube, so the Progress tab reflects
        # the actual channel (not just the videos we matched by title)
        "live_videos": sorted(uploaded, key=lambda v: -v["views"]),
        "recent_comments": comments,
        # carry over control-layer state (don't wipe it on every sync)
        "pins_posted": prev.get("pins_posted", []),
        "analytics": prev.get("analytics"),
    }
    with open(LIBRARY, "w") as f:
        json.dump(lib, f, indent=2)
    if comments:
        print(f"Pulled {len(comments)} recent comment(s) — reply from the dashboard!")

    print(f"Matched and updated {matched} of your {len(lib['videos'])} tracked videos.")
    if uploaded and not matched:
        print("No matches — did you edit the titles before uploading? "
              "Views still safe to enter manually in the dashboard.")


if __name__ == "__main__":
    main()
