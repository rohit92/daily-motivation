#!/usr/bin/env python3
"""
make_longform.py — generate an ORIGINAL long-form (16:9) motivation video.

Why this exists: long-form watch-hours are the second path to monetization
(4,000 hours), and channels that pair Shorts with long-form grow ~41% faster.
make_compilation.py can only stitch Shorts that still exist locally — but you
delete output/ after uploading. This builds a real long video from scratch:

  1. Script: your local AI (Ollama) writes a chaptered talk in your channel's
     voice; with no AI it composes one from your own script bank instead.
  2. Voice: the same neural voice as your Shorts (edge-tts, Piper fallback).
  3. Video: 1920x1080, one background per line with a slow Ken Burns zoom,
     lower-third captions, chapter title cards, quiet music bed.
  4. Extras: a click-worthy thumbnail (JPG), a YouTube title + description with
     real chapter timestamps, an Instagram promo caption, a pinned comment.

  python3 make_longform.py                 # ~4 minute video
  python3 make_longform.py --minutes 8     # longer
  python3 make_longform.py --theme discipline
  python3 make_longform.py --upload        # build, then auto-upload (needs OAuth)

Output: long_form/NN_longform_YYYY-MM-DD.mp4 (+ .jpg thumbnail + _meta.json),
registered in library.json under "longform".
"""

import argparse
import glob
import json
import os
import random
import re
import subprocess
import sys
from datetime import date

from PIL import Image, ImageDraw, ImageFont

import make_video as mv          # reuse the voice pipeline + fonts (one source of truth)

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNEL = _paths.DEFAULT_CHANNEL
_P = _paths.paths(None)
CONTENT = _P["content"]
LIBRARY = _P["library"]
LINKS = _P["links"]
OUT_DIR = _P["long_form"]
WORK = os.path.join(HERE, ".work", "longform", CHANNEL)
BG_DIR = os.path.join(HERE, "assets", "backgrounds")   # shared
MUSIC_DIR = os.path.join(HERE, "assets", "music")      # shared
LOGO = os.path.join(_P["brand"], "logo.png")


def set_channel(channel):
    global CHANNEL, CONTENT, LIBRARY, LINKS, OUT_DIR, WORK, LOGO
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    CONTENT, LIBRARY, LINKS = P["content"], P["library"], P["links"]
    OUT_DIR = P["long_form"]
    WORK = os.path.join(HERE, ".work", "longform", CHANNEL)
    LOGO = os.path.join(P["brand"], "logo.png")
    _refresh_brand()
    # Reuse make_video's voice pipeline, but with THIS channel's voice + fonts.
    try:
        import make_video as mv
        cfg = load(P["config"], {}) or {}
        mv.EDGE_VOICE = cfg.get("voice") or mv.EDGE_VOICE
        mv.LOGO = LOGO
    except Exception:
        pass

W, H = 1920, 1080
FPS = 30
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
       "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]

SECONDS_PER_LINE = 3.6           # rough planning average (speech + pause)

INTRO_LINES = [
    "Give me the next few minutes, and I'll give you a reason to keep going.",
    "No music-video fluff here. Just the truth, chapter by chapter.",
    "Play this while you train, study, or start your day.",
]
# Per-channel branding, refreshed by set_channel(). Defaults keep motivation
# byte-for-byte identical to before the multi-channel refactor.
BRAND_NAME = "Mindset Refuel"
BRAND_LABEL = "MINDSET REFUEL"
BRAND_HANDLE = "@mindsetrefuel"


def _refresh_brand():
    global BRAND_NAME, BRAND_LABEL, BRAND_HANDLE, OUTRO_LINES
    m = _paths.channel_meta(CHANNEL)
    BRAND_NAME = m.get("name", BRAND_NAME)
    BRAND_LABEL = (m.get("category_label") or BRAND_NAME).upper()
    BRAND_HANDLE = m.get("handle", BRAND_HANDLE)
    OUTRO_LINES = [
        "You didn't watch this far by accident.",
        "Pick ONE idea from this video and act on it today.",
        f"Subscribe to {BRAND_NAME} — a brand new video every single day.",
    ]


OUTRO_LINES = [
    "You didn't watch this far by accident.",
    "Pick ONE chapter from this video and act on it today.",
    "Subscribe to Mindset Refuel — one hit of motivation, every single day.",
]


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, data):
    json.dump(data, open(path, "w"), indent=2)


# ---------- script (Ollama / Claude → your own script bank) ----------

def llm_script(minutes, theme):
    """Ask the AI for a chaptered long-form script. Returns dict or None."""
    try:
        import ai_brain
    except Exception:
        return None
    n_chapters = max(3, round(minutes * 60 / SECONDS_PER_LINE / 8))
    prefer = f" Lean into the theme '{theme}'." if theme else ""
    system = ("You write spoken scripts for Mindset Refuel, a faceless YouTube "
              "motivation channel. Punchy, honest, no hype, short lines of 6-12 "
              "words each — every line is one on-screen caption. No hashtags, "
              "no emojis, no stage directions.")
    user = (f"{prefer} Write a {minutes}-minute chaptered motivation talk. "
            f"Return ONLY JSON: {{\"title\":\"video title, max 8 words\","
            f"\"chapters\":[{{\"title\":\"2-4 words\",\"lines\":[\"...\"]}}]}} "
            f"with exactly {n_chapters} chapters of 7-9 lines each.")
    text, _ = ai_brain.llm(system, user, max_tokens=4000)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    chapters = []
    for ch in data.get("chapters", []):
        lines = [str(x).strip() for x in ch.get("lines", []) if str(x).strip()]
        title = str(ch.get("title", "")).strip()
        if title and len(lines) >= 4:
            chapters.append({"title": title[:40], "lines": lines[:10]})
    if len(chapters) < 3:
        return None
    return {"title": str(data.get("title", "")).strip()[:70] or None,
            "chapters": chapters}


def bank_script(minutes, theme):
    """No AI? Build chapters from your own content.json script bank."""
    content = load(CONTENT, {"items": []})
    items = [it for it in content["items"] if len(it.get("lines", [])) >= 4]
    if not items:
        sys.exit("content.json has no usable scripts.")
    n_chapters = max(3, round(minutes * 60 / SECONDS_PER_LINE / 8))
    if theme:
        items.sort(key=lambda it: 0 if theme.lower() in (it.get("theme") or "") else 1)
    # spread across distinct themes where possible
    picked, seen = [], set()
    for it in items:
        th = it.get("theme") or ""
        if th not in seen or len(picked) < len(seen):
            picked.append(it)
            seen.add(th)
        if len(picked) == n_chapters:
            break
    for it in items:                      # top up if themes ran out
        if len(picked) == n_chapters:
            break
        if it not in picked:
            picked.append(it)
    random.shuffle(picked)

    def chapter_title(it):
        th = (it.get("theme") or "").strip()
        if th and th not in ("ai",):
            return th.title()
        try:
            import progress
            return progress._infer_theme(it["lines"][0]).title()
        except Exception:
            return "Keep Going"

    return {"title": None,
            "chapters": [{"title": chapter_title(it), "lines": it["lines"]}
                         for it in picked]}


# ---------- length enforcement (a "6-minute" video must BE ~6 minutes) ----------

WORDS_PER_SEC = 2.4          # edge-tts Andrew on our short lines ≈ 145 wpm
CARD_SEC = 2.2               # average spoken chapter-card segment


def est_seconds(chapters):
    words = sum(len(l.split()) for ch in chapters for l in ch["lines"])
    return words / WORDS_PER_SEC + len(chapters) * CARD_SEC


def _llm_more_chapters(script, n, story):
    """Ask the AI to CONTINUE the script with n more chapters (returns [])."""
    try:
        import ai_brain
    except Exception:
        return []
    so_far = "\n".join(f"- {c['title']}: {c['lines'][0]}"
                       for c in script["chapters"])
    what = ("the STORY — deepen the middle with a setback, a doubt, and a "
            "small win, same narrator voice; do NOT resolve the ending again"
            if story else
            "the motivation talk with NEW angles — no repeated ideas")
    system = ("You write spoken scripts for Mindset Refuel, a faceless YouTube "
              "motivation channel. Punchy, honest, no hype, short lines of "
              "6-12 words each. No hashtags, no emojis, no stage directions.")
    user = (f"Chapters so far:\n{so_far}\n\nWrite {n} MORE chapters continuing "
            f'{what}. Return ONLY JSON: {{"chapters":[{{"title":"2-4 words",'
            f'"lines":["..."]}}]}} with exactly {n} chapters of 7-9 lines each.')
    text, _ = ai_brain.llm(system, user, max_tokens=2500)
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out, have = [], {l for c in script["chapters"] for l in c["lines"]}
    for ch in data.get("chapters", []):
        lines = []
        for x in ch.get("lines", []):
            x = str(x).strip()
            if x and x not in have:
                lines.append(x)
                have.add(x)
        if ch.get("title") and len(lines) >= 4:
            out.append({"title": str(ch["title"]).strip()[:40],
                        "lines": lines[:10]})
    return out


_REFLECT_TITLES = ["What It Means For You", "The First Step", "Make It Stick",
                   "Your Move", "Keep It Burning", "Start Tonight",
                   "The Hard Part", "Read This Twice", "The Quiet Truth",
                   "One Rule", "Before You Go", "Carry It With You"]


def _fresh_title(pool, used):
    """A chapter title that has NOT been used yet (spoken twice = obvious bug)."""
    t = next((t for t in pool if t not in used), None)
    if t:
        return t
    n = 2
    while f"One More Thing {n}" in used:
        n += 1
    return f"One More Thing {n}"


def _bank_more_chapters(script, theme, story, n=2):
    """No AI? Top up from the owner's script bank. For stories the extra
    chapters become the LESSON section (story → what it means → act on it)."""
    content = load(CONTENT, {"items": []})
    have = {l for c in script["chapters"] for l in c["lines"]}
    items = [it for it in content["items"]
             if len(it.get("lines", [])) >= 4
             and not any(l in have for l in it["lines"])]
    if theme:
        items.sort(key=lambda it: 0 if theme.lower() in (it.get("theme") or "") else 1)
    out = []
    used_titles = {c["title"] for c in script["chapters"]}
    for it in items:
        if len(out) == n:
            break
        if any(l in have for l in it["lines"]):
            continue                       # overlaps something already picked
        have.update(it["lines"])
        if story:
            title = _fresh_title(_REFLECT_TITLES, used_titles)
        else:
            th = (it.get("theme") or "").strip()
            title = th.title() if th and th != "ai" else "Keep Going"
            if title in used_titles:
                title = _fresh_title(_REFLECT_TITLES, used_titles)
        used_titles.add(title)
        out.append({"title": title, "lines": it["lines"]})
    return out


def ensure_minutes(script, minutes, theme=None, story=False):
    """Pad the script until it fills ~92% of the target minutes. LLM
    continuation first (keeps the narrative), script bank as the fallback
    that always works. Stories keep their final chapter LAST (the payoff)."""
    target = minutes * 60 * 0.92
    for _ in range(10):
        gap = target - est_seconds(script["chapters"])
        if gap <= 0:
            break
        n = max(1, min(3, round(gap / 30)))       # ~30s per added chapter
        added = _llm_more_chapters(script, n, story)
        if added and story and len(script["chapters"]) > 1:
            script["chapters"][-1:-1] = added      # story grows in the middle,
        elif added:                                # the payoff stays last
            script["chapters"].extend(added)
        else:
            added = _bank_more_chapters(script, theme, story, n)
            if not added:
                break
            script["chapters"].extend(added)       # lessons read after the end
    return script


# ---------- Pillow frames ----------

def _shadow_text(draw, xy, text, font, fill=(255, 255, 255, 255)):
    x, y = xy
    draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 190))
    draw.text((x, y), text, font=font, fill=fill)


def caption_png(line, chapter, out_png):
    """Lower-third caption card for one spoken line (16:9)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font, lines, line_h = mv.fit_text(d, line, mv.FONT_MAIN, 1400, 260, 72)
    block_h = line_h * len(lines)
    top = H - 200 - block_h
    d.rounded_rectangle([W/2 - 760, top - 36, W/2 + 760, H - 160],
                        radius=28, fill=(0, 0, 0, 150))
    y = top - 10
    for ln in lines:
        lw = d.textlength(ln, font=font)
        _shadow_text(d, ((W - lw) / 2, y), ln, font)
        y += line_h
    lab = ImageFont.truetype(mv.FONT_SMALL, 34)
    _shadow_text(d, (80, 60), BRAND_LABEL, lab, fill=(255, 255, 255, 200))
    if chapter:
        cf = ImageFont.truetype(mv.FONT_SMALL, 34)
        t = chapter.upper()
        tw = d.textlength(t, font=cf)
        _shadow_text(d, (W - tw - 80, 60), t, cf, fill=(230, 180, 80, 230))
    img.save(out_png)


def chapter_card_png(num, title, out_png):
    """Full-screen chapter title card."""
    img = Image.new("RGB", (W, H), (11, 14, 21))
    d = ImageDraw.Draw(img)
    for i in range(H):                       # subtle vertical gradient
        v = 11 + int(14 * i / H)
        d.line([(0, i), (W, i)], fill=(v, v + 3, v + 9))
    small = ImageFont.truetype(mv.FONT_SMALL, 44)
    big, lines, line_h = mv.fit_text(d, title.upper(), mv.FONT_MAIN, 1500, 380, 130)
    label = f"CHAPTER {num}" if num else BRAND_LABEL
    lw = d.textlength(label, font=small)
    d.text(((W - lw) / 2, H / 2 - line_h * len(lines) / 2 - 110), label,
           font=small, fill=(230, 180, 80))
    d.rectangle([W/2 - 60, H/2 - line_h*len(lines)/2 - 40,
                 W/2 + 60, H/2 - line_h*len(lines)/2 - 32], fill=(230, 180, 80))
    y = H / 2 - line_h * len(lines) / 2
    for ln in lines:
        tw = d.textlength(ln, font=big)
        d.text(((W - tw) / 2, y), ln, font=big, fill=(238, 241, 247))
        y += line_h
    img.save(out_png)


def thumbnail(title, bg_path, out_jpg):
    """1280x720 thumbnail: darkened background + big hook text + brand."""
    img = Image.open(bg_path).convert("RGB")
    tw, th = 1280, 720
    scale = max(tw / img.width, th / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
    img = img.crop(((img.width - tw) // 2, (img.height - th) // 2,
                    (img.width - tw) // 2 + tw, (img.height - th) // 2 + th))
    dark = Image.new("RGB", (tw, th), (0, 0, 0))
    img = Image.blend(img, dark, 0.55)
    d = ImageDraw.Draw(img)
    words = title.split()
    text = " ".join(words[:7]).upper()
    font, lines, line_h = mv.fit_text(d, text, mv.FONT_MAIN, 1080, 420, 110)
    y = th / 2 - line_h * len(lines) / 2 + 20
    d.rectangle([70, y - 26, 210, y - 12], fill=(230, 180, 80))
    for ln in lines:
        d.text((73, y + 3), ln, font=font, fill=(0, 0, 0))
        d.text((70, y), ln, font=font, fill=(255, 255, 255))
        y += line_h
    lab = ImageFont.truetype(mv.FONT_SMALL, 36)
    d.text((73, 53), BRAND_LABEL, font=lab, fill=(0, 0, 0))
    d.text((70, 50), BRAND_LABEL, font=lab, fill=(230, 180, 80))
    if os.path.exists(LOGO):
        try:
            logo = Image.open(LOGO).convert("RGBA").resize((110, 110))
            img.paste(logo, (tw - 140, 40), logo)
        except Exception:
            pass
    img.save(out_jpg, quality=90)


# ---------- ffmpeg segments ----------

def build_segment(bg, png, wav, dur, out_mp4, fade_in=False, fade_out=False):
    """One encoded 16:9 segment: Ken Burns background + caption + line audio.
    Every segment shares identical codec params so the final concat is -c copy."""
    vf = (f"[0:v]scale=2304:1296:force_original_aspect_ratio=increase,"
          f"crop=2304:1296,"
          f"zoompan=z='min(1.001+0.0008*on,1.10)':d=1:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
          f"eq=brightness=-0.20:saturation=1.10,setsar=1[bg];"
          f"[bg][1:v]overlay=0:0[v0]")
    fades, afades = [], []
    if fade_in:
        fades.append("fade=t=in:st=0:d=0.5")
        afades.append("afade=t=in:st=0:d=0.4")
    if fade_out:
        fades.append(f"fade=t=out:st={max(0, dur - 0.8):.3f}:d=0.8")
        afades.append(f"afade=t=out:st={max(0, dur - 0.8):.3f}:d=0.8")
    vchain = f"[v0]{','.join(fades)}[v]" if fades else None
    fc = vf + (";" + vchain if vchain else "")
    vmap = "[v]" if vchain else "[v0]"
    amap = ["-map", "2:a"]
    if afades:
        fc += f";[2:a]{','.join(afades)}[a]"
        amap = ["-map", "[a]"]
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", bg,
         "-loop", "1", "-t", f"{dur:.3f}", "-i", png, "-i", wav,
         "-filter_complex", fc, "-map", vmap, *amap, "-t", f"{dur:.3f}",
         *ENC, out_mp4],
        check=True, capture_output=True)


def build_card_segment(png, wav, dur, out_mp4):
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", png, "-i", wav,
         "-filter_complex",
         f"[0:v]scale={W}:{H},setsar=1,fade=t=in:st=0:d=0.4[v]",
         "-map", "[v]", "-map", "1:a", "-t", f"{dur:.3f}", *ENC, out_mp4],
        check=True, capture_output=True)


# ---------- metadata ----------

def fmt_ts(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_description(hook, chapter_marks, links,
                      tags="#motivation #discipline #mindset #selfimprovement"):
    parts = [hook, "", "⏱ Chapters:"]
    parts += [f"{fmt_ts(t)} {name}" for t, name in chapter_marks]
    parts += ["",
              f"🔔 Subscribe to {BRAND_HANDLE} — a brand new video every single day.",
              "💬 Which chapter hit you hardest? Tell me in the comments 👇"]
    if links.get("gumroad"):
        parts.append(f"📲 Get the pack: {links['gumroad']}")
    if links.get("affiliate"):
        parts.append(f"📘 Recommended: {links['affiliate']}")
    if links.get("linktree"):
        parts.append(f"🔗 Everything: {links['linktree']}")
    parts += ["", tags]
    return "\n".join(parts)


# ---------- main build ----------

def build(minutes, theme, music_on=True, script=None, kind="longform"):
    """Render a chaptered 16:9 video. `script` may be supplied by a caller
    (storyteller.py passes a full story); kind="story" = cold-open storytelling:
    no generic intro, un-numbered chapter cards, story-specific packaging."""
    mv.need("ffmpeg"); mv.need("ffprobe")
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    for f in glob.glob(os.path.join(WORK, "*")):
        os.remove(f)

    bg_pool = sorted(glob.glob(os.path.join(BG_DIR, "*.jpg")) +
                     glob.glob(os.path.join(BG_DIR, "*.png")))
    if not bg_pool:
        sys.exit(f"No backgrounds in {BG_DIR}. Run fetch_backgrounds.py first.")

    story = kind == "story"
    if script is None:
        script = llm_script(minutes, theme)
        engine = "AI-written"
        if not script:
            script = bank_script(minutes, theme)
            engine = "from your script bank"
    else:
        engine = script.get("engine", "story mode")
    before = len(script["chapters"])
    script = ensure_minutes(script, minutes, theme=theme, story=story)
    if len(script["chapters"]) > before:
        print(f"  · script was short — extended {before} → "
              f"{len(script['chapters'])} chapters to fill {minutes} minutes")
    intro = [] if story else [{"title": "", "lines": INTRO_LINES}]
    chapters = (intro + script["chapters"] +
                [{"title": "One Last Thing", "lines": OUTRO_LINES}])
    print(f"Script ready ({engine}): {len(script['chapters'])} chapters. "
          f"Building segments…")

    segs, chapter_marks, t_cursor = [], [], 0.0
    idx = 0
    total_segments = sum(len(c["lines"]) for c in chapters) + len(chapters) - 1
    for ci, ch in enumerate(chapters):
        # chapter title card (never for the cold open / intro)
        if ci > 0:
            name = ch["title"] or f"Part {ci}"
            chapter_marks.append((t_cursor, name))
            card = os.path.join(WORK, f"card_{ci:02d}.png")
            wav = os.path.join(WORK, f"card_{ci:02d}.wav")
            seg = os.path.join(WORK, f"seg_{idx:03d}.mp4")
            last = ci == len(chapters) - 1
            num = 0 if last else (ci + 1 if story else ci)
            chapter_card_png(num, name, card)
            # stories speak just the beat's title — "Chapter N" breaks the spell
            spoken = name if (story or last) else f"Chapter {ci}. {name}."
            mv.synth_line(spoken, wav)
            dur = mv.duration(wav)
            build_card_segment(card, wav, dur, seg)
            segs.append(seg); t_cursor += dur; idx += 1
        else:
            chapter_marks.append((0.0, ch["title"] if story else "Intro"))
        for li, line in enumerate(ch["lines"]):
            wav = os.path.join(WORK, f"l_{ci:02d}_{li:02d}.wav")
            png = os.path.join(WORK, f"l_{ci:02d}_{li:02d}.png")
            seg = os.path.join(WORK, f"seg_{idx:03d}.mp4")
            mv.synth_line(line, wav)
            dur = mv.duration(wav)
            caption_png(line, ch["title"], png)
            build_segment(random.choice(bg_pool), png, wav, dur, seg,
                          fade_in=(idx == 0),
                          fade_out=(ci == len(chapters) - 1 and
                                    li == len(ch["lines"]) - 1))
            segs.append(seg); t_cursor += dur; idx += 1
            if idx % 10 == 0:
                print(f"  … {idx}/{total_segments} segments")

    # concat (identical codec params → stream copy, fast)
    listfile = os.path.join(WORK, "list.txt")
    with open(listfile, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    base = os.path.join(WORK, "base.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                    "-c", "copy", base], check=True, capture_output=True)

    seq = len(load(LIBRARY, {}).get("longform", {})) + 1
    stem = f"{seq:02d}_{'story' if story else 'longform'}_{date.today().isoformat()}"
    out = os.path.join(OUT_DIR, stem + ".mp4")

    music_pool = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.wav")) +
                        glob.glob(os.path.join(MUSIC_DIR, "*.mp3")))
    total = mv.duration(base)
    if music_on and music_pool:
        subprocess.run(
            ["ffmpeg", "-y", "-i", base, "-stream_loop", "-1", "-i",
             random.choice(music_pool), "-filter_complex",
             f"[1:a]volume=0.08,afade=t=in:st=0:d=2[m];"
             f"[0:a][m]amix=inputs=2:duration=first:normalize=0,"
             f"afade=t=out:st={max(0, total - 2):.3f}:d=2[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out],
            check=True, capture_output=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-i", base, "-c", "copy",
                        "-movflags", "+faststart", out],
                       check=True, capture_output=True)

    # ---------- metadata + thumbnail + registry ----------
    mins = int(total // 60)
    hook = chapters[0]["lines"][0] if story else (
        chapters[1]["lines"][0] if len(chapters) > 1 else "Pure motivation.")
    # niche-aware metadata: a motivation title/hashtag/pin on the English or
    # Facts channel is an instant "this is spam/reused" signal — match the niche.
    niche = _paths.channel_meta(CHANNEL).get("niche", "motivation")
    NICHE_META = {
        "everyday-english": {
            "t2": f"{mins} Minutes to Speak English Better",
            "t1": "The English Boost You Needed Today",
            "tags": "#english #learnenglish #speakenglish #fluency",
            "pin": "Which tip will you use first? 👇 Tell me — I read every comment.",
        },
        "did-you-know-facts": {
            "t2": f"{mins} Minutes of Mind-Blowing Facts",
            "t1": "Facts That Will Break Your Brain Today",
            "tags": "#facts #didyouknow #science #history",
            "pin": "Which fact shocked you most? 👇 Comment — let's compare.",
        },
        "motivation": {
            "t2": f"{mins} Minutes That Will Fix Your Mindset",
            "t1": "The Motivation You Needed Today",
            "tags": "#motivation #discipline #mindset #selfimprovement",
            "pin": None,   # falls through to the theme-matched pin engine
        },
    }
    nm = NICHE_META.get(niche, NICHE_META["motivation"])

    title = script.get("title") or (nm["t2"] if mins >= 2 else nm["t1"])
    brand = f"{BRAND_NAME} Stories" if story else BRAND_NAME
    title = f"{title} | {brand}"[:95]
    links = load(LINKS, {}) or {}
    desc = build_description(hook, chapter_marks, links, nm["tags"])
    what = "story" if story else "video"
    ig = (f"I just posted a full {max(1, mins)}-minute {what} on YouTube: "
          f"\"{title.split('|')[0].strip()}\" 🎥\n\n"
          f"Watch it now — link on my YouTube channel {BRAND_HANDLE}.\n\n"
          f"{nm['tags']}")
    pin = script.get("pin_comment") or nm["pin"]
    if not pin:
        try:
            import metadata as md
            pin = md.pin_comment_from([hook], theme or "motivation", seq)
        except Exception:
            pin = "Which chapter hit you hardest? 👇 Tell me — I read everything."
    thumb = os.path.join(OUT_DIR, stem + ".jpg")
    thumbnail(script.get("thumbnail_text") or title.split("|")[0].strip(),
              random.choice(bg_pool), thumb)

    meta = {"file": os.path.basename(out), "title": title, "description": desc,
            "ig_caption": ig, "pin_comment": pin, "kind": kind,
            "thumb": os.path.basename(thumb), "duration_sec": round(total, 1),
            "chapters": [[round(t, 1), n] for t, n in chapter_marks],
            "created": date.today().isoformat(), "status": "ready",
            "engine": engine}
    save(os.path.join(OUT_DIR, stem + "_meta.json"), meta)
    lib = load(LIBRARY, {"videos": {}})
    lib.setdefault("longform", {})[os.path.basename(out)] = meta
    save(LIBRARY, lib)

    for s in segs + [base]:
        if os.path.exists(s):
            os.remove(s)

    print(f"\n✓ Built {os.path.relpath(out, HERE)}  ({mins}m {int(total % 60)}s, "
          f"{len(chapter_marks)} chapters, {engine})")
    print(f"✓ Thumbnail: {os.path.relpath(thumb, HERE)}")
    print(f"\nTITLE : {title}")
    print(f"\nDESCRIPTION:\n{desc}")
    print(f"\nPINNED COMMENT:\n{pin}")
    return out, meta


def main():
    ap = argparse.ArgumentParser(description="Original long-form video generator")
    ap.add_argument("--minutes", type=float, default=4.0)
    ap.add_argument("--theme", default="")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--upload", action="store_true",
                    help="auto-upload after building (needs one-time Google OAuth)")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)

    out, meta = build(a.minutes, a.theme, music_on=not a.no_music)
    if a.upload:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "upload_youtube.py"),
             "--file", out, "--title", meta["title"], "--desc", meta["description"],
             "--thumb", os.path.join(OUT_DIR, meta["thumb"]),
             "--comment", meta["pin_comment"], "--longform",
             "--channel", CHANNEL],
            cwd=HERE)
        if r.returncode == 0:
            lib = load(LIBRARY, {"videos": {}})
            if meta["file"] in lib.get("longform", {}):
                lib["longform"][meta["file"]]["status"] = "uploaded"
                save(LIBRARY, lib)


if __name__ == "__main__":
    main()
