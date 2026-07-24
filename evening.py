#!/usr/bin/env python3
"""
evening.py — the WHOLE evening routine in one click (the 🌇 button).

Runs, in order, everything that used to be 5 separate steps:
  1. Sync real channel numbers + comment inbox   (channel_stats.py)
  2. Sync retention analytics                     (analytics.py --sync)
  3. Post question-comments where missing         (channel_control.py --apply-pins)
  4. Upload today's video — builds one first if needed; goes live at
     prime time (7:30 PM IST) automatically       (pilot.py + upload_youtube.py)
  5. Print a short human checklist of the 2–3 things only a human can do
     (pin on the phone, Instagram Reel, reply to comments).

Double-post protection: if a video already went out today (library
last_upload_date, or the live channel shows a post today), it will NOT
build or upload another one. One video per day, always.

  python3 evening.py
"""

import json
import os
import subprocess
import sys
from datetime import date

import netcfg
import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNEL = _paths.DEFAULT_CHANNEL
_P = _paths.paths(None)
LIBRARY = _P["library"]
TODAY = _P["today"]
OUTPUT = _P["output"]
CONFIG = _P["config"]
TOKEN = _P["yt_token"]
CLIENT_SECRET = _P["client_secret"]
PY = sys.executable
ENV = {**os.environ, "PATH": os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin",
       **netcfg.proxy_env()}

# Child scripts that accept --channel (evening passes the active channel through).
_CHANNEL_AWARE = {"channel_stats.py", "analytics.py", "channel_control.py",
                  "pilot.py", "upload_youtube.py"}


def set_channel(channel):
    global CHANNEL, LIBRARY, TODAY, OUTPUT, CONFIG, TOKEN
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    LIBRARY, TODAY, OUTPUT, CONFIG, TOKEN = (P["library"], P["today"],
                                             P["output"], P["config"], P["yt_token"])


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def run(label, *cmd):
    print(f"→ {label}…", flush=True)
    full = [PY, *cmd]
    if cmd and cmd[0] in _CHANNEL_AWARE:
        full += ["--channel", CHANNEL]
    r = subprocess.run(full, cwd=HERE, env=ENV, capture_output=True, text=True)
    out = (r.stdout or r.stderr or "").strip()
    for ln in out.splitlines()[-3:]:
        print(f"   {ln}", flush=True)
    return r.returncode == 0, out


def connected():
    return os.path.exists(CLIENT_SECRET) and os.path.exists(TOKEN)


def queue_active(cfg):
    """True while the user's hand-scheduled YouTube queue still posts daily.
    A hand-edited non-ISO date must fail LOUD, not silently block uploads
    forever (or silently allow a double-post)."""
    q = str(cfg.get("queue_until") or "").strip()
    if not q:
        return False
    try:
        return date.today() <= date.fromisoformat(q)
    except ValueError:
        print(f"⚠ config queue_until '{q}' is not YYYY-MM-DD — ignoring it.",
              flush=True)
        return False


def posted_today(lib):
    """True if today's video already went out (never double-post)."""
    if lib.get("last_upload_date") == date.today().isoformat():
        return True
    try:
        import progress
        live = (lib.get("channel", {}) or {}).get("live_videos") or []
        _, days_since = progress.streak_info(live)
        return days_since == 0
    except Exception:
        return False


def main():
    import argparse
    ap = argparse.ArgumentParser()
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)

    done, todo = [], []
    meta = _paths.channel_meta(CHANNEL)
    print(f"🌇 Evening routine — {meta.get('name', CHANNEL)} — sit back.\n", flush=True)

    # 1–2. fresh numbers first, so every later decision uses today's truth
    ok, _ = run("Syncing your real channel numbers", "channel_stats.py")
    if ok:
        done.append("Channel stats + comment inbox refreshed")
    run("Syncing retention analytics", "analytics.py", "--sync")

    # 3. question-comments on any video that lacks one (0 new = nothing to do)
    if connected():
        ok, out = run("Posting question-comments where missing",
                      "channel_control.py", "--apply-pins")
        if ok:
            done.append("Question-comment(s) posted")
            todo.append("Phone: open the new comment → ⋮ → Pin it")
    else:
        todo.append("Google not connected — do the one-time connect in Settings")

    # 4. today's video — with the one-per-day guard
    lib = load(LIBRARY, {"videos": {}}) or {"videos": {}}
    cfg = load(CONFIG, {}) or {}
    if queue_active(cfg):
        done.append(f"Your hand-scheduled queue covers today (through "
                    f"{cfg.get('queue_until')}) — no extra upload, one video per day")
    elif posted_today(lib):
        done.append("Today's video is already out — one per day, no double-post")
    else:
        m = load(TODAY)
        fresh = (m and m.get("date") == date.today().isoformat()
                 and m.get("file")
                 and os.path.exists(os.path.join(OUTPUT, m["file"])))
        if not fresh:
            ok, _ = run("No usable video for today — asking the Pilot to build "
                        "one (a minute or two)", "pilot.py")
            m = load(TODAY)
            fresh = (m and m.get("date") == date.today().isoformat()
                     and m.get("file")
                     and os.path.exists(os.path.join(OUTPUT, m["file"])))
        if fresh and connected():
            ok, _ = run("Uploading today's video (title, description, "
                        "prime-time schedule — all handled)",
                        "upload_youtube.py")
            if ok:
                done.append("Today's video uploaded — YouTube publishes it "
                            "at 7:30 PM IST (or it's live now if it's evening)")
                todo.append("AirDrop the video to your phone → post to "
                            "Instagram Reels (📂 Reveal file on the Today tab)")
            else:
                todo.append("Upload failed — use ⤴ on the Today tab and "
                            "check the console")
        elif fresh:
            todo.append("Upload today's video manually (Today tab → "
                        "⬆ Open YouTube upload)")
        else:
            todo.append("The Pilot couldn't prepare a video — open the Today "
                        "tab and click 🚀 Prepare today's video")

    # 5. the human layer — the part that makes the algorithm trust you
    inbox = (lib.get("channel", {}) or {}).get("recent_comments") or []
    if inbox:
        todo.append(f"Reply to {len(inbox)} comment(s) — Uploaded tab → "
                    "💡 Draft my reply → ↩ Send")
    else:
        todo.append("Inbox empty → leave real comments on 3–5 big motivation "
                    "channels (free discovery)")

    print("\n" + "=" * 52)
    print("  EVENING SUMMARY")
    print("=" * 52)
    for d in done:
        print(f"  ✓ {d}")
    print("\n  Left for you (the human touch):")
    for i, t in enumerate(todo, 1):
        print(f"  {i}. {t}")
    print("=" * 52)


if __name__ == "__main__":
    main()
