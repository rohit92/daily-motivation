#!/usr/bin/env python3
"""
character.py — overlay a simple animated stick-figure narrator whose mouth moves
in sync with the voice. A post-step: it takes a finished video and returns a new
one with the character, so it can never break the main generator.

Honest scope: this is a clean stick-cartoon (free, local, no paid avatar tools).
It adds motion + personality, which helps retention. For studio 2D/3D avatars
you'd need paid services — this is the free, ships-today version.

  python3 character.py output/20_c008.mp4            # -> ..._toon.mp4
  python3 character.py in.mp4 out.mp4
"""

import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, ".work", "char")
FPS = 30
CW, CH = 340, 540          # character canvas


def sprite(mouth):
    """mouth: 0 closed, 1 mid, 2 open. Returns an RGBA stick figure."""
    img = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = CW // 2

    def stroke(shape, pts, w):
        # dark halo then white, so it reads on any background
        d.line(pts, fill=(0, 0, 0, 220), width=w + 8, joint="curve") if shape == "line" \
            else d.ellipse(pts, outline=(0, 0, 0, 220), width=w + 8)
        d.line(pts, fill=(255, 255, 255, 255), width=w, joint="curve") if shape == "line" \
            else d.ellipse(pts, outline=(255, 255, 255, 255), width=w)

    # head
    stroke("ellipse", [cx - 62, 30, cx + 62, 154], 12)
    # eyes
    for ex in (cx - 24, cx + 24):
        d.ellipse([ex - 8, 78, ex + 8, 94], fill=(255, 255, 255, 255))
        d.ellipse([ex - 8, 78, ex + 8, 94], outline=(0, 0, 0, 220), width=3)
    # mouth
    if mouth == 0:
        stroke("line", [cx - 22, 122, cx + 22, 122], 10)
    elif mouth == 1:
        d.ellipse([cx - 20, 116, cx + 20, 132], fill=(0, 0, 0, 230),
                  outline=(255, 255, 255, 255), width=6)
    else:
        d.ellipse([cx - 26, 108, cx + 26, 146], fill=(0, 0, 0, 230),
                  outline=(255, 255, 255, 255), width=6)
    # body
    stroke("line", [(cx, 154), (cx, 330)], 12)
    stroke("line", [(cx, 196), (cx - 66, 268)], 12)
    stroke("line", [(cx, 196), (cx + 66, 268)], 12)
    stroke("line", [(cx, 330), (cx - 54, 486)], 12)
    stroke("line", [(cx, 330), (cx + 54, 486)], 12)
    return img


def mouth_states(wav_path, nframes):
    with wave.open(wav_path) as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    spf = max(1, len(data) // max(1, nframes))
    rms = np.array([np.sqrt(np.mean(data[i*spf:(i+1)*spf]**2) + 1)
                    for i in range(nframes)])
    peak = np.percentile(rms, 95) or 1.0
    lvl = np.clip(rms / peak, 0, 1)
    return np.where(lvl < 0.18, 0, np.where(lvl < 0.5, 1, 2))


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", path],
                         capture_output=True, text=True)
    return float(out.stdout.strip())


def build(in_video, out_video):
    os.makedirs(WORK, exist_ok=True)
    for f in os.listdir(WORK):
        os.remove(os.path.join(WORK, f))

    dur = duration(in_video)
    nframes = int(dur * FPS)
    wav = os.path.join(WORK, "audio.wav")
    subprocess.run(["ffmpeg", "-y", "-i", in_video, "-vn", "-ac", "1", "-ar", "22050", wav],
                   check=True, capture_output=True)

    states = mouth_states(wav, nframes)
    # render the 3 sprites once, then hardlink the right one per frame
    paths = {}
    for s in (0, 1, 2):
        p = os.path.join(WORK, f"sprite_{s}.png")
        sprite(s).save(p)
        paths[s] = p
    for i, s in enumerate(states):
        link = os.path.join(WORK, f"f_{i+1:05d}.png")
        try:
            os.link(paths[int(s)], link)
        except OSError:
            Image.open(paths[int(s)]).save(link)

    seq = os.path.join(WORK, "f_%05d.png")
    # overlay bottom-left with a gentle talking bob; keep original audio.
    subprocess.run([
        "ffmpeg", "-y", "-i", in_video, "-framerate", str(FPS), "-i", seq,
        "-filter_complex",
        "[0:v][1:v]overlay=x=48:y='H-h-120-16*abs(sin(2.4*t))':shortest=1[v]",
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", out_video,
    ], check=True, capture_output=True)
    return out_video


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 character.py <in.mp4> [out.mp4]")
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + "_toon.mp4"
    build(src, out)
    print("wrote", os.path.relpath(out, HERE))


if __name__ == "__main__":
    main()
