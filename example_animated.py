#!/usr/bin/env python3
"""example_animated.py — ONE sample Short with an ANIMATED background (moving
gradient + film grain + vignette) instead of a still photo, to show the new look.

Standalone demo: reuses make_video's neural voice + karaoke captions, only the
background changes. Does NOT touch the main pipeline. Output: example_animated.mp4
"""
import os, subprocess, sys
import make_video as mv

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, ".work", "example")
os.makedirs(WORK, exist_ok=True)
OUT = os.path.join(HERE, "example_animated.mp4")
W, H, FPS = mv.W, mv.H, mv.FPS

LINES = ["Motivation is a liar.", "Discipline is what stays."]
LABEL = "MINDSET REFUEL"
CTA = "SUBSCRIBE for daily motivation"

# 1) voice + karaoke caption frames per line (reusing make_video)
segs = []          # (wav, dur, [png per word], [(start,end) per word])
for i, line in enumerate(LINES):
    wav = os.path.join(WORK, f"v{i}.wav")
    timings = mv.synth_line(line, wav)
    d = mv.duration(wav)
    words, font, wlines, line_h = mv.caption_layout(line)
    wins = mv.word_windows(words, timings, d)
    pngs = []
    for j in range(len(words)):
        p = os.path.join(WORK, f"c{i}_{j}.png")
        mv.render_caption_state(words, j, font, wlines, line_h, LABEL, CTA, p)
        pngs.append(p)
    segs.append((wav, d, pngs, wins))

total = round(sum(d for _, d, _, _ in segs) + 0.4, 3)

# 2) build ffmpeg inputs: [0]=animated gradient, then all word PNGs, then voices
cmd = ["/opt/homebrew/bin/ffmpeg", "-y",
       "-f", "lavfi", "-t", f"{total:.3f}",
       "-i", (f"gradients=s={W}x{H}:c0=0x0a1a3a:c1=0x2a1050:c2=0x08202a:"
              f"c3=0x140a2e:nb_colors=4:speed=0.006:type=spiral")]
png_index = {}
idx = 1
for i, (_, d, pngs, _) in enumerate(segs):
    for j, p in enumerate(pngs):
        cmd += ["-loop", "1", "-t", f"{total:.3f}", "-i", p]
        png_index[(i, j)] = idx
        idx += 1
audio_base = idx
for wav, *_ in segs:
    cmd += ["-i", wav]

# 3) filter graph: gradient -> grain + vignette + gentle darken -> word overlays
fc = [f"[0:v]format=yuv420p,noise=alls=11:allf=t+u,"
      f"eq=brightness=-0.06:saturation=1.15,vignette=PI/4.5[bg]"]
prev = "bg"
k = 0
line_start = 0.0
for i, (_, d, pngs, wins) in enumerate(segs):
    for j, (s, e) in enumerate(wins):
        gs, ge = line_start + s, line_start + e
        out = f"o{k}"
        fc.append(f"[{prev}][{png_index[(i,j)]}:v]overlay=0:0:"
                  f"enable='between(t,{gs:.3f},{ge:.3f})'[{out}]")
        prev = out
        k += 1
    line_start += d
fc.append(f"[{prev}]fade=t=in:st=0:d=0.4,fade=t=out:st={total-0.5:.3f}:d=0.5[vout]")
aud = "".join(f"[{audio_base+i}:a]" for i in range(len(segs)))
fc.append(f"{aud}concat=n={len(segs)}:v=0:a=1,afade=t=out:st={total-0.5:.3f}:d=0.5[aud]")

cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aud]",
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", OUT]

print("Building animated example…")
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print("FAILED:\n", r.stderr[-1500:]); sys.exit(1)
print(f"OK -> {OUT}  ({total:.1f}s)")
