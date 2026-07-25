#!/usr/bin/env python3
"""
reconcile.py — make library.json tell the truth about what is really on YouTube.

The library used to record only status="uploaded", with no YouTube id. That let
two separate lies survive:

  * A video whose upload died mid-flight was still marked "uploaded", so the
    system never retried it and the Short simply never existed. (education
    03_c015 and facts 03_c014 were both in this state.)
  * Stats were matched back by TITLE, so when the duplicate-script bug shipped
    two videos with near-identical titles, the one that never uploaded inherited
    the other's view count — 03_c015 claimed 55 views on a channel with 47.

This walks every channel, asks YouTube what actually exists, and repairs the
drift. Videos that are not really live go back to status="ready" so the normal
pipeline picks them up and posts them.

  python3 reconcile.py             # report only
  python3 reconcile.py --fix       # apply the corrections
  python3 reconcile.py --channel facts --fix
"""
import argparse
import json
import os
import sys

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
# YouTube says a video is fine only when it has finished processing. A Short
# stuck at "uploaded" with a zero-length duration is a truncated transfer that
# will never become watchable, no matter how long you wait.
HEALTHY = "processed"
DEAD_DURATION = "P0D"


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def live_videos(slug):
    """Every video actually on the channel: {video_id: {...}} — or None if the
    API can't be reached (we must NOT 'repair' anything on a failed lookup)."""
    import yt_auth
    yt_auth.set_channel(slug)
    yt = yt_auth.data_api(interactive=False)
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
        r = yt.videos().list(part="snippet,status,contentDetails",
                             id=",".join(ids[i:i + 50])).execute()
        for v in r.get("items", []):
            dur = v["contentDetails"].get("duration", "")
            out[v["id"]] = {
                "title": v["snippet"]["title"],
                "upload_status": v["status"]["uploadStatus"],
                "privacy": v["status"]["privacyStatus"],
                "duration": dur,
                "healthy": (v["status"]["uploadStatus"] == HEALTHY
                            and dur != DEAD_DURATION),
            }
    return out


def reconcile_channel(slug, fix=False):
    P = _paths.paths(slug)
    lib = load(P["library"], {"videos": {}}) or {"videos": {}}
    videos = lib.get("videos") or {}

    print(f"\n=== {slug}")
    try:
        live = live_videos(slug)
    except Exception as e:
        print(f"  ! could not read YouTube ({type(e).__name__}: {str(e)[:120]}) "
              f"— skipping, nothing changed")
        return 0
    print(f"  {len(live)} video(s) live on the channel")

    by_title = {}
    for vid, v in live.items():
        by_title.setdefault(v["title"], []).append(vid)

    def healthy_sibling(name, entry):
        """Another library entry built from the SAME script that IS live and
        healthy. If one exists, this entry is a leftover of the duplicate-build
        bug — re-uploading it would put the same script on the channel twice,
        which is the reused-content problem we are trying to get rid of."""
        for other, o in videos.items():
            if other == name or o.get("id") != entry.get("id"):
                continue
            ov = o.get("video_id")
            if ov and (live.get(ov) or {}).get("healthy"):
                return other, ov
            cands = by_title.get(o.get("title", ""), [])
            for c in cands:
                if live[c]["healthy"]:
                    return other, c
        return None, None

    def retire(name, entry, reason):
        """Not really live. Either it duplicates a live video (dead end) or it
        genuinely needs posting (back into the queue)."""
        sib, sv = healthy_sibling(name, entry)
        if sib:
            print(f"  ⊘ {name}: {reason}, and script '{entry.get('id')}' is "
                  f"already live as {sib} ({sv}) → marking duplicate, will NOT "
                  f"be re-posted")
            if fix:
                entry["status"] = "duplicate"
        else:
            print(f"  ✗ {name}: {reason} → re-queueing for upload")
            if fix:
                entry["status"] = "ready"
        if fix:
            entry.pop("video_id", None)
            for k in ("views", "likes", "comments"):
                entry.pop(k, None)          # stats belonged to another video
        return 1 if fix else 0

    claimed, changes = set(), 0
    for name, entry in sorted(videos.items()):
        if entry.get("status") != "uploaded":
            continue
        vid = entry.get("video_id")

        if not vid:
            # Legacy entry: no id was recorded. Adopt one only when exactly one
            # live video carries this exact title AND no sibling took it first.
            cands = [c for c in by_title.get(entry.get("title", ""), [])
                     if c not in claimed]
            if len(cands) == 1:
                vid = cands[0]
                print(f"  · {name}: matched to {vid} by title")
                if fix:
                    entry["video_id"] = vid
                    changes += 1
            else:
                why = ("marked uploaded but no live video has this title"
                       if not cands else
                       f"marked uploaded but {len(cands)} live videos share this title")
                changes += retire(name, entry, why)
                continue

        claimed.add(vid)
        info = live.get(vid)
        if info is None:
            changes += retire(name, entry,
                              f"video_id {vid} is not on the channel (deleted?)")
        elif not info["healthy"]:
            print(f"  ⚠ {name}: {vid} is {info['upload_status']} "
                  f"/ duration {info['duration']} → BROKEN on YouTube. "
                  f"Delete it in Studio, then this re-uploads.")
        else:
            print(f"  ✓ {name}: {vid} live ({info['privacy']}, {info['duration']})")

    orphans = [v for v in live if v not in claimed]
    if orphans:
        print(f"  · {len(orphans)} live video(s) not tracked in the library "
              f"(older uploads) — left alone")

    if fix and changes:
        json.dump(lib, open(P["library"], "w"), indent=2)
        print(f"  → wrote {changes} correction(s) to library.json")
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="apply the corrections")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()

    explicit = "--channel" in sys.argv
    chans = ([{"slug": a.channel}] if explicit else _paths.active_channels())
    total = sum(reconcile_channel(c["slug"], fix=a.fix) for c in chans)
    if not a.fix:
        print("\nReport only. Re-run with --fix to apply.")
    else:
        print(f"\nDone — {total} correction(s) applied.")


if __name__ == "__main__":
    main()
