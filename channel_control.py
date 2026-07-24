#!/usr/bin/env python3
"""
channel_control.py — the system's hands on your real YouTube channel.

Everything the dashboard/assistant can DO to the channel goes through here
(needs the one-time Google connect — dashboard Settings → YouTube connection):

  python3 channel_control.py --apply-pins            # post the engagement
        question as a comment on every live video that doesn't have one yet
        (you still tap ⋮ → Pin on each — the API can't pin)
  python3 channel_control.py --apply-pins --dry-run  # show the plan only
  python3 channel_control.py --reply THREAD_ID --text "..."   # reply to a comment
  python3 channel_control.py --comment VIDEO_ID --text "..."  # comment on a video
  python3 channel_control.py --set-title VIDEO_ID --text "..."
  python3 channel_control.py --set-desc  VIDEO_ID --text "..."

Used by the dashboard buttons; safe to run by hand too. Every action prints
exactly what it did.
"""

import argparse
import json
import os
import sys

import yt_auth
import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARY = _paths.paths(None)["library"]
CHANNEL = _paths.DEFAULT_CHANNEL


def set_channel(channel):
    global LIBRARY, CHANNEL
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    LIBRARY = _paths.paths(CHANNEL)["library"]
    yt_auth.set_channel(CHANNEL)


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save_lib(lib):
    json.dump(lib, open(LIBRARY, "w"), indent=2)


def post_comment(video_id, text, yt=None):
    yt = yt or yt_auth.data_api(interactive=False)
    yt.commentThreads().insert(
        part="snippet",
        body={"snippet": {"videoId": video_id, "topLevelComment": {
            "snippet": {"textOriginal": text}}}}).execute()
    return True


def reply_to(thread_id, text, yt=None):
    """Reply under a viewer's comment (thread id = the top-level comment id)."""
    yt = yt or yt_auth.data_api(interactive=False)
    yt.comments().insert(
        part="snippet",
        body={"snippet": {"parentId": thread_id,
                          "textOriginal": text}}).execute()
    return True


def update_snippet(video_id, title=None, description=None):
    """Change a live video's title/description (fetch-modify-send: the API
    replaces the whole snippet, so we must round-trip the current one)."""
    yt = yt_auth.data_api(interactive=False)
    cur = yt.videos().list(part="snippet", id=video_id).execute()
    items = cur.get("items")
    if not items:
        sys.exit(f"Video {video_id} not found (not yours or deleted).")
    sn = items[0]["snippet"]
    if title:
        sn["title"] = title[:100]
    if description:
        sn["description"] = description
    yt.videos().update(part="snippet",
                       body={"id": video_id, "snippet": sn}).execute()
    return sn["title"]


def pin_question_for(title):
    """Theme-matched engagement question for a live video (same bank the
    Shorts pipeline uses, keyed off the hook)."""
    import metadata
    import progress
    theme = progress._infer_theme(title)
    return metadata.THEME_PINS.get(theme) or metadata.GENERIC_PINS[
        abs(hash(title)) % len(metadata.GENERIC_PINS)]


def apply_pins(dry_run=False):
    """Post the pinned-question comment on every live video that hasn't had
    one yet. Tracked in library.json so it never double-posts."""
    lib = load(LIBRARY, {"videos": {}})
    ch = lib.get("channel", {})
    live = ch.get("live_videos") or []
    if not live:
        sys.exit("No live videos — run 'Sync my stats' first.")
    done = set(ch.get("pins_posted", []))
    todo = [v for v in live if v["id"] not in done]
    if not todo:
        print("✓ Every live video already has its question comment.")
        return
    # auth check up front — no point looping if the connection is missing
    yt = None if dry_run else yt_auth.data_api(interactive=False)
    print(f"{'DRY RUN — would post' if dry_run else 'Posting'} on "
          f"{len(todo)} video(s):\n")
    posted = 0
    for v in todo:
        q = pin_question_for(v["title"])
        head = v["title"].split("#")[0].strip()[:48]
        print(f"  · {head}\n    → {q}")
        if dry_run:
            continue
        try:
            post_comment(v["id"], q, yt)
            done.add(v["id"])
            posted += 1
        except Exception as e:
            print(f"    ✗ failed: {e}")
    if not dry_run:
        ch["pins_posted"] = sorted(done)
        save_lib(lib)
        if posted == 0:
            sys.exit("\n✗ Nothing was posted — see the errors above.")
        print(f"\n✓ Posted {posted} comment(s). Last human step: open each "
              f"video once and tap ⋮ → Pin on your comment.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-pins", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reply", metavar="THREAD_ID")
    ap.add_argument("--comment", metavar="VIDEO_ID")
    ap.add_argument("--set-title", metavar="VIDEO_ID")
    ap.add_argument("--set-desc", metavar="VIDEO_ID")
    ap.add_argument("--text", default="")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)

    try:
        if a.apply_pins:
            apply_pins(dry_run=a.dry_run)
        elif a.reply:
            if not a.text:
                sys.exit("--text required")
            reply_to(a.reply, a.text)
            print("✓ Reply posted.")
        elif a.comment:
            if not a.text:
                sys.exit("--text required")
            post_comment(a.comment, a.text)
            print("✓ Comment posted.")
        elif a.set_title:
            print("✓ Title now:", update_snippet(a.set_title, title=a.text))
        elif a.set_desc:
            update_snippet(a.set_desc, description=a.text)
            print("✓ Description updated.")
        else:
            ap.print_help()
    except yt_auth.NotConnected as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
