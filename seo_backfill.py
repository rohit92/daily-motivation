#!/usr/bin/env python3
"""
seo_backfill.py — put tags, the right category, and a real channel profile on
work that is already published.

seo.py fixes this going forward. This fixes the back catalogue: every video
uploaded before the fix went up with no tags and categoryId 22, and all three
channels still have an empty description and empty keywords. A video with no
tags can still be found — YouTube reads the title and description — but it is
competing with both hands tied, and these videos will keep accruing views for
years.

Nothing here touches the video file, the title, or the view count. It edits
metadata only, and it never clears a field that already has something in it.

QUOTA: videos.update costs 50 units, channels.update 50. A full backfill of ~28
videos plus 3 channels is about 1,550 of the 10,000 units/day. Uploads cost
1,600 each, so run this when the day's uploads are already done.

  python3 seo_backfill.py                    # dry run — show every change
  python3 seo_backfill.py --apply            # write it
  python3 seo_backfill.py --apply --videos-only
  python3 seo_backfill.py --apply --channel facts
"""
import argparse
import json
import os
import sys

import paths as _paths
import seo
import yt_auth

VIDEO_UPDATE_UNITS = 50
CHANNEL_UPDATE_UNITS = 50
# Keep enough units in reserve for one upload. Backfilling metadata on a video
# published last month is never worth losing tonight's post — and the two share
# one 10,000-unit project quota.
DEFAULT_RESERVE = 1600


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def quota_left(reserve=DEFAULT_RESERVE):
    """Units we may spend right now, per schedule_queue's own ledger.

    Google resets the real quota at midnight Pacific, which is the middle of the
    following day in IST — so the morning autopilot run is still inside the
    previous quota day. Spending freely here is how tomorrow's upload dies with
    quotaExceeded.
    """
    try:
        import schedule_queue as SQ
        q = SQ.load(SQ.QUEUE, {}) or {}
        budget = q.get("daily_budget", 8000)
        # SQ.quota_day(), not the local date: Google's counter rolls over at
        # midnight Pacific and the ledger is keyed to that.
        spent = (q.get("spent") or {}).get(SQ.quota_day(), 0)
        return max(0, budget - spent - reserve)
    except Exception:
        return 0            # can't tell → assume none, never gamble


def charge(units):
    """Record what we spent, so uploads see an honest ledger."""
    if units <= 0:
        return
    try:
        import schedule_queue as SQ
        q = SQ.load(SQ.QUEUE, {}) or {}
        today = SQ.quota_day()
        q.setdefault("spent", {})[today] = (q.get("spent") or {}).get(today, 0) + units
        SQ.save(q)
    except Exception:
        pass


def theme_index(slug):
    """{video_id: theme} from this channel's library."""
    lib = load(_paths.paths(slug)["library"], {"videos": {}}) or {"videos": {}}
    out = {}
    for entry in (lib.get("videos") or {}).values():
        vid = entry.get("video_id")
        if vid and entry.get("theme"):
            out[vid] = entry["theme"]
    return out


def live_snippets(yt):
    """Every video on the channel with its current snippet."""
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items") or []
    if not items:
        raise RuntimeError("channel not found for this token")
    pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, page = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=pl,
                                    maxResults=50, pageToken=page).execute()
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break

    out = {}
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,contentDetails",
                             id=",".join(ids[i:i + 50])).execute()
        for v in r.get("items", []):
            out[v["id"]] = {"snippet": v["snippet"],
                            "duration": v["contentDetails"].get("duration", "")}
    return out


def _is_longform(duration):
    """PT#M#S over a minute, or any duration with an H — not a Short."""
    d = duration or ""
    if "H" in d:
        return True
    import re
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return False
    return int(m.group(1) or 0) >= 1


def backfill_videos(slug, yt, apply=False, budget=None):
    themes = theme_index(slug)
    try:
        live = live_snippets(yt)
    except Exception as e:
        print(f"  ! could not read the channel ({type(e).__name__}: "
              f"{str(e)[:120]}) — skipping")
        return 0, 0

    want_cat = seo.category_id(slug)
    changed = 0
    for vid, info in sorted(live.items()):
        snip = info["snippet"]
        title = snip.get("title", "")
        have_tags = snip.get("tags") or []
        have_cat = snip.get("categoryId", "")
        longform = _is_longform(info["duration"])
        # 'story' is a format, not a topic, and most older entries have no
        # theme at all — fall back to reading it off the title.
        theme = themes.get(vid, "")
        if theme not in seo.THEME_TERMS:
            theme = seo.guess_theme(slug, title)

        new_tags = seo.tags_for(slug, theme=theme, longform=longform, title=title)
        # Never throw away tags someone added by hand — merge and re-fit.
        if have_tags:
            new_tags = seo._fit(list(have_tags) + new_tags)

        need_tags = set(t.lower() for t in new_tags) != set(t.lower() for t in have_tags)
        need_cat = have_cat != want_cat
        if not (need_tags or need_cat):
            print(f"  · {vid}  already good")
            continue

        # Check the budget BEFORE announcing the change, so a stopped run never
        # prints an edit marker for something it did not write.
        if apply and budget is not None and budget[0] < VIDEO_UPDATE_UNITS:
            print(f"  · quota reserve reached — {vid} and the rest are unchanged; "
                  f"re-run after the reset and it resumes here")
            break

        bits = []
        if need_tags:
            bits.append(f"tags {len(have_tags)}→{len(new_tags)}")
        if need_cat:
            bits.append(f"category {have_cat}→{want_cat}")
        print(f"  {'✎' if apply else '→'} {vid}  {', '.join(bits)}"
              f"   {title[:48]}")
        if need_tags and not have_tags:
            print(f"        + {', '.join(new_tags[:8])}"
                  + (" …" if len(new_tags) > 8 else ""))

        if apply:
            # videos.update REPLACES the whole snippet part, so every field we
            # want to keep has to be sent back. Dropping title/description here
            # would blank them on a live video.
            body = {"id": vid, "snippet": {
                "title": title,
                "description": snip.get("description", ""),
                "categoryId": want_cat,
                "tags": new_tags,
            }}
            for k in ("defaultLanguage", "defaultAudioLanguage"):
                if snip.get(k):
                    body["snippet"][k] = snip[k]
            try:
                yt.videos().update(part="snippet", body=body).execute()
            except Exception as e:
                print(f"     ✗ failed: {type(e).__name__}: {str(e)[:140]}")
                continue
            if budget is not None:
                budget[0] -= VIDEO_UPDATE_UNITS
                charge(VIDEO_UPDATE_UNITS)
        changed += 1
    return changed, changed * VIDEO_UPDATE_UNITS


def backfill_channel(slug, yt, apply=False):
    """Set the About text and channel keywords — empty on all three channels."""
    r = yt.channels().list(part="brandingSettings,snippet", mine=True).execute()
    items = r.get("items") or []
    if not items:
        print("  ! channel not found")
        return 0, 0
    ch = items[0]
    bs = ch.get("brandingSettings") or {}
    cur = bs.get("channel") or {}

    want_desc = seo.channel_about(slug)
    want_kw = seo.channel_keywords(slug)
    have_desc = (cur.get("description") or "").strip()
    have_kw = (cur.get("keywords") or "").strip()

    # Only fill what is empty. If the owner has written their own About text,
    # a generated one is not an improvement.
    new_desc = have_desc or want_desc
    new_kw = have_kw or want_kw
    if new_desc == have_desc and new_kw == have_kw:
        print("  · channel profile already filled in")
        return 0, 0

    if not have_desc:
        print(f"  {'✎' if apply else '→'} description: EMPTY → "
              f"{len(want_desc)} chars")
        for line in want_desc.splitlines()[:3]:
            if line.strip():
                print(f"        {line}")
    if not have_kw:
        print(f"  {'✎' if apply else '→'} keywords: EMPTY → {want_kw}")

    if apply:
        body = {"id": ch["id"], "brandingSettings": {
            "channel": {**cur, "description": new_desc, "keywords": new_kw}}}
        try:
            yt.channels().update(part="brandingSettings", body=body).execute()
        except Exception as e:
            print(f"     ✗ failed: {type(e).__name__}: {str(e)[:160]}")
            return 0, 0
    return 1, CHANNEL_UPDATE_UNITS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--channel", default=None, help="one channel (default: all)")
    ap.add_argument("--videos-only", action="store_true")
    ap.add_argument("--channel-only", action="store_true")
    ap.add_argument("--reserve", type=int, default=DEFAULT_RESERVE,
                    help=f"units to leave for uploads (default {DEFAULT_RESERVE})")
    a = ap.parse_args()

    slugs = ([a.channel] if a.channel
             else [c["slug"] for c in _paths.active_channels()])
    budget = None
    if a.apply:
        budget = [quota_left(a.reserve)]
        print(f"quota available for backfill: {budget[0]} units "
              f"({budget[0] // VIDEO_UPDATE_UNITS} videos), "
              f"keeping {a.reserve} in reserve for uploads")
        if budget[0] < VIDEO_UPDATE_UNITS and not a.channel_only:
            print("Nothing to spend today — re-run after the quota resets and "
                  "it picks up where it left off.")
    total, units = 0, 0
    for slug in slugs:
        name = _paths.channel_meta(slug).get("name", slug)
        print(f"\n=== {name} ({slug})")
        try:
            yt_auth.set_channel(slug)
            yt = yt_auth.data_api(interactive=False)
        except Exception as e:
            print(f"  ! not connected: {type(e).__name__}: {str(e)[:140]}")
            continue
        if not a.channel_only:
            c, u = backfill_videos(slug, yt, apply=a.apply, budget=budget)
            total += c
            units += u
        if not a.videos_only:
            c, u = backfill_channel(slug, yt, apply=a.apply)
            total += c
            units += u

    print(f"\n{'Applied' if a.apply else 'Would change'} {total} item(s) "
          f"≈ {units} quota units.")
    if not a.apply:
        print("Dry run — nothing was written. Re-run with --apply.")


if __name__ == "__main__":
    main()
