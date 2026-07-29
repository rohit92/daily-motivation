#!/usr/bin/env python3
"""
make_video.py — Faceless YouTube Shorts generator (free, monetization-friendly).

Per video:
  1. Pick the next unused item from content.json (tracked in state.json).
  2. For each spoken line: synth a natural neural voice (edge-tts, Piper
     fallback), capture per-word timings, and render one caption frame per word
     so the spoken word lights up in gold (karaoke-style, high-retention).
  3. ffmpeg builds a 1080x1920 Short where the background image, the on-screen
     caption, and the voice all change together in sync, with a slow Ken Burns
     zoom and fades. Backgrounds are darkened so text is always readable.
  4. Save to output/NN_<id>.mp4  (typically 15-25s).

Everything is free and copyright-safe:
  - Voice:  Piper neural TTS, fully offline (no API key).
  - Images: your assets/backgrounds/ folder (Picsum / Pexels — free commercial use).
  - NEVER use random Google-image-search results: most are copyrighted and will
    get the channel demonetized or struck.

Usage:
  python3 make_video.py                 # make the next 1 video
  python3 make_video.py --batch 7       # make a week at once
  python3 make_video.py --reset         # forget used-item history
"""

import argparse
import asyncio
import glob
import json
import os
import random
import shutil
import subprocess
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

try:
    import edge_tts  # neural TTS + per-word timing (WordBoundary events)
    EDGE_TTS_OK = True
except Exception:
    EDGE_TTS_OK = False

import netcfg
import paths as _paths

PROXY = netcfg.proxy_url()   # '' unless a college proxy is enabled in config

HERE = os.path.dirname(os.path.abspath(__file__))
# Shared roots (identical for every channel).
WORK_DIR = os.path.join(HERE, ".work")
BG_DIR = os.path.join(HERE, "assets", "backgrounds")
MUSIC_DIR = os.path.join(HERE, "assets", "music")
VOICE_MODEL = os.path.join(HERE, "assets", "voices", "en_US-ryan-high.onnx")

# Per-channel paths are resolved at run time via paths.paths(<slug>). These
# module-level names default to the motivation channel so any legacy import that
# reads CONTENT/STATE/CONFIG/OUTPUT_DIR/LOGO still works.
_P = _paths.paths(None)
CONTENT = _P["content"]
STATE = _P["state"]
CONFIG = _P["config"]
OUTPUT_DIR = _P["output"]
LOGO = os.path.join(_P["brand"], "logo.png")

W, H = 1080, 1920
FPS = 30


def _font(*candidates):
    """Return the first font path that exists, else a Linux fallback so the
    generator runs on macOS (production) and Linux (CI/sandbox) alike."""
    for c in candidates:
        if c and os.path.exists(c):
            return c
    for fb in ("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(fb):
            return fb
    return candidates[0] if candidates else None


FONT_MAIN = _font("/System/Library/Fonts/Supplemental/Arial Black.ttf")
FONT_SMALL = _font("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

GOLD = (240, 190, 70, 235)   # active-word highlight pill (on-brand gold)

# --- Voice settings ---
# Default: edge-tts neural voice (very natural, needs internet).
# Fallback: Piper (offline) if edge-tts can't be reached.
# config.json "voice" overrides (Settings → Voice style): the en-IN voices
# sound local to the channel's core Indian audience.
def _load_voice(config_path):
    try:
        with open(config_path) as _f:
            return json.load(_f).get("voice", "")
    except Exception:
        return ""


def _load_cfg(config_path, key, default):
    try:
        with open(config_path) as _f:
            v = json.load(_f).get(key)
            return default if v is None else v
    except Exception:
        return default


EDGE_VOICE = _load_voice(CONFIG) or "en-US-AndrewNeural"
# Delivery speed. This was pinned at -9% ("more deliberate"), which is wrong for
# Shorts: the first two seconds decide whether someone swipes, and a slow opening
# line reads as dead air. Faster delivery also fits more words into the same
# runtime, so the hook lands before the viewer's thumb does.
# Override per channel with "voice_rate": "+12%" in that channel's config.json.
EDGE_RATE = _load_cfg(CONFIG, "voice_rate", "+12%")
# Piper's scale is inverse: lower = faster. Kept roughly in step with EDGE_RATE.
PIPER_LENGTH_SCALE = float(_load_cfg(CONFIG, "piper_length_scale", 0.94))
# Dead air between lines. Half a second per line on a 6-line Short is 3 seconds
# of silence — a third of the video spent saying nothing.
GAP_SECONDS = float(_load_cfg(CONFIG, "line_gap_seconds", 0.22))


def need(binary):
    if shutil.which(binary) is None:
        sys.exit(f"ERROR: '{binary}' is required but not found on PATH.")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pick_items(content, state, count):
    used = set(state.get("used_ids", []))
    by_id = {it["id"]: it for it in content["items"]}

    def hook(it):
        lines = it.get("lines") or [""]
        return (lines[0] or "").strip().lower()

    # The first line is spoken first AND becomes the title, so two scripts that
    # share it produce two videos that look identical in the feed. Scripts
    # composed before script_composer enforced unique hooks can still collide,
    # so filter them out here too — this is the last gate before a render.
    spoken = {hook(by_id[i]) for i in used if i in by_id}
    queue = []
    for it in content["items"]:
        if it["id"] in used or hook(it) in spoken:
            continue
        spoken.add(hook(it))
        queue.append(it)
    if not queue:
        sys.exit("No scripts left with an unused hook. Add new hooks to the "
                 "bank in script_composer.py (see --stats for the count).")
    return queue[:count]


# ---------- caption card (Pillow, transparent PNG) ----------

def fit_text(draw, text, font_path, max_w, max_h, start_size):
    size = start_size
    lines, line_h = [text], start_size
    while size > 30:
        font = ImageFont.truetype(font_path, size)
        avg = draw.textlength("ABCDEFGHIJ abcdefghij", font=font) / 21
        width_chars = max(8, int(max_w / avg))
        lines = textwrap.wrap(text, width=width_chars,
                              break_long_words=False, break_on_hyphens=False)
        line_h = size + int(size * 0.30)
        block_h = line_h * len(lines)
        widest = max((draw.textlength(l, font=font) for l in lines), default=0)
        if widest <= max_w and block_h <= max_h:
            return font, lines, line_h
        size -= 4
    return font, lines, line_h


def caption_layout(line):
    """Compute wrapping ONCE per line so every word-state PNG shares an
    identical layout (the highlight moves, the text never jitters)."""
    tmp = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(tmp)
    words = line.split() or [line]
    font, lines, line_h = fit_text(d, " ".join(words), FONT_MAIN, 900, 620, 92)
    return words, font, lines, line_h


def render_caption_state(words, active, font, lines, line_h, label, cta, out_png):
    """Render the full caption with word #active lit in a gold pill (karaoke).
    Non-active words stay white with a drop shadow; layout is fixed by the
    precomputed `lines`/`line_h` so only the highlight moves between frames."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    block_h = line_h * len(lines)
    cy = H // 2
    size = font.size

    # dark scrim behind the quote for guaranteed contrast on any image
    pad_y = 60
    top = cy - block_h // 2 - pad_y
    bot = cy + block_h // 2 + pad_y
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(scrim).rounded_rectangle(
        [60, top, W - 60, bot], radius=40, fill=(0, 0, 0, 140)
    )
    img = Image.alpha_composite(img, scrim)
    draw = ImageDraw.Draw(img)

    # quote lines, drawn word-by-word so the active word can be highlighted
    space_w = draw.textlength(" ", font=font)
    gw = 0
    y = cy - block_h // 2
    for ln in lines:
        lw = draw.textlength(ln, font=font)
        x = (W - lw) / 2
        for word in ln.split():
            ww = draw.textlength(word, font=font)
            if gw == active:
                draw.rounded_rectangle(
                    [x - 16, y + size * 0.04, x + ww + 16, y + size * 1.16],
                    radius=int(size * 0.26), fill=GOLD,
                )
                draw.text((x, y), word, font=font, fill=(20, 20, 20, 255))
            else:
                draw.text((x + 4, y + 4), word, font=font, fill=(0, 0, 0, 200))
                draw.text((x, y), word, font=font, fill=(255, 255, 255, 255))
            x += ww + space_w
            gw += 1
        y += line_h

    # top label
    lab_font = ImageFont.truetype(FONT_SMALL, 46)
    lw = draw.textlength(label.upper(), font=lab_font)
    draw.text(((W - lw) / 2 + 3, 303), label.upper(), font=lab_font, fill=(0, 0, 0, 160))
    draw.text(((W - lw) / 2, 300), label.upper(), font=lab_font, fill=(255, 255, 255, 210))

    # bottom cta
    cta_font = ImageFont.truetype(FONT_SMALL, 46)
    cw = draw.textlength(cta, font=cta_font)
    draw.text(((W - cw) / 2 + 2, H - 318), cta, font=cta_font, fill=(0, 0, 0, 160))
    draw.text(((W - cw) / 2, H - 320), cta, font=cta_font, fill=(255, 255, 255, 230))

    img.save(out_png)


def word_windows(words, timings, seg_dur):
    """Return one (start, end) display window per word, contiguous across the
    whole clip. Uses real edge-tts word boundaries when they line up 1:1 with
    the visible words; otherwise splits time by word length (offline fallback)."""
    n = len(words)
    speech = max(0.3, seg_dur - GAP_SECONDS)
    if timings and len(timings) == n:
        starts = [max(0.0, t["start"]) for t in timings]
    else:
        weights = [len(w) + 1 for w in words]
        tot = sum(weights) or 1
        acc, starts = 0, []
        for w in weights:
            starts.append(speech * acc / tot)
            acc += w
    wins = []
    for i in range(n):
        s = starts[i]
        e = starts[i + 1] if i + 1 < n else seg_dur
        wins.append((max(0.0, s), max(s + 0.05, e)))
    if wins:
        wins[0] = (0.0, wins[0][1])   # first word lit from the very start
    return wins


# ---------- voice (edge-tts, Piper fallback) ----------

async def _edge_stream(text, mp3_path):
    """Stream edge-tts audio to mp3_path and collect per-word timings.
    edge-tts >=7 defaults to SentenceBoundary, so we must ASK for WordBoundary
    to get the per-word offsets the karaoke captions need."""
    kw = dict(rate=EDGE_RATE, proxy=(PROXY or None))
    try:
        comm = edge_tts.Communicate(text, EDGE_VOICE, boundary="WordBoundary", **kw)
    except TypeError:               # older edge-tts: emits WordBoundary by default
        comm = edge_tts.Communicate(text, EDGE_VOICE, **kw)
    words = []
    with open(mp3_path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({
                    "text": ch["text"],
                    "start": ch["offset"] / 1e7,                      # 100ns -> s
                    "end": (ch["offset"] + ch["duration"]) / 1e7,
                })
    return words


def synth_line(text, out_wav):
    """Synthesize `text` to out_wav (44.1kHz) with a trailing pause.
    Returns per-word timings [{text,start,end}] in the unpadded audio timeline
    when the neural voice provides them, else None (caller approximates).
    Prefers the edge-tts Python API (audio + timings), then the edge CLI, then
    offline Piper."""
    raw_mp3 = out_wav + ".raw.mp3"
    raw_wav = out_wav + ".raw.wav"
    src, words = None, None

    # 1) edge-tts Python API — audio and word boundaries in a single pass
    if EDGE_TTS_OK:
        try:
            words = asyncio.run(_edge_stream(text, raw_mp3))
            if os.path.exists(raw_mp3) and os.path.getsize(raw_mp3) > 0:
                src = raw_mp3
            else:
                words = None
        except Exception:
            src, words = None, None

    # 2) edge-tts CLI — audio only (no timings)
    if src is None:
        try:
            cli = [sys.executable, "-m", "edge_tts", "--voice", EDGE_VOICE,
                   "--rate", EDGE_RATE, "--text", text, "--write-media", raw_mp3]
            if PROXY:
                cli += ["--proxy", PROXY]
            r = subprocess.run(cli, capture_output=True, timeout=30)
            if r.returncode == 0 and os.path.exists(raw_mp3) and os.path.getsize(raw_mp3) > 0:
                src = raw_mp3
        except Exception:
            src = None

    # 3) offline fallback
    if src is None:
        subprocess.run(
            [sys.executable, "-m", "piper", "--model", VOICE_MODEL,
             "--length_scale", str(PIPER_LENGTH_SCALE), "--output_file", raw_wav],
            input=text, text=True, check=True, capture_output=True,
        )
        src = raw_wav

    # normalize + add trailing pause so lines breathe (appends silence at the
    # end; earlier word timings stay valid)
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ac", "2",
         "-af", f"aresample=44100,apad=pad_dur={GAP_SECONDS}", out_wav],
        check=True, capture_output=True,
    )
    for f in (raw_mp3, raw_wav):
        if os.path.exists(f):
            os.remove(f)
    return words


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ---------- subscribe end-cap ----------
# The description CTA is invisible on Shorts (nobody opens it); this puts the
# subscribe ask INSIDE the video for ~2s at the end — the one place every
# viewer who finished actually looks. Toggle: config.json "endcap" (default on).

# Per-channel branding for the end-cap. Set from main() so each channel names
# itself in the subscribe card. Defaults keep the motivation channel identical.
ENDCAP_NAME = "Mindset Refuel"
ENDCAP_HANDLE = "@mindsetrefuel"
ENDCAP_COLOR = GOLD[:3]
ENDCAP_LINE = "Subscribe to Mindset Refuel. A brand new one drops every single day."


def _set_branding(name, handle, color):
    """Update the module-level end-cap branding for the active channel."""
    global ENDCAP_NAME, ENDCAP_HANDLE, ENDCAP_COLOR, ENDCAP_LINE
    ENDCAP_NAME = name or ENDCAP_NAME
    ENDCAP_HANDLE = handle or ENDCAP_HANDLE
    if color:
        ENDCAP_COLOR = tuple(color)[:3]
    ENDCAP_LINE = f"Subscribe to {ENDCAP_NAME}. A brand new one drops every single day."


def endcap_png(out_png):
    img = Image.new("RGB", (W, H), (11, 14, 21))
    d = ImageDraw.Draw(img)
    for i in range(H):                          # subtle brand gradient
        v = 11 + int(16 * i / H)
        d.line([(0, i), (W, i)], fill=(v, v + 3, v + 10))
    y = int(H * 0.30)
    if os.path.exists(LOGO):
        try:
            logo = Image.open(LOGO).convert("RGBA").resize((260, 260))
            img.paste(logo, ((W - 260) // 2, y - 280), logo)
        except Exception:
            pass
    big = ImageFont.truetype(FONT_MAIN, 118)
    tw = d.textlength("SUBSCRIBE", font=big)
    pad = 44
    d.rounded_rectangle([(W - tw) / 2 - pad, y + 30, (W + tw) / 2 + pad, y + 30 + 118 * 1.32],
                        radius=44, fill=ENDCAP_COLOR)
    d.text(((W - tw) / 2, y + 52), "SUBSCRIBE", font=big, fill=(20, 20, 20))
    handle = ImageFont.truetype(FONT_SMALL, 64)
    hw = d.textlength(ENDCAP_HANDLE, font=handle)
    d.text(((W - hw) / 2, y + 250), ENDCAP_HANDLE, font=handle, fill=(238, 241, 247))
    small = ImageFont.truetype(FONT_SMALL, 46)
    sw = d.textlength("New video every day", font=small)
    d.text(((W - sw) / 2, y + 360), "New video every day", font=small,
           fill=(147, 160, 189))
    img.save(out_png)


def build_endcap():
    """Build the ~2s end-cap segment once; encoded exactly like the main video
    so the two concat with stream copy."""
    png = os.path.join(WORK_DIR, "endcap.png")
    wav = os.path.join(WORK_DIR, "endcap.wav")
    seg = os.path.join(WORK_DIR, "endcap.mp4")
    endcap_png(png)
    synth_line(ENDCAP_LINE, wav)
    dur = duration(wav)
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", png, "-i", wav,
         "-filter_complex",
         f"[0:v]scale={W}:{H},setsar=1,fade=t=in:st=0:d=0.3,format=yuv420p[v];"
         f"[1:a]afade=t=out:st={max(0, dur - 0.5):.3f}:d=0.5[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-maxrate", "6M", "-bufsize", "12M",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", seg],
        check=True, capture_output=True)
    return seg


def append_endcap(out_path):
    """Concat the end-cap onto a finished Short (stream copy, re-encode fallback).
    Never allowed to break the build — worst case the video ships without it."""
    try:
        seg = build_endcap()
        listfile = os.path.join(WORK_DIR, "endcap_list.txt")
        with open(listfile, "w") as f:
            f.write(f"file '{out_path}'\nfile '{seg}'\n")
        merged = out_path + ".cap.mp4"
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
             "-c", "copy", "-movflags", "+faststart", merged],
            capture_output=True)
        if r.returncode != 0 or duration(merged) <= duration(out_path):
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                 "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-maxrate", "6M", "-bufsize", "12M",
                 "-pix_fmt", "yuv420p", "-r", str(FPS),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                 "-movflags", "+faststart", merged],
                check=True, capture_output=True)
        os.replace(merged, out_path)
        return True
    except Exception:
        for f in (out_path + ".cap.mp4",):
            if os.path.exists(f):
                os.remove(f)
        return False


# ---------- build one video ----------

# ---------- animated background (config: animated_bg, default on) ----------
# A moving gradient + film grain + vignette instead of a static photo — far more
# engaging on the feed, 100% free, no copyright. One continuous clip is rendered
# for the whole video so motion never resets between lines.

def _grad_palette(rgb):
    """Rich jewel-tone 4-colour palette, tinted by the channel's brand colour —
    dark enough for white text, vibrant enough to look alive."""
    r, g, b = (tuple(rgb)[:3] if rgb else (240, 190, 70))
    m = lambda v: max(16, min(130, int(v * 0.34)))
    bt = f"0x{m(r):02x}{m(g):02x}{m(b):02x}"
    return ["0x14336e", "0x3f1a72", bt, "0x0e3550"]


def grad_bg_video(total, out_mp4):
    c0, c1, c2, c3 = _grad_palette(ENDCAP_COLOR)
    src = (f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:c3={c3}:"
           f"nb_colors=4:speed=0.007:type=spiral")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", f"{max(total, 0.5):.3f}", "-i", src,
         "-vf", ("format=yuv420p,noise=alls=9:allf=t+u,"
                 "eq=brightness=0.02:saturation=1.22,vignette=PI/6.5"),
         "-r", str(FPS), "-c:v", "libx264", "-preset", "fast", "-crf", "22",
         "-pix_fmt", "yuv420p", out_mp4],
        check=True, capture_output=True)
    return out_mp4


def _theme_backgrounds(theme, n, lines=None):
    """n images of what this script is about, or [] if nothing is available.

    Subject first, theme second: matching on theme alone put elephants behind a
    fact about a shrimp, because the theme was 'animals' and the library
    obligingly returned animals.
    """
    try:
        import imagery
        if lines and _subject_mode():
            return imagery.for_script(lines, theme, n)
        return imagery.pick(theme, n) if theme else []
    except Exception:
        return []          # imagery is an enhancement; never break a render


def _write_credits(video_path, bgs):
    """Save image attribution beside the video. Silent no-op when none is due."""
    try:
        import imagery
        block = imagery.credit_block(bgs)
        side = os.path.splitext(video_path)[0] + "_credits.txt"
        if block:
            with open(side, "w") as f:
                f.write(block)
        elif os.path.exists(side):
            os.remove(side)
    except Exception:
        pass


def _subject_mode():
    """True when the picture is the point, not the mood.

    On a facts channel the image carries the information — someone stops
    scrolling because they see the octopus. Dimming it to -0.18 and washing 42%
    of a moving gradient over it, which is right for a motivation backdrop,
    makes the subject unreadable. Set "image_mode": "subject" (or "mood") in a
    channel's config.json to override the per-niche default.
    """
    mode = (load_json(CONFIG, {}) or {}).get("image_mode")
    if mode:
        return mode == "subject"
    try:
        return _paths.channel_meta(CHANNEL).get("niche") == "did-you-know-facts"
    except Exception:
        return False


def build_video(item, content, seq, bg_pool):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    for f in glob.glob(os.path.join(WORK_DIR, "seg_*")):
        os.remove(f)

    # Brand name on-screen every frame = recognition = subscribes (viewers
    # subscribe to channels they can NAME). CTA gives a concrete reason.
    label = content.get("category_label", "MINDSET REFUEL")
    cta = content.get("cta", "SUBSCRIBE · new one daily")
    lines = item["lines"]
    n = len(lines)

    # Backgrounds matched to what this script is actually ABOUT. The old code
    # sampled a shared pool of 20 generic photos at random, so every channel drew
    # from the same handful and a fact about an octopus was illustrated with a
    # stock landscape. imagery.py keeps a per-theme library; fall back to the
    # generic pool only when that theme hasn't been stocked yet.
    bgs = _theme_backgrounds(item.get("theme"), n, item.get("lines"))
    if not bgs:
        bgs = random.sample(bg_pool, min(n, len(bg_pool)))
        while len(bgs) < n:
            bgs.append(random.choice(bg_pool))

    # synth each line, then render one caption PNG per word (karaoke highlight)
    seg_wavs, seg_durs = [], []
    seg_states, seg_wins = [], []      # per line: [png paths], [(start,end)]
    for i, line in enumerate(lines):
        wav = os.path.join(WORK_DIR, f"seg_{i}.wav")
        timings = synth_line(line, wav)
        dur = duration(wav)
        words, font, wlines, line_h = caption_layout(line)
        wins = word_windows(words, timings, dur)
        pngs = []
        for j in range(len(words)):
            png = os.path.join(WORK_DIR, f"seg_{i}_w{j:02d}.png")
            render_caption_state(words, j, font, wlines, line_h, label, cta, png)
            pngs.append(png)
        seg_wavs.append(wav)
        seg_durs.append(dur)
        seg_states.append(pngs)
        seg_wins.append(wins)

    total = round(sum(seg_durs), 3)
    fade_out = round(total - 0.5, 3)

    # dynamic look (config animated_bg, default on): real images with STRONG
    # Ken Burns motion + an animated colour wash on top so the colours shift.
    animated = bool(load_json(CONFIG, {}).get("animated_bg", True))

    # assemble ffmpeg inputs: image backgrounds, then every word-PNG, then wavs
    cmd = ["ffmpeg", "-y"]
    for i in range(n):
        cmd += ["-loop", "1", "-t", f"{seg_durs[i]:.3f}", "-i", bgs[i]]
    png_base = []                      # first input index of each line's PNGs
    idx = n
    for i in range(n):
        png_base.append(idx)
        for png in seg_states[i]:
            cmd += ["-loop", "1", "-t", f"{seg_durs[i]:.3f}", "-i", png]
            idx += 1
    audio_base = idx                   # first audio input index
    for i in range(n):
        cmd += ["-i", seg_wavs[i]]

    # optional background music bed (mixed quietly under the voice)
    music_file = None
    music_pool = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.wav")) +
                        glob.glob(os.path.join(MUSIC_DIR, "*.mp3")))
    if music_pool:
        music_file = random.choice(music_pool)
        music_in = audio_base + n
        cmd += ["-stream_loop", "-1", "-i", music_file]

    # animated colour-wash overlay: a shifting gradient blended over the moving
    # images so the colours visibly change through the video (attention grabber).
    color_in = None
    if animated:
        c0, c1, c2, c3 = _grad_palette(ENDCAP_COLOR)
        color_in = (music_in + 1) if music_file else (audio_base + n)
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}",
                "-i", (f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:c3={c3}:"
                       f"nb_colors=4:speed=0.05:type=spiral")]

    # When the picture carries the information, it has to stay legible: dim it
    # less and let more of its own colour through.
    subject = _subject_mode()
    dim = -0.07 if subject else -0.18
    sat = 1.06 if subject else 1.20

    fc = []
    for i in range(n):
        # stronger Ken Burns — a clear, faster zoom so every image visibly moves.
        # Alternate the direction so consecutive shots don't all drift the same
        # way, which is what made a run of images read as one static block.
        if i % 2:
            z = "z='max(1.32-0.0040*on,1.02)'"
        else:
            z = "z='min(1.02+0.0040*on,1.32)'"
        fc.append(
            f"[{i}:v]scale=1296:2304:force_original_aspect_ratio=increase,"
            f"crop=1296:2304,"
            f"zoompan={z}:d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
            f"eq=brightness={dim}:saturation={sat},setsar=1[bg{i}]"
        )
        # overlay each word-PNG only during its spoken window; a disabled
        # overlay passes the frame through, so exactly one word is lit at a time.
        prev = f"bg{i}"
        for j, (s, e) in enumerate(seg_wins[i]):
            pin = png_base[i] + j
            out = f"seg{i}" if j == len(seg_wins[i]) - 1 else f"o{i}_{j}"
            fc.append(
                f"[{prev}][{pin}:v]overlay=0:0:"
                f"enable='between(t,{s:.3f},{e:.3f})'[{out}]"
            )
            prev = out
    vconcat = "".join(f"[seg{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc]"
    aconcat = "".join(f"[{audio_base+i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[ac]"
    if animated and color_in is not None:
        # The colour wash is mood, not content. At 0.42 it buried the subject of
        # a facts image under a moving gradient; keep it faint when the picture
        # is the payload.
        wash = 0.16 if subject else 0.42
        vout = (f"[{color_in}:v]fps={FPS},format=yuv420p,setsar=1[cw];"
                f"[vc][cw]blend=all_mode=softlight:all_opacity={wash},"
                f"noise=alls=7:allf=t,"
                f"fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out}:d=0.5,"
                f"format=yuv420p[vout]")
    else:
        vout = (f"[vc]fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out}:d=0.5,"
                f"format=yuv420p[vout]")
    if music_file:
        aout = (f"[{music_in}:a]volume=0.12,afade=t=in:st=0:d=1.2[mus];"
                f"[ac][mus]amix=inputs=2:duration=first:normalize=0[amx];"
                f"[amx]afade=t=out:st={fade_out}:d=0.6[aout]")
    else:
        aout = f"[ac]afade=t=out:st={fade_out}:d=0.5[aout]"
    filter_complex = ";".join(fc) + ";" + vconcat + ";" + aconcat + ";" + vout + ";" + aout

    out_path = os.path.join(OUTPUT_DIR, f"{seq:02d}_{item['id']}.mp4")
    # Record the attribution CC BY images require, next to the video, so the
    # description generator can append it without re-deriving which images ran.
    _write_credits(out_path, bgs)
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-maxrate", "6M", "-bufsize", "12M",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    if load_json(CONFIG, {}).get("endcap", True):
        if append_endcap(out_path):
            total = duration(out_path)
    return out_path, total


def main():
    ap = argparse.ArgumentParser(description="Faceless Shorts generator")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--id", help="generate one specific script id (used by the pilot)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild an --id that was already made (creates a duplicate)")
    _paths.add_channel_arg(ap)
    args = ap.parse_args()

    # Resolve this channel's data files + branding (defaults to motivation).
    global CONTENT, STATE, CONFIG, OUTPUT_DIR, LOGO, EDGE_VOICE, WORK_DIR
    global EDGE_RATE, PIPER_LENGTH_SCALE, GAP_SECONDS, CHANNEL
    CHANNEL = args.channel
    P = _paths.paths(args.channel)
    CONTENT, STATE, CONFIG = P["content"], P["state"], P["config"]
    OUTPUT_DIR = P["output"]
    LOGO = os.path.join(P["brand"], "logo.png")
    # Channel-scoped scratch dir so parallel renders never collide.
    WORK_DIR = os.path.join(HERE, ".work", args.channel)
    EDGE_VOICE = _load_voice(CONFIG) or EDGE_VOICE
    # Pacing is per channel too — these were read at import against the DEFAULT
    # channel's config, so a per-channel override never took effect.
    EDGE_RATE = _load_cfg(CONFIG, "voice_rate", EDGE_RATE)
    PIPER_LENGTH_SCALE = float(_load_cfg(CONFIG, "piper_length_scale",
                                         PIPER_LENGTH_SCALE))
    GAP_SECONDS = float(_load_cfg(CONFIG, "line_gap_seconds", GAP_SECONDS))
    meta = _paths.channel_meta(args.channel)
    _set_branding(meta.get("name"), meta.get("handle"), meta.get("brand_color"))

    need("ffmpeg")
    need("ffprobe")
    if not os.path.exists(VOICE_MODEL):
        sys.exit(f"Voice model missing: {VOICE_MODEL}")

    bg_pool = sorted(glob.glob(os.path.join(BG_DIR, "*.jpg")) +
                     glob.glob(os.path.join(BG_DIR, "*.png")) +
                     glob.glob(os.path.join(BG_DIR, "*.jpeg")))
    if not bg_pool:
        sys.exit(f"No backgrounds found in {BG_DIR}. Run fetch_backgrounds.py.")

    content = load_json(CONTENT, None)
    if content is None:
        sys.exit("content.json not found.")

    state = {"used_ids": []} if args.reset else load_json(STATE, {"used_ids": []})
    if args.id:
        items = [it for it in content["items"] if it["id"] == args.id]
        if not items:
            sys.exit(f"Script id {args.id} not found in content.json")
        # --id skipped pick_items, which is the ONLY place used_ids was checked.
        # Rebuilding a used id ships the same script twice under two file names —
        # that is how c015/c014 went out twice and c018 three times. YouTube reads
        # near-identical uploads as reused content, which risks monetization.
        if args.id in set(state.get("used_ids", [])) and not args.force:
            sys.exit(f"Script id {args.id} was already made — refusing to build a "
                     f"duplicate (YouTube penalizes reused content). "
                     f"Use --force only if you really want a second cut.")
    else:
        items = pick_items(content, state, args.batch)
    print(f"Generating {len(items)} video(s)...\n")

    for i, item in enumerate(items):
        seq = len(state.get("used_ids", [])) + 1  # global 1-based number
        out, dur = build_video(item, content, seq, bg_pool)
        state.setdefault("used_ids", []).append(item["id"])
        save_json(STATE, state)
        print(f"  [{i+1}/{len(items)}] {os.path.relpath(out, HERE)}  ({dur:.1f}s)")

    print(f"\nDone. {len(items)} file(s) in ./output/ — ready to upload.")


if __name__ == "__main__":
    main()
