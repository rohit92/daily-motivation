#!/usr/bin/env python3
"""
upload_youtube.py — upload today's video to YouTube automatically.

ONE-TIME SETUP (free, ~5 min) — this is the only part you must do:
  1. Go to https://console.cloud.google.com  → same project as your API key.
  2. "APIs & Services" → "Enable APIs" → enable "YouTube Data API v3".
  3. "OAuth consent screen" → External → add yourself as a Test user.
  4. "Credentials" → Create credentials → OAuth client ID → "Desktop app".
  5. Download the JSON, rename it to  client_secret.json , put it in ~/youtube/.
  First run opens a browser once to approve; the token is saved after that.

Then, from the dashboard, click "Auto-upload to YouTube", or:
  python3 upload_youtube.py            # uploads today's mission video
  python3 upload_youtube.py --file output/x.mp4 --title "..." --desc "..."
  python3 upload_youtube.py --file long_form/x.mp4 --longform --thumb x.jpg \
                            --comment "pinned comment text"

It marks the video uploaded and clears the mission. Extras:
  --longform        it's a normal 16:9 video, not a Short
  --thumb PATH      set a custom thumbnail after upload
  --comment TEXT    post this as the first comment (open YouTube once to PIN it
                    — pinning itself isn't possible via the API)
Privacy comes from config.json ("upload_privacy": public/unlisted/private).
"""

import argparse
import json
import os
import sys
from datetime import date

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
_P = _paths.paths(None)
OUTPUT = _P["output"]
LIBRARY = _P["library"]
TODAY = _P["today"]
CONFIG = _P["config"]
CHANNEL = _paths.DEFAULT_CHANNEL


def set_channel(channel):
    global OUTPUT, LIBRARY, TODAY, CONFIG, CHANNEL
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    OUTPUT, LIBRARY, TODAY, CONFIG = P["output"], P["library"], P["today"], P["config"]


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def publish_time():
    """Prime-time publishing: if the daily slot (config post_time_ist, default
    7:30 PM IST) is still ahead, return it as RFC3339 UTC so YouTube holds the
    video private and flips it public at exactly that time. Returns None when
    the slot already passed (or the feature is off) → publish immediately."""
    cfg = load(CONFIG, {}) or {}
    if not cfg.get("schedule_uploads", True):
        return None
    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        ist = ZoneInfo("Asia/Kolkata")
        h, m = map(int, str(cfg.get("post_time_ist", "19:30")).split(":"))
        now = datetime.now(ist)
        slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot - now < timedelta(minutes=10):
            return None                    # it's evening already — go live now
        return slot.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        print(f"⚠ prime-time scheduling unavailable ({e}) — publishing NOW. "
              f"Check config post_time_ist (needs HH:MM).")
        return None


def get_service():
    """Shared login via yt_auth (one consent covers upload + comments +
    thumbnails + analytics for the whole system). Browser consent is only
    attempted in a real terminal — from the dashboard/evening subprocesses
    (output captured, no TTY) it must fail fast, never hang the buttons."""
    import yt_auth
    yt_auth.set_channel(CHANNEL)
    try:
        return yt_auth.data_api(interactive=sys.stdout.isatty())
    except yt_auth.NotConnected as e:
        sys.exit(f"✗ {e}")


def upload(path, title, description, thumb=None, comment=None, longform=False,
           publish_at=None):
    from googleapiclient.http import MediaFileUpload
    privacy = load(CONFIG, {}).get("upload_privacy", "public")
    yt = get_service()
    status_body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:      # YouTube requires private + publishAt for scheduling
        status_body = {"privacyStatus": "private", "publishAt": publish_at,
                       "selfDeclaredMadeForKids": False}
    body = {
        "snippet": {"title": title[:100], "description": description,
                    "categoryId": "22"},
        "status": status_body,
    }
    media = MediaFileUpload(path, chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    print(f"Uploading {os.path.basename(path)} "
          f"({'scheduled' if publish_at else privacy})…")
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
    vid = resp["id"]
    url = (f"https://youtube.com/watch?v={vid}" if longform
           else f"https://youtube.com/shorts/{vid}")
    print(f"✓ Uploaded: {url}")
    if publish_at:
        slot = load(CONFIG, {}).get("post_time_ist", "19:30")
        print(f"✓ Scheduled — YouTube publishes it at your prime time "
              f"({slot} IST) automatically.")

    if thumb and os.path.exists(thumb):
        try:
            yt.thumbnails().set(videoId=vid,
                                media_body=MediaFileUpload(thumb)).execute()
            print("✓ Thumbnail set")
        except Exception as e:
            print(f"· Thumbnail skipped ({e})")

    if comment and publish_at:
        print("· First comment waits until the video is live — tomorrow's "
              "🌇 evening click (or 📌 Pin questions) posts it.")
    elif comment:
        try:
            yt.commentThreads().insert(
                part="snippet",
                body={"snippet": {"videoId": vid, "topLevelComment": {
                    "snippet": {"textOriginal": comment}}}}).execute()
            print("✓ First comment posted — open the video once and tap ⋮ → Pin.")
        except Exception as e:
            print(f"· Comment skipped ({e}) — post it manually from the mission card.")
    return vid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--title")
    ap.add_argument("--desc")
    ap.add_argument("--thumb", help="thumbnail image to set after upload")
    ap.add_argument("--comment", help="post as the first comment (pin it on YouTube)")
    ap.add_argument("--longform", action="store_true", help="normal 16:9 video, not a Short")
    ap.add_argument("--now", action="store_true",
                    help="publish immediately (skip prime-time scheduling)")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)

    thumb, comment = a.thumb, a.comment
    if a.file:
        path, title, desc = a.file, a.title or "Motivation", a.desc or ""
        used_mission = False
    else:
        m = load(TODAY)
        if not m or m.get("date") != date.today().isoformat():
            sys.exit("No mission for today. Prepare one in the dashboard first.")
        path = os.path.join(OUTPUT, m["file"])
        title, desc, used_mission = m["title"], m["description"], True
        comment = comment or m.get("pin_comment")

    if not os.path.exists(path):
        sys.exit(f"Video not found: {path}")

    # the daily Short goes out at prime time; --file uploads publish right away
    publish_at = None if (a.now or not used_mission) else publish_time()
    upload(path, title, desc, thumb=thumb, comment=comment, longform=a.longform,
           publish_at=publish_at)

    # mark uploaded + clear today's mission + stamp the day (double-post guard)
    if used_mission:
        lib = load(LIBRARY, {"videos": {}})
        base = os.path.basename(path).replace("_toon", "")
        for name in (os.path.basename(path), base):
            if name in lib["videos"]:
                lib["videos"][name]["status"] = "uploaded"
        lib["last_upload_date"] = date.today().isoformat()
        json.dump(lib, open(LIBRARY, "w"), indent=2)
        if os.path.exists(TODAY):
            os.remove(TODAY)

    # event-driven auto-replenish: right after every upload, kick a DETACHED job
    # that refreshes trends and buffers the NEXT video for every channel, so the
    # pipeline is always one ahead and never waits for the morning schedule.
    if load(CONFIG, {}).get("prepare_next_on_upload", True):
        try:
            import subprocess
            here = os.path.dirname(os.path.abspath(__file__))
            env = {**os.environ,
                   "PATH": os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin"}
            subprocess.Popen([sys.executable, os.path.join(here, "pilot.py"), "--prepare-next"],
                             cwd=here, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("↻ Trend-scanning + building the next video in the background.")
        except Exception:
            pass
    print("Done. (Still post to Instagram Reels + reply to comments!)")


if __name__ == "__main__":
    main()
