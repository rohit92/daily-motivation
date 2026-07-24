#!/usr/bin/env python3
"""
make_compilation.py — stitch your Shorts into ONE long-form video.

Why: channels that pair Shorts with long-form grow ~41% faster, and long-form
builds the 4,000 watch-hours that unlock the other path to monetization. Post
one of these a week.

  python3 make_compilation.py                 # all videos in output/
  python3 make_compilation.py --count 20      # newest 20
  python3 make_compilation.py --title "10 Minutes of Pure Motivation"

Output: long_form/compilation_YYYY-MM-DD.mp4  (+ a suggested title/description).
"""

import argparse
import glob
import os
import subprocess
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "output")
OUT_DIR = os.path.join(HERE, "long_form")
WORK = os.path.join(HERE, ".work")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=0, help="use newest N (0 = all)")
    ap.add_argument("--title", default="Motivation Mix — Start Your Day Right")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)

    clips = sorted(glob.glob(os.path.join(OUTPUT, "*.mp4")))
    if not clips:
        raise SystemExit("No videos in output/. Generate some first.")
    if args.count:
        clips = sorted(clips, key=os.path.getmtime)[-args.count:]

    listfile = os.path.join(WORK, "compile_list.txt")
    with open(listfile, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")

    out = os.path.join(OUT_DIR, f"compilation_{date.today().isoformat()}.mp4")
    # concat demuxer with stream copy — fast, no re-encode (all clips share codec).
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", "-movflags", "+faststart", out],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or duration(out) < 1:
        # fallback: re-encode (handles any codec mismatch)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out],
            check=True, capture_output=True,
        )

    dur = duration(out)
    mins = int(dur // 60)
    print(f"Built {os.path.relpath(out, HERE)}  —  {len(clips)} clips, "
          f"{mins}m {int(dur % 60)}s")
    print("\nSuggested upload (LONG-FORM, not a Short):")
    print(f"  Title: {args.title} 🔥 (Daily Motivation Compilation)")
    print("  Description: The best of Mindset Refuel in one place. "
          "Play it while you work out, study, or start your day. "
          "Follow for daily motivation. #motivation #discipline #mindset")
    print("  Tip: pin your product link in the first comment.")


if __name__ == "__main__":
    main()
