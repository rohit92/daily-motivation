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
import http.client
import json
import os
import sys
import time
from datetime import date

import paths as _paths

# Network failures that mean "try that chunk again", not "give up". IOError
# covers socket errors, timeouts and urllib URLError (all OSError subclasses);
# HttpError carries Google's 5xx blips (filtered by RETRIABLE_STATUS below).
try:
    from googleapiclient.errors import HttpError as _HttpError
    RETRIABLE = (IOError, http.client.HTTPException, _HttpError)
except ImportError:                        # library missing → auth fails first
    RETRIABLE = (IOError, http.client.HTTPException)
RETRIABLE_STATUS = {500, 502, 503, 504}   # transient Google-side errors
MAX_RETRIES = 6

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


def publish_time(on_date=None):
    """Prime-time publishing: if the daily slot (config post_time_ist, default
    7:30 PM IST) is still ahead, return it as RFC3339 UTC so YouTube holds the
    video private and flips it public at exactly that time. Returns None when
    the slot already passed (or the feature is off) → publish immediately.

    Pass `on_date` (a datetime.date) to target that day's slot instead of today's
    — that is how a whole week can be uploaded now and released one per day."""
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
        if on_date:
            slot = slot.replace(year=on_date.year, month=on_date.month,
                                day=on_date.day)
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


def _check_accepted(yt, vid):
    """Did YouTube actually ACCEPT the bytes? A truncated upload is reported as
    a successful insert but then sits in 'processing' forever at 0s duration,
    so the Short silently never goes live. Fail loudly instead — the caller
    (autopilot) then alerts you the same evening instead of days later."""
    try:
        r = yt.videos().list(part="status,processingDetails", id=vid).execute()
        items = r.get("items") or []
        if not items:
            print("   ⚠ could not read the video back — check it on YouTube.")
            return
        st = items[0].get("status", {}) or {}
        bad = st.get("rejectionReason") or st.get("failureReason")
        if st.get("uploadStatus") in ("rejected", "failed") or bad:
            raise RuntimeError(
                f"YouTube REJECTED the upload ({bad or st.get('uploadStatus')}). "
                f"The video is not live: https://youtube.com/watch?v={vid}")
        print(f"   ✓ accepted by YouTube (processing: "
              f"{(items[0].get('processingDetails') or {}).get('processingStatus', '?')})")
    except RuntimeError:
        raise
    except Exception as e:                 # verification is best-effort only
        print(f"   · post-upload check skipped ({e})")


def mark_uploaded(library_path, filename, vid, publish_at=None):
    """Record the upload against the library entry, INCLUDING the YouTube id.

    Storing the id is what makes 'uploaded' verifiable. Without it the only link
    back to YouTube was the title, so two videos built from the same script (the
    old duplicate bug) both matched the one live video: each inherited its view
    count, and a video that never actually reached YouTube still read 'uploaded'.
    reconcile.py uses this id to check truth against the API.
    """
    lib = load(library_path, {"videos": {}}) or {"videos": {}}
    base = os.path.basename(filename).replace("_toon", "")
    touched = False
    for name in (os.path.basename(filename), base):
        v = lib.get("videos", {}).get(name)
        if v is not None:
            v["status"] = "uploaded"
            v["video_id"] = vid
            v["uploaded_at"] = date.today().isoformat()
            if publish_at:
                v["publish_at"] = publish_at
            touched = True
    if touched:
        lib["last_upload_date"] = date.today().isoformat()
        json.dump(lib, open(library_path, "w"), indent=2)
    return touched


def _seo_category():
    """This channel's YouTube category, falling back to the old hardcoded 22."""
    try:
        import seo
        return seo.category_id(CHANNEL)
    except Exception:
        return "22"        # a bad SEO lookup must never block an upload


def _seo_tags(theme, longform, title):
    try:
        import seo
        return seo.tags_for(CHANNEL, theme=theme, longform=longform, title=title)
    except Exception:
        return []


def upload(path, title, description, thumb=None, comment=None, longform=False,
           publish_at=None, theme=None):
    from googleapiclient.http import MediaFileUpload
    privacy = load(CONFIG, {}).get("upload_privacy", "public")
    yt = get_service()
    status_body = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:      # YouTube requires private + publishAt for scheduling
        status_body = {"privacyStatus": "private", "publishAt": publish_at,
                       "selfDeclaredMadeForKids": False}
    # Tags and category were the two things missing from every upload this
    # system has ever made: no `tags` key at all, and categoryId pinned to 22
    # ("People & Blogs") even on the English and science channels. That is why
    # search accounted for ~1% of views — there was nothing to search against.
    snippet = {"title": title[:100], "description": description,
               "categoryId": _seo_category(), "defaultLanguage": "en",
               "defaultAudioLanguage": "en"}
    tags = _seo_tags(theme, longform, title)
    if tags:
        snippet["tags"] = tags
    body = {"snippet": snippet, "status": status_body}
    # 4 MB chunks make the upload GENUINELY resumable: a dropped connection
    # retries just that chunk instead of restarting — or worse, half-delivering
    # the file. chunksize=-1 pushed the whole video in a single request, which
    # is how a Short ended up stuck in YouTube "processing" at 0s duration
    # after a flaky upload (video adANN4-nIjg on the facts channel).
    media = MediaFileUpload(path, chunksize=4 * 1024 * 1024, resumable=True,
                            mimetype="video/*")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Uploading {os.path.basename(path)} ({size_mb:.1f} MB, "
          f"{'scheduled' if publish_at else privacy})…")
    print(f"   · category {snippet['categoryId']}, {len(tags)} tag(s)"
          + (f": {', '.join(tags[:5])}…" if tags else " — NONE"))
    resp, tries = None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                print(f"   … {int(status.progress() * 100)}%")
            tries = 0                      # a good chunk resets the retry budget
        except RETRIABLE as e:
            # transient: server hiccup, dropped socket, proxy blip. Resume.
            code = getattr(getattr(e, "resp", None), "status", None)
            if code is not None and code not in RETRIABLE_STATUS:
                raise                      # a real API error (quota, auth, bad file)
            tries += 1
            if tries > MAX_RETRIES:
                raise RuntimeError(
                    f"upload failed after {MAX_RETRIES} retries: {e}") from e
            wait = min(2 ** tries, 30)
            print(f"   · network hiccup ({type(e).__name__}) — resuming in "
                  f"{wait}s [{tries}/{MAX_RETRIES}]")
            time.sleep(wait)
    vid = resp["id"]
    url = (f"https://youtube.com/watch?v={vid}" if longform
           else f"https://youtube.com/shorts/{vid}")
    print(f"✓ Uploaded: {url}")
    _check_accepted(yt, vid)
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
    ap.add_argument("--publish-at", dest="publish_at", metavar="YYYY-MM-DD",
                    help="go public at this date's prime-time slot (upload now, "
                         "release later)")
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
    if a.publish_at:
        on = date.fromisoformat(a.publish_at)
        publish_at = publish_time(on_date=on)
        if not publish_at:
            sys.exit(f"✗ {on}'s slot has already passed — nothing to schedule.")
    else:
        publish_at = None if (a.now or not used_mission) else publish_time()
    vid = upload(path, title, desc, thumb=thumb, comment=comment,
                 longform=a.longform, publish_at=publish_at)

    # mark uploaded + clear today's mission + stamp the day (double-post guard)
    mark_uploaded(LIBRARY, path, vid, publish_at)
    if used_mission and os.path.exists(TODAY):
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
