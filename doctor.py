#!/usr/bin/env python3
"""
doctor.py — one-command health check. Run this any time something feels off,
or once a month. It verifies every part of the system and tells you the exact
fix for anything broken.

  python3 doctor.py
"""

import glob
import json
import os
import shutil
import subprocess
import sys

import paths as _paths
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OK, WARN, BAD = "✓", "⚠", "✗"
issues = {"bad": 0, "warn": 0}


def line(sym, msg, fix=""):
    print(f" {sym}  {msg}")
    if fix:
        print(f"      → {fix}")
    if sym == BAD:
        issues["bad"] += 1
    elif sym == WARN:
        issues["warn"] += 1


def check_binaries():
    print("\nTools:")
    for b, fix in [("ffmpeg", "brew install ffmpeg"),
                   ("ffprobe", "brew install ffmpeg"),
                   ("say", "built into macOS — should always exist")]:
        if shutil.which(b):
            line(OK, f"{b} found")
        else:
            line(BAD, f"{b} missing", fix)


def check_modules():
    print("\nPython packages:")
    mods = {"PIL": "python3 -m pip install Pillow",
            "flask": "python3 -m pip install flask",
            "numpy": "python3 -m pip install numpy",
            "edge_tts": "python3 -m pip install edge-tts",
            "piper": "python3 -m pip install piper-tts"}
    for m, fix in mods.items():
        try:
            __import__(m)
            line(OK, f"{m} installed")
        except Exception:
            crit = m in ("PIL", "flask")
            line(BAD if crit else WARN, f"{m} not importable", fix)


def check_assets():
    print("\nAssets:")
    vm = os.path.join(HERE, "assets", "voices", "en_US-ryan-high.onnx")
    line(OK if os.path.exists(vm) else WARN,
         "Piper voice model (offline fallback voice)",
         "" if os.path.exists(vm) else "re-download the model per README (edge-tts still works online)")

    bgs = glob.glob(os.path.join(HERE, "assets", "backgrounds", "*"))
    if len(bgs) >= 10:
        line(OK, f"{len(bgs)} background images")
    elif bgs:
        line(WARN, f"only {len(bgs)} backgrounds", "python3 fetch_backgrounds.py --count 20")
    else:
        line(BAD, "no backgrounds", "python3 fetch_backgrounds.py --count 20")

    music = glob.glob(os.path.join(HERE, "assets", "music", "*"))
    line(OK if music else WARN, f"{len(music)} music beds",
         "" if music else "python3 make_music.py (optional)")

    for p in ["assets/brand/logo.png", "assets/brand/banner.png",
              "product/discipline_ebook.pdf"]:
        line(OK if os.path.exists(os.path.join(HERE, p)) else WARN, p,
             "" if os.path.exists(os.path.join(HERE, p)) else "python3 make_assets.py")


def check_content():
    print("\nContent pipeline:")
    try:
        out = subprocess.run([sys.executable, "script_composer.py", "--stats"],
                             cwd=HERE, capture_output=True, text=True).stdout
        unused = int(out.splitlines()[0].split(":")[1])
        combos = int(out.splitlines()[1].split(":")[1])
        line(OK if unused >= 3 else WARN, f"{unused} scripts queued (unused)",
             "" if unused >= 3 else "click Generate, or python3 script_composer.py --add 7")
        if combos > 60:
            line(OK, f"{combos} fresh script combos available (~{combos//30} months)")
        elif combos > 0:
            line(WARN, f"only {combos} combos left", "refresh the script bank soon")
        else:
            line(BAD, "script bank exhausted", "add a fresh script bank")
    except Exception as e:
        line(BAD, f"composer not runnable: {e}")


def check_voice():
    print("\nVoice (critical path):")
    try:
        import piper  # noqa
        vm = os.path.join(HERE, "assets", "voices", "en_US-ryan-high.onnx")
        if os.path.exists(vm):
            test = os.path.join(HERE, ".work", "doctor_voice.wav")
            os.makedirs(os.path.dirname(test), exist_ok=True)
            r = subprocess.run([sys.executable, "-m", "piper", "--model", vm,
                                "--output_file", test], input="test", text=True,
                               capture_output=True)
            if r.returncode == 0 and os.path.getsize(test) > 1000:
                line(OK, "offline voice (Piper) works — you can generate even with no internet")
                os.remove(test)
            else:
                line(WARN, "Piper didn't produce audio", "edge-tts online voice is still primary")
        else:
            line(WARN, "no Piper model; you rely on edge-tts (needs internet)")
    except Exception:
        line(WARN, "Piper not available; edge-tts (online) is your only voice")


def check_schedule():
    print("\nSchedule & tracking:")
    sc = os.path.join(HERE, "schedule.csv")
    if os.path.exists(sc):
        import csv
        rows = list(csv.DictReader(open(sc)))
        last = rows[-1]["date"]
        today = date.today().isoformat()
        if today > last:
            line(WARN, f"schedule ended {last}", "python3 make_schedule.py --start "
                 + today)
        else:
            covered = sum(1 for r in rows if r["date"] >= today)
            line(OK, f"schedule covers {covered} more days (through {last})")
    else:
        line(WARN, "no schedule.csv", "python3 make_schedule.py")

    # library.json and output/ moved under channels/<slug>/ when the project
    # went multichannel. Checking the old root paths meant this reported "no
    # library.json — run metadata.py --sync" on every single run, against three
    # libraries that were all present and correct. A health check that cries
    # wolf every time is worse than no health check.
    for ch in _paths.load_registry():
        slug = ch["slug"]
        P = _paths.paths(slug)
        tag = slug if ch.get("active", True) else f"{slug}, paused"
        if not os.path.exists(P["library"]):
            line(WARN, f"no library.json ({tag})",
                 f"python3 metadata.py --channel {slug} --sync")
            continue
        L = (json.load(open(P["library"])) or {}).get("videos", {})
        vids = glob.glob(os.path.join(P["output"], "*.mp4"))
        missing = [os.path.basename(v) for v in vids
                   if os.path.basename(v) not in L]
        if missing:
            line(WARN, f"{len(missing)} video(s) lack metadata ({tag})",
                 f"python3 metadata.py --channel {slug} --sync")
        else:
            ready = sum(1 for v in L.values() if v.get("status") == "ready")
            line(OK, f"{len(L)} tracked, {ready} ready ({tag})")


def check_disk_and_links():
    print("\nSystem & money:")
    free = shutil.disk_usage(HERE).free // (1024**3)
    line(OK if free > 3 else WARN, f"{free} GB free disk",
         "" if free > 3 else "archive old uploaded videos from output/")

    # Per-channel too, for the same reason as library.json above.
    for ch in _paths.load_registry():
        if not ch.get("active", True):
            continue            # a paused channel's monetization links can wait
        slug = ch["slug"]
        links = _paths.paths(slug)["links"]
        if not os.path.exists(links):
            line(WARN, f"no links.json ({slug})",
                 "create it with your product/affiliate links")
            continue
        filled = [k for k, v in (json.load(open(links)) or {}).items() if v]
        if filled:
            line(OK, f"money links set ({slug}): {', '.join(filled)}")
        else:
            line(WARN, f"links.json is empty ({slug})",
                 "add your Gumroad/Linktree/affiliate URLs so descriptions include them")


if __name__ == "__main__":
    print("=" * 60)
    print("  MINDSET REFUEL — SYSTEM HEALTH CHECK")
    print("=" * 60)
    check_binaries()
    check_modules()
    check_assets()
    check_voice()
    check_content()
    check_schedule()
    check_disk_and_links()
    print("\n" + "=" * 60)
    if issues["bad"]:
        print(f"  {BAD} {issues['bad']} problem(s) need fixing (see → hints above).")
        sys.exit(1)
    elif issues["warn"]:
        print(f"  {WARN} {issues['warn']} minor note(s), but you're good to run.")
    else:
        print("  ✓ ALL GOOD. The machine is healthy. Go upload. 💪")
    print("=" * 60)
