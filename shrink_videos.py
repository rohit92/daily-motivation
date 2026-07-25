#!/usr/bin/env python3
"""
shrink_videos.py — re-encode oversized Shorts that are still waiting to upload.

Videos built before the encoder was capped came out ~10x larger than they need
to be (a 33s Short at ~29 Mbps ≈ 120 MB). Big files are the main cause of
half-finished uploads that sit in YouTube "processing" forever, and they make
every upload slow. This re-encodes them to the same settings make_video.py now
uses — visually identical on a phone, ~10x smaller.

It only touches videos that have NOT been uploaded, never re-renders (no TTS,
no ffmpeg filter graph — just a transcode), and only replaces the original
after verifying the new file is valid and the same length.

  python3 shrink_videos.py            # all channels, report + shrink
  python3 shrink_videos.py --dry-run  # just show what would change
"""
import argparse
import json
import os
import subprocess
import sys

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
# Anything above this bitrate is worth re-encoding (our target is ~3 Mbps).
BITRATE_LIMIT = 6_000_000


def probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "default=noprint_wrappers=1:nokey=1", path]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    return out.splitlines()


def duration(path):
    try:
        return float(probe(path, "format=duration")[0])
    except Exception:
        return 0.0


def shrink(path, dry=False):
    """Re-encode one file in place. Returns (old_mb, new_mb) or None if skipped."""
    old = os.path.getsize(path)
    dur = duration(path)
    if dur <= 0:
        print(f"    · skip (unreadable): {os.path.basename(path)}")
        return None
    bitrate = old * 8 / dur
    if bitrate <= BITRATE_LIMIT:
        return None                                   # already small enough
    if dry:
        print(f"    would shrink {os.path.basename(path)} "
              f"({old/1048576:.1f} MB, {bitrate/1e6:.1f} Mbps)")
        return None

    tmp = path + ".shrink.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", path,
         "-c:v", "libx264", "-preset", "medium", "-crf", "24",
         "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp],
        capture_output=True, text=True)

    # verify before replacing — a bad transcode must never eat the original
    ok = (r.returncode == 0 and os.path.exists(tmp)
          and os.path.getsize(tmp) > 100_000
          and abs(duration(tmp) - dur) < 1.0)
    if not ok:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"    ✗ re-encode failed, kept original: {os.path.basename(path)}")
        return None
    new = os.path.getsize(tmp)
    if new >= old:                                    # no gain — keep original
        os.remove(tmp)
        return None
    os.replace(tmp, path)
    return old / 1048576, new / 1048576


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()

    chans = ([{"slug": a.channel}] if a.channel and a.channel != _paths.DEFAULT_CHANNEL
             else _paths.active_channels())
    saved = 0.0
    for c in chans:
        slug = c["slug"]
        P = _paths.paths(slug)
        lib = json.load(open(P["library"])) if os.path.exists(P["library"]) else {"videos": {}}
        print(f"[{slug}]")
        for name, v in sorted((lib.get("videos") or {}).items()):
            if v.get("status") == "uploaded":
                continue                              # already on YouTube
            path = os.path.join(P["output"], name)
            if not os.path.exists(path):
                continue
            res = shrink(path, dry=a.dry_run)
            if res:
                old, new = res
                saved += old - new
                print(f"    ✓ {name}: {old:.1f} MB → {new:.1f} MB")
    if not a.dry_run and saved:
        print(f"\nReclaimed {saved:.1f} MB — uploads will be much faster.")
    elif not a.dry_run:
        print("\nNothing to shrink — every pending video is already small.")


if __name__ == "__main__":
    main()
