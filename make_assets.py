#!/usr/bin/env python3
"""
make_assets.py — generate all the visual assets a channel needs, plus a
sellable digital product. Everything here is original + copyright-safe.

Produces:
  assets/brand/logo.png          800x800  profile picture
  assets/brand/banner.png        2048x1152 YouTube channel banner (safe-area text)
  product/wallpapers/wall_*.png  1080x1920 phone wallpapers (the sellable pack)
  product/discipline_ebook.pdf   a mini-ebook (cover + quotes + CTA)

Change BRAND below to your final channel name, then: python3 make_assets.py
"""

import argparse
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = "MINDSET REFUEL"            # <- your channel name
TAGLINE = "Refuel your mindset, every single day"
HANDLE = "@mindsetrefuel"
ACCENT = (240, 180, 80)            # brand accent colour (per-channel)

# Fall back to a Linux font if the Mac fonts aren't present (CI/sandbox).
def _font(path):
    if os.path.exists(path):
        return path
    for fb in ("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(fb):
            return fb
    return path

FONT_BLACK = _font("/System/Library/Fonts/Supplemental/Arial Black.ttf")
FONT_BOLD = _font("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

BRAND_DIR = os.path.join(HERE, "assets", "brand")
WALL_DIR = os.path.join(HERE, "product", "wallpapers")

TAGLINES = {
    "motivation": "Refuel your mindset, every single day",
    "education": "Speak English with confidence, every day",
    "facts": "One mind-blowing fact, every single day",
}


def set_channel(channel):
    """Point BRAND/HANDLE/ACCENT/BRAND_DIR at `channel` from channels.json."""
    global BRAND, HANDLE, ACCENT, BRAND_DIR, TAGLINE
    m = _paths.channel_meta(channel or _paths.DEFAULT_CHANNEL)
    BRAND = (m.get("category_label") or m.get("name") or BRAND).upper()
    HANDLE = m.get("handle", HANDLE)
    ACCENT = tuple(m.get("brand_color", ACCENT))[:3]
    TAGLINE = TAGLINES.get(m.get("slug"), TAGLINE)
    BRAND_DIR = os.path.join(_paths.paths(channel)["brand"])

# Short, punchy quotes for wallpapers (original / common-domain phrasing)
WALL_QUOTES = [
    "DISCIPLINE\nOVER\nMOTIVATION", "DO IT\nTIRED", "SMALL STEPS\nEVERY DAY",
    "PROVE\nTHEM\nWRONG", "WIN THE\nMORNING", "CONSISTENCY\nBEATS\nTALENT",
    "START NOW\nFIX IT\nLATER", "ONE PERCENT\nBETTER\nDAILY", "SILENCE\nTHE DOUBT",
    "REST\nDON'T QUIT", "BECOME\nUNDENIABLE", "SHOW UP\nANYWAY",
]

# (quote, one-line action) pairs for the ebook
EBOOK = [
    ("Motivation fades. Discipline stays.",
     "Today: do the one thing you're avoiding — before anything else."),
    ("You don't need more time. You need less scrolling.",
     "Today: cut your screen time by 30 minutes and use it to start."),
    ("Small steps, taken daily, become unstoppable.",
     "Today: pick a habit and do the tiniest version of it."),
    ("Doubt kills more dreams than failure ever will.",
     "Today: take one action your doubt told you not to."),
    ("Comfort is where dreams go to sleep.",
     "Today: do one thing slightly outside your comfort zone."),
    ("Show up on the days you least feel like it.",
     "Today: keep your streak alive, even at 50%."),
    ("Compare yourself only to who you were yesterday.",
     "Today: write down one way you improved since last week."),
    ("Rest is part of the plan. Quitting isn't.",
     "Today: rest on purpose — then get back to it tomorrow."),
    ("You are one decision away from a different life.",
     "Today: make that decision. Just begin."),
    ("The comeback is always stronger than the setback.",
     "Today: forgive a past slip and restart, stronger."),
]


def gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def fit(draw, text, font_path, max_w, max_h, start):
    size = start
    while size > 20:
        font = ImageFont.truetype(font_path, size)
        avg = draw.textlength("ABCDEFGHIJ", font=font) / 10
        wchars = max(6, int(max_w / avg))
        lines = []
        for para in text.split("\n"):
            wrapped = textwrap.wrap(para, width=wchars,
                                    break_long_words=False, break_on_hyphens=False)
            lines.extend(wrapped or [""])
        lh = size + int(size * 0.28)
        widest = max((draw.textlength(l, font=font) for l in lines), default=0)
        if widest <= max_w and lh * len(lines) <= max_h:
            return font, lines, lh
        size -= 3
    return font, lines, lh


def draw_center(draw, lines, font, lh, cx, cy, fill=(255, 255, 255), shadow=True):
    total = lh * len(lines)
    y = cy - total // 2
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = cx - w // 2
        if shadow:
            draw.text((x + 3, y + 3), ln, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), ln, font=font, fill=fill)
        y += lh


def accent_line(draw, cx, y, half=70, color=None):
    draw.rectangle([cx - half, y, cx + half, y + 6], fill=color or ACCENT)


def _dark(color, f=0.16):
    """A dark version of the brand colour, for gradient backgrounds."""
    return tuple(int(c * f) for c in color)


def _mid(color, f=0.42):
    return tuple(int(c * f) for c in color)


# ---------- logo ----------
def make_logo():
    S = 800
    img = gradient((S, S), _mid(ACCENT), _dark(ACCENT))
    d = ImageDraw.Draw(img)
    # monogram
    initials = "".join(w[0] for w in BRAND.split()[:2]).upper()
    f = ImageFont.truetype(FONT_BLACK, 300)
    w = d.textlength(initials, font=f)
    d.text(((S - w) / 2 + 4, 190 + 4), initials, font=f, fill=(0, 0, 0))
    d.text(((S - w) / 2, 190), initials, font=f, fill=(255, 255, 255))
    accent_line(d, S // 2, 560, half=110)
    f2 = ImageFont.truetype(FONT_BOLD, 40)
    w2 = d.textlength(BRAND, font=f2)
    d.text(((S - w2) / 2, 600), BRAND, font=f2, fill=(230, 230, 230))
    os.makedirs(BRAND_DIR, exist_ok=True)
    img.save(os.path.join(BRAND_DIR, "logo.png"))


# ---------- banner ----------
def make_banner():
    W, H = 2048, 1152
    img = gradient((W, H), _dark(ACCENT), _mid(ACCENT))
    d = ImageDraw.Draw(img)
    cx, cy = W // 2, H // 2
    # safe area ~1235x338 centered
    f, lines, lh = fit(d, BRAND, FONT_BLACK, 1100, 200, 150)
    draw_center(d, lines, f, lh, cx, cy - 60)
    accent_line(d, cx, cy + 30, half=90)
    tf = ImageFont.truetype(FONT_BOLD, 46)
    tw = d.textlength(TAGLINE, font=tf)
    d.text((cx - tw / 2, cy + 70), TAGLINE, font=tf, fill=(210, 210, 210))
    img.save(os.path.join(BRAND_DIR, "banner.png"))


# ---------- wallpapers (the product) ----------
PALETTES = [
    ((15, 32, 39), (44, 83, 100)), ((26, 42, 108), (46, 20, 55)),
    ((11, 72, 107), (44, 62, 80)), ((22, 34, 42), (58, 96, 115)),
    ((66, 39, 90), (35, 37, 38)), ((31, 28, 44), (67, 67, 67)),
]


def make_wallpapers():
    os.makedirs(WALL_DIR, exist_ok=True)
    W, H = 1080, 1920
    for i, q in enumerate(WALL_QUOTES):
        top, bot = PALETTES[i % len(PALETTES)]
        img = gradient((W, H), top, bot)
        d = ImageDraw.Draw(img)
        f, lines, lh = fit(d, q, FONT_BLACK, 860, 900, 150)
        draw_center(d, lines, f, lh, W // 2, H // 2 - 40)
        accent_line(d, W // 2, H // 2 + (lh * len(lines)) // 2 + 60, half=90)
        wf = ImageFont.truetype(FONT_BOLD, 34)
        ww = d.textlength(BRAND, font=wf)
        d.text(((W - ww) / 2, H - 150), BRAND, font=wf, fill=(255, 255, 255))
        img.save(os.path.join(WALL_DIR, f"wall_{i+1:02d}.png"))


# ---------- ebook ----------
def make_ebook():
    W, H = 1080, 1440
    pages = []

    # cover
    cover = gradient((W, H), (26, 42, 108), (15, 32, 39))
    d = ImageDraw.Draw(cover)
    f, lines, lh = fit(d, "30 DAYS OF\nDISCIPLINE", FONT_BLACK, 900, 500, 130)
    draw_center(d, lines, f, lh, W // 2, 520)
    accent_line(d, W // 2, 760, half=120)
    sf = ImageFont.truetype(FONT_BOLD, 40)
    sub = "A daily pocket guide"
    d.text(((W - d.textlength(sub, font=sf)) / 2, 820), sub, font=sf, fill=(220, 220, 220))
    bf = ImageFont.truetype(FONT_BOLD, 34)
    d.text(((W - d.textlength(BRAND, font=bf)) / 2, H - 120), BRAND, font=bf, fill=(200, 200, 200))
    pages.append(cover)

    # content pages
    for i, (quote, action) in enumerate(EBOOK, 1):
        top, bot = PALETTES[i % len(PALETTES)]
        pg = gradient((W, H), top, bot)
        d = ImageDraw.Draw(pg)
        nf = ImageFont.truetype(FONT_BLACK, 44)
        d.text((90, 90), f"DAY {i}", font=nf, fill=(240, 180, 80))
        qf, qlines, qlh = fit(d, quote, FONT_BLACK, 900, 500, 84)
        draw_center(d, qlines, qf, qlh, W // 2, 560)
        accent_line(d, W // 2, 560 + (qlh * len(qlines)) // 2 + 50, half=80)
        af, alines, alh = fit(d, action, FONT_BOLD, 880, 300, 42)
        draw_center(d, alines, af, alh, W // 2, 900, fill=(235, 235, 235))
        pages.append(pg)

    # closing / CTA
    end = gradient((W, H), (15, 32, 39), (44, 83, 100))
    d = ImageDraw.Draw(end)
    f, lines, lh = fit(d, "KEEP\nGOING.", FONT_BLACK, 900, 500, 150)
    draw_center(d, lines, f, lh, W // 2, 520)
    cf = ImageFont.truetype(FONT_BOLD, 40)
    for j, line in enumerate([f"Follow {HANDLE}", "for daily motivation."]):
        d.text(((W - d.textlength(line, font=cf)) / 2, 820 + j * 60), line, font=cf, fill=(220, 220, 220))
    pages.append(end)

    os.makedirs(os.path.join(HERE, "product"), exist_ok=True)
    out = os.path.join(HERE, "product", "discipline_ebook.pdf")
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=150)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate per-channel brand assets")
    _paths.add_channel_arg(ap)
    ap.add_argument("--logo-only", action="store_true",
                    help="only the logo + banner (skip the motivation product pack)")
    a = ap.parse_args()
    set_channel(a.channel)
    os.makedirs(BRAND_DIR, exist_ok=True)

    print(f"Generating brand assets for {BRAND} ({a.channel})…")
    make_logo()
    make_banner()
    # The wallpaper pack + ebook are the motivation channel's sellable product.
    if a.channel == "motivation" and not a.logo_only:
        print("Generating wallpaper pack...")
        make_wallpapers()
        print("Generating ebook PDF...")
        make_ebook()
    print(f"Done. See {os.path.relpath(BRAND_DIR, HERE)}/")
