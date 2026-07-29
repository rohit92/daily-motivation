#!/usr/bin/env python3
"""
pilot.py — the AI Pilot. One command prepares TODAY's single best video and
tells you exactly what to do with it.

What it does (in order):
  1. Scans your channel to see what you've already uploaded (auto, if online).
  2. Picks today's best topic — your winning theme, boosted by what's trending.
  3. Generates ONE optimized video for it (bold hook, right length, music).
  4. Writes the title / description / IG caption.
  5. Writes today.json — your mission for the day, shown big on the dashboard.

  python3 pilot.py            # prepare today's video + mission
  python3 pilot.py --status   # just print today's mission
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date

import netcfg
import paths as _paths
import script_composer as sc

HERE = os.path.dirname(os.path.abspath(__file__))
# Per-channel paths, resolved in prepare()/print_status() from --channel.
# Defaults below keep motivation working if called without a channel.
_P = _paths.paths(None)
LIBRARY = _P["library"]
TODAY = _P["today"]
TRENDS = _P["trends"]
CONFIG = _P["config"]
CHANNEL = _paths.DEFAULT_CHANNEL
# Use THIS interpreter for child scripts (it has PIL/edge-tts/etc.), and only
# APPEND Homebrew for ffmpeg/ollama. Prepending Homebrew would let its python3
# (no PIL) shadow ours and break make_video.py — that was the "generate does
# nothing" bug.
PY = sys.executable
ENV = {**os.environ, "PATH": os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin",
       **netcfg.proxy_env()}

# Hooks the retention data PROVED die: too-generic openers whose first 3 seconds
# don't open a curiosity gap, so the Shorts feed never distributes them
# (41-52% retention, 2-view videos). Never ship one as the day's post — skip it
# and use the next ready short, or generate a fresh one. Source: profile.json.
WEAK_HOOK_PATTERNS = (
    "one decision away",
    "champions are made",
    "where champions",
)


def weak_hook(title):
    t = (title or "").lower()
    return any(p in t for p in WEAK_HOOK_PATTERNS)


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def set_channel(channel):
    """Point this module's data paths at `channel` and tell script_composer too."""
    global LIBRARY, TODAY, TRENDS, CONFIG, CHANNEL, OUTPUT_DIR
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    LIBRARY, TODAY, TRENDS, CONFIG = P["library"], P["today"], P["trends"], P["config"]
    OUTPUT_DIR = P["output"]
    sc.set_channel(CHANNEL)


OUTPUT_DIR = _P["output"]


# Child scripts that understand --channel (per-channel data). character.py
# operates on shared data and does NOT take --channel. trend_scan.py does now:
# it searches this channel's niche and writes this channel's report.
_CHANNEL_AWARE = {"channel_stats.py", "make_video.py", "metadata.py",
                  "trend_scan.py",
                  "storyteller.py", "make_longform.py", "analytics.py",
                  "channel_control.py", "upload_youtube.py"}


def run(cmd):
    """Run a child script; pass --channel to the scripts that understand it."""
    full = [PY, *cmd]
    if cmd and cmd[0] in _CHANNEL_AWARE:
        full += ["--channel", CHANNEL]
    return subprocess.run(full, cwd=HERE, env=ENV, capture_output=True, text=True)


def choose_theme():
    """Best topic = your best-performing theme, else the top trending theme."""
    lib = load(LIBRARY, {"videos": {}})
    scored = {}
    for v in lib["videos"].values():
        th = v.get("theme")
        if th and v.get("views", 0) > 0:
            scored[th] = scored.get(th, 0) + v["views"]
    if scored:
        return max(scored, key=scored.get), "your best-performing style"
    weights = sc.theme_weights()
    top = max(weights, key=weights.get)
    reason = "this week's top trend" if weights[top] > 1.0 else "a strong evergreen topic"
    return top, reason


def best_post_time():
    tr = load(TRENDS, {})
    hours = tr.get("best_hours_utc") or []
    if hours:
        ist = (hours[0] + 5.5) % 24            # UTC -> IST
        h = int(ist) % 12 or 12
        ampm = "AM" if int(ist) < 12 else "PM"
        return f"{h}:{'30' if ist % 1 else '00'} {ampm}"
    return "8:00 PM"


def prepare():
    print("AI Pilot: preparing today's video…\n")

    # 1. detect what's already uploaded (best-effort; needs internet + API key)
    r = run(["channel_stats.py"])
    if r.returncode == 0:
        print("  ✓ scanned your channel (uploaded videos detected)")
    else:
        print("  · channel scan skipped (offline or key missing) — continuing")

    # 1b. a ready Short cut from Sunday's story takes priority — it funnels
    #     viewers to the full story (nothing to generate, it's already built)
    lib = load(LIBRARY, {"videos": {}})
    for name, v in sorted(lib["videos"].items(), key=lambda kv: kv[1].get("seq", 0)):
        # use any READY buffered video first (built ahead by prepare_next after
        # your last upload) before generating a fresh one — pipeline stays ahead.
        if not (v.get("status") == "ready"
                and os.path.exists(os.path.join(OUTPUT_DIR, name))):
            continue
        if weak_hook(v.get("title")):
            print(f"  · skipping ready video {name}: weak hook the retention "
                  f"data says dies — {(v.get('title') or '')[:44]}")
            continue
        is_story = str(v.get("id", "")).startswith("st")
        mission = {
            "date": date.today().isoformat(),
            "file": name, "id": v["id"],
            "theme": v.get("theme", "story" if is_story else ""),
            "reason": ("A beat from this week's story — it pulls viewers to the full video."
                       if is_story else
                       "A fresh video from your buffer — prepared right after your last upload."),
            "post_time": best_post_time(),
            "title": v["title"], "description": v["description"],
            "ig_caption": v["ig_caption"],
            "pin_comment": v.get("pin_comment", ""),
            "steps": [
                f"Upload to YouTube as a Short at {best_post_time()} (your local time).",
                "Post the same file to Instagram Reels.",
                "Post the pinned comment below, then pin it (⋮ → Pin).",
                "Reply to every comment in the first hour — this is the #1 growth signal.",
            ],
        }
        json.dump(mission, open(TODAY, "w"), indent=2)
        print(f"  ✓ using a ready buffered video as today's: {name}")
        print_status(mission)
        return

    # 2. nothing buffered → we really are building one. Only NOW is it worth
    #    scanning the internet for fresh trends (it takes ~a minute). Doing this
    #    before the buffer check made "Prepare" feel like it was rendering a new
    #    video every time, when usually it just promotes one that already exists.
    cfg = load(CONFIG, {})
    stale = (not os.path.exists(TRENDS) or
             time.time() - os.path.getmtime(TRENDS) > 3 * 86400)
    if cfg.get("scan_on_generate", True) or stale:
        print("  · scanning the internet for this week's trends…")
        run(["trend_scan.py", "--region", "US"])

    # 3. choose today's topic
    theme, reason = choose_theme()
    print(f"  ✓ today's topic: {theme}  ({reason})")

    # 3. write one script in that theme, then make the video
    try:
        import ai_brain
        # Only use the AI path when the channel explicitly opts in (ai_scripts).
        # Otherwise the curated per-channel bank (script_composer) is used, which
        # writes to THIS channel's content.json so make_video can find the id.
        # ai_brain currently writes to the top-level content.json, so enabling it
        # without that fix caused "Script id ai### not found" and failed builds.
        if load(CONFIG, {}).get("ai_scripts") and ai_brain.has_ai():
            s = ai_brain.write_scripts(1)
            item = ai_brain.append_scripts(s)[0] if s else sc.compose(1, prefer=theme)[0]
        else:
            item = sc.compose(1, prefer=theme)[0]
    except Exception:
        item = sc.compose(1, prefer=theme)[0]

    print(f"  ✓ script ready ({item['id']}). Making the video (a minute or two)…")
    r = run(["make_video.py", "--id", item["id"]])
    if r.returncode != 0:
        print("  ✗ video generation failed:\n" + (r.stderr or r.stdout)[-400:])
        return
    run(["metadata.py", "--sync"])

    # 4. locate today's finished video in the library
    lib = load(LIBRARY, {"videos": {}})
    entry = None
    for name, v in lib["videos"].items():
        if v["id"] == item["id"]:
            entry = dict(v); entry["file"] = name
            break
    if not entry:
        print("  ✗ could not find the finished video in the library")
        return

    # optional: overlay the animated stick-figure narrator
    if load(CONFIG, {}).get("character"):
        print("  ✓ adding the stick-figure narrator…")
        r = run(["character.py", os.path.join(OUTPUT_DIR, entry["file"])])
        toon = entry["file"].rsplit(".", 1)[0] + "_toon.mp4"
        if r.returncode == 0 and os.path.exists(os.path.join(OUTPUT_DIR, toon)):
            entry["file"] = toon

    mission = {
        "date": date.today().isoformat(),
        "file": entry["file"], "id": item["id"], "theme": theme,
        "reason": f"Leaning into '{theme}' — {reason}.",
        "post_time": best_post_time(),
        "title": entry["title"], "description": entry["description"],
        "ig_caption": entry["ig_caption"],
        "pin_comment": entry.get("pin_comment", ""),
        "steps": [
            f"Upload to YouTube as a Short at {best_post_time()} (your local time).",
            "Post the same file to Instagram Reels.",
            "Post the pinned comment below, then pin it (⋮ → Pin).",
            "Reply to every comment in the first hour — this is the #1 growth signal.",
        ],
    }
    json.dump(mission, open(TODAY, "w"), indent=2)
    print_status(mission)


def prepare_next():
    """Event-driven top-up (runs right after every upload): refresh trends, then
    make sure EVERY active channel has one fresh video BUFFERED (status 'ready').
    The next daily run picks up the buffer instead of generating from scratch, so
    the pipeline is always one video ahead. Idempotent — a channel that already
    has a ready buffer is skipped, so it never piles up or loops."""
    print("Preparing the next video for all channels (trend-scan + build)…\n")
    made = []
    for c in _paths.active_channels():
        set_channel(c["slug"])
        # Scan inside the loop now: each channel searches its own niche, so a
        # single global scan can no longer steer all three by motivation.
        run(["trend_scan.py", "--region", "US"])
        lib = load(LIBRARY, {"videos": {}}) or {"videos": {}}
        buffered = [n for n, v in (lib.get("videos") or {}).items()
                    if v.get("status") == "ready" and not weak_hook(v.get("title"))
                    and os.path.exists(os.path.join(OUTPUT_DIR, n))]
        if buffered:
            print(f"  · {c['slug']}: already has {len(buffered)} ready — skip")
            continue
        theme, _ = choose_theme()
        try:
            import ai_brain
            if load(CONFIG, {}).get("ai_scripts") and ai_brain.has_ai():
                s = ai_brain.write_scripts(1)
                item = ai_brain.append_scripts(s)[0] if s else sc.compose(1, prefer=theme)[0]
            else:
                item = sc.compose(1, prefer=theme)[0]
        except Exception:
            item = sc.compose(1, prefer=theme)[0]
        r = run(["make_video.py", "--id", item["id"]])
        if r.returncode == 0:
            run(["metadata.py", "--sync"])
            made.append(c["slug"])
            print(f"  ✓ {c['slug']}: buffered next video ({item['id']})")
        else:
            print(f"  ✗ {c['slug']}: build failed")
    print(f"\nDone. Buffered next video for: {', '.join(made) if made else 'none (all already had one)'}")


def print_status(m=None):
    m = m or load(TODAY)
    if not m or m.get("date") != date.today().isoformat():
        print("No mission prepared for today. Run:  python3 pilot.py")
        return
    print("\n" + "=" * 58)
    print("  TODAY'S MISSION  ·  " + m["date"])
    print("=" * 58)
    print(f"  Video : {m['file']}")
    print(f"  Why   : {m['reason']}")
    print(f"  Post  : {m['post_time']}")
    print(f"\n  Title : {m['title']}")
    print("\n  Do this:")
    for i, s in enumerate(m["steps"], 1):
        print(f"    {i}. {s}")
    print("=" * 58)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--prepare-next", dest="prepare_next", action="store_true",
                    help="event-driven: trend-scan + buffer the next video for every channel")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)
    if a.prepare_next:
        prepare_next()
    elif a.status:
        print_status()
    else:
        prepare()


if __name__ == "__main__":
    main()
