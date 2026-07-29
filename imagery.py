#!/usr/bin/env python3
"""
imagery.py — a large, topic-tagged, copyright-safe image library.

The problem this fixes: every video on every channel rendered the same animated
gradient (animated_bg), tinted by the channel's brand colour. A facts video
saying "an octopus has three hearts" showed a spiral gradient. The fallback was
20 shared Picsum photos chosen at random — landscape stock shots with no
relationship to what the narrator was saying, repeating across all three
channels.

For a facts channel especially, the image IS the payload. Someone stops
scrolling because they see an octopus, then stays for the sentence about it.

LICENCE POLICY — deliberately strict, because these channels want monetization:
we take PUBLIC DOMAIN and CC0 only by default. No attribution obligation, no
share-alike, nothing that can turn into a copyright strike later. CC BY is
available behind --allow-by, and when used the attribution is recorded in the
manifest so it can be printed into the video description.

Sources, both keyless and free:
  * Wikimedia Commons — enormous, well-labelled, mostly PD/CC0. Best for facts:
    real photographs of the actual animal, place or object.
  * Openverse (openverse.org) — indexes CC-licensed images across Flickr,
    museums and more.

  python3 imagery.py --stock --channel facts      # fill every theme
  python3 imagery.py --theme ocean --count 40
  python3 imagery.py --status
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_ROOT = os.path.join(HERE, "assets", "images")
MANIFEST = os.path.join(IMG_ROOT, "manifest.json")

UA = "faceless-shorts/1.0 (personal channel tooling; contact via YouTube)"
TIMEOUT = 25

# Licences we accept without any obligation attached.
FREE = {"cc0", "public domain", "pd", "cc pd", "no restrictions",
        "publicdomain", "cc-zero"}
# Accepted only with --allow-by; requires crediting the author.
ATTRIB = {"cc by", "cc-by", "attribution"}

# What to actually search for, per theme. A theme name alone is a poor query —
# "biology" returns textbook diagrams; "octopus", "jellyfish" return the images
# that stop a thumb. These are the visual nouns behind each theme.
THEME_QUERIES = {
    # --- facts ---------------------------------------------------------
    "ocean": ["octopus", "jellyfish", "coral reef", "deep sea creature",
              "whale underwater", "sea turtle", "manta ray"],
    "space": ["galaxy", "nebula", "saturn planet", "solar eclipse",
              "milky way night sky", "astronaut spacewalk", "mars surface"],
    "animals": ["flamingo", "chameleon", "arctic fox", "hummingbird",
                "elephant herd", "wolf", "owl closeup"],
    "biology": ["human anatomy illustration", "neuron", "dna helix",
                "human heart anatomy", "microscope cells", "human skeleton"],
    "history": ["ancient egypt pyramid", "roman colosseum", "medieval castle",
                "ancient greek temple", "viking ship", "great wall of china"],
    "physics": ["lightning storm", "prism light spectrum", "gears mechanism",
                "vortex water", "magnet iron filings", "pendulum"],
    "geography": ["mountain range aerial", "desert dunes", "volcano eruption",
                  "world map old", "glacier", "waterfall aerial"],
    "sleep": ["night sky stars", "moon over clouds", "bedroom night",
              "dreaming abstract", "owl at night"],
    "food": ["honey jar", "coffee beans", "chili peppers", "bread baking",
             "spices market", "chocolate"],
    "technology": ["circuit board", "vintage computer", "satellite orbit",
                   "robot arm", "fiber optics", "server room"],
    "weather": ["thunderstorm", "tornado", "snowflake macro", "hurricane satellite",
                "rainbow after rain", "fog forest"],
    "psychology": ["human brain model", "optical illusion", "mirror reflection",
                   "crowd of people", "maze aerial"],
    # --- education (abstract; scenes of people communicating) ----------
    "smalltalk": ["two people talking cafe", "handshake meeting", "conversation friends"],
    "workplace": ["office meeting", "business handshake", "coworking space"],
    "listening": ["headphones listening", "podcast microphone", "person listening"],
    "idioms": ["open book pages", "library books", "dictionary page"],
    "questions": ["question mark chalkboard", "raised hand classroom"],
    "storytelling": ["storytelling campfire", "open storybook", "theatre stage"],
    "phrases": ["speech bubbles", "conversation chat", "notebook writing"],
    "vocabulary": ["dictionary open", "letter blocks", "writing notebook"],
    "grammar": ["red pen correction", "chalkboard writing", "notebook grammar"],
    "pronunciation": ["mouth speaking closeup", "microphone studio", "sound waves"],
    "confidence": ["public speaking stage", "confident person portrait", "presentation"],
    "connectors": ["chain links", "bridge connection", "puzzle pieces joining"],
    # --- motivation (mood; abstract effort and perseverance) -----------
    "discipline": ["mountain climber summit", "running at dawn", "gym weights"],
    "startnow": ["sunrise horizon", "starting line track", "open road"],
    "consistency": ["stairs upward", "rowing team", "calendar marked"],
    "focus": ["archery target", "chess board", "telescope"],
    "doubt": ["fog path forest", "crossroads sign", "storm clouds"],
    "comeback": ["sunrise after storm", "phoenix fire", "climber reaching top"],
    "growth": ["seedling sprout", "tree growth", "plant growing soil"],
    "comparison": ["mirror reflection", "two paths forest", "crowd silhouette"],
    "patience": ["hourglass", "bamboo forest", "slow river"],
    "fear": ["cliff edge", "dark tunnel light", "storm ocean waves"],
    "identity": ["silhouette sunset", "mask", "portrait shadow"],
    "ownership": ["hands holding compass", "steering wheel road", "captain ship"],
}


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _json(url):
    return json.loads(_get(url).decode("utf-8", "replace"))


def _ok_license(text, allow_by=False):
    """Is this licence safe to put in a monetized video?

    Rejects NC (non-commercial) and ND (no-derivatives) outright, and also SA
    (share-alike): embedding a share-alike image arguably makes the finished
    video a derivative that must itself be licensed share-alike, which is not a
    commitment to make quietly on someone's channel. Plain CC BY and public
    domain are the safe set.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(k in t for k in FREE):
        return True
    if not allow_by:
        return False
    if "-sa" in t or " sa " in t or t.endswith(" sa"):
        return False
    if "-nc" in t or "-nd" in t or "noncommercial" in t or "noderiv" in t:
        return False
    return any(k in t for k in ATTRIB)


def search_wikimedia(query, limit=20, allow_by=False):
    """Wikimedia Commons: the best source of real, correctly-labelled photos."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": str(limit),
        "gsrnamespace": "6", "prop": "imageinfo",
        "iiprop": "url|extmetadata|size", "iiurlwidth": "1400",
    })
    try:
        data = _json(f"https://commons.wikimedia.org/w/api.php?{params}")
    except Exception:
        return []
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        for info in page.get("imageinfo", []) or []:
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
            if not _ok_license(lic, allow_by):
                continue
            w, h = info.get("width", 0), info.get("height", 0)
            if w < 800 or h < 600:
                continue           # too small to fill a 1080x1920 frame
            out.append({
                "url": info.get("thumburl") or info.get("url"),
                "title": page.get("title", ""),
                "license": lic,
                "artist": _strip_html((meta.get("Artist", {}) or {}).get("value", "")),
                "source": "wikimedia",
                "page": info.get("descriptionurl", ""),
            })
    return out


def search_openverse(query, limit=20, allow_by=False):
    lic = "cc0,pdm" + (",by" if allow_by else "")
    params = urllib.parse.urlencode({
        "q": query, "license": lic, "page_size": str(limit),
        "mature": "false",
    })
    try:
        data = _json(f"https://api.openverse.org/v1/images/?{params}")
    except Exception:
        return []
    out = []
    for r in data.get("results", []) or []:
        if (r.get("width") or 0) < 800:
            continue
        out.append({
            "url": r.get("url"),
            "title": r.get("title", ""),
            "license": r.get("license", ""),
            "artist": r.get("creator", ""),
            "source": "openverse",
            "page": r.get("foreign_landing_url", ""),
        })
    return out


# Title words that mean the picture is about something else that merely
# involves the subject — a shrimp BOAT, a shrimp DISH, a bird eating one.
_WRONG_CONTEXT = ("boat", "ship", "restaurant", "dish", "recipe", "cooking",
                  "cooked", "fried", "market", "plate", "salad", "soup",
                  "farm", "factory", "logo", "sign", "stamp", "coin", "map of",
                  "postcard", "hotel", "statue", "monument", "museum label")


def _relevance(hit, head):
    """Lower is better. Subject named in the title wins; wrong context loses."""
    title = (hit.get("title") or "").lower()
    score = 0 if head and head in title else 2
    if any(w in title for w in _WRONG_CONTEXT):
        score += 3
    return score


def _strip_html(s):
    import re
    return re.sub(r"<[^>]+>", "", s or "").strip()[:120]


def load_manifest():
    if os.path.exists(MANIFEST):
        try:
            return json.load(open(MANIFEST))
        except Exception:
            pass
    return {"images": {}}


def save_manifest(m):
    os.makedirs(IMG_ROOT, exist_ok=True)
    json.dump(m, open(MANIFEST, "w"), indent=1)


def _prepare(raw_bytes, dest):
    """Crop to 9:16 and save. Returns False if the image is unusable.

    Stored oversized (1350x2400) on purpose: the Ken Burns move in make_video
    zooms in, and zooming a frame-sized image just magnifies its pixels.
    """
    try:
        from PIL import Image, ImageOps
        import io
        im = Image.open(io.BytesIO(raw_bytes))
        im = ImageOps.exif_transpose(im).convert("RGB")
        if min(im.size) < 500:
            return False
        im = ImageOps.fit(im, (1350, 2400), method=Image.LANCZOS, centering=(0.5, 0.4))
        # Captions are white. Museum scans and scientific plates are often on
        # near-white paper, which would render the words invisible — and those
        # are exactly the images worth keeping for a facts channel. Darken the
        # bright ones instead of discarding them.
        from PIL import ImageEnhance, ImageStat
        mean = sum(ImageStat.Stat(im.convert("L")).mean) / 1.0
        if mean > 150:
            # Scale toward a target mean so text keeps its contrast.
            im = ImageEnhance.Brightness(im).enhance(max(0.45, 150.0 / mean))
        im.save(dest, "JPEG", quality=88, optimize=True)
        return True
    except Exception:
        return False


def fetch_theme(theme, count=30, allow_by=False, queries=None, quiet=False):
    """Fill one theme's folder up to `count` images."""
    qs = queries or THEME_QUERIES.get(theme) or [theme]
    out_dir = os.path.join(IMG_ROOT, theme)
    os.makedirs(out_dir, exist_ok=True)
    have = len([f for f in os.listdir(out_dir) if f.endswith(".jpg")])
    if have >= count:
        if not quiet:
            print(f"  {theme:<14} already has {have} — skipping")
        return 0

    man = load_manifest()
    seen_urls = {v.get("url") for v in man["images"].values()}
    added = 0
    for q in qs:
        if have + added >= count:
            break
        hits = search_wikimedia(q, limit=25, allow_by=allow_by)
        hits += search_openverse(q, limit=25, allow_by=allow_by)
        random.shuffle(hits)
        # A search for "shrimp" happily returns "Egrets eating shrimp" — the
        # word matches, the picture is a bird. Prefer images whose own title
        # names the subject, so the frame shows the thing being talked about.
        head = (q.split() or [""])[0].lower().rstrip("s")
        hits.sort(key=lambda h: _relevance(h, head))
        for h in hits:
            if have + added >= count:
                break
            if not h["url"] or h["url"] in seen_urls:
                continue
            # basename, not `theme`: subject keys look like "_subjects/shrimp",
            # and a slash here silently built a path whose parent didn't exist,
            # so every save failed and the folder stayed empty.
            stem = os.path.basename(theme.rstrip("/")) or "img"
            name = f"{stem}_{have + added + 1:03d}.jpg"
            dest = os.path.join(out_dir, name)
            try:
                raw = _get(h["url"])
            except Exception:
                continue
            if len(raw) < 8000 or not _prepare(raw, dest):
                continue
            seen_urls.add(h["url"])
            # Manifest key matches credit_block's lookup: last two path parts.
            man["images"][f"{os.path.basename(out_dir)}/{name}"] = {
                "url": h["url"], "license": h["license"], "artist": h["artist"],
                "source": h["source"], "page": h["page"], "query": q,
            }
            added += 1
            time.sleep(0.15)          # be polite to free APIs
    save_manifest(man)
    if not quiet:
        print(f"  {theme:<14} +{added} (now {have + added})")
    return added


def themes_for(channel):
    try:
        import script_composer as sc
        sc.set_channel(channel)
        return sorted(sc.BANK.keys())
    except Exception:
        return sorted(THEME_QUERIES.keys())


def pick(theme, n, rng=None):
    """n image paths for this theme, newest-shuffled. [] when the theme is empty."""
    rng = rng or random
    d = os.path.join(IMG_ROOT, theme or "")
    if not os.path.isdir(d):
        return []
    files = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jpg"))
    if not files:
        return []
    if len(files) >= n:
        return rng.sample(files, n)
    out = list(files)
    while len(out) < n:
        out.append(rng.choice(files))
    return out


# Words that never identify what a fact is ABOUT.
_SUBJ_STOP = {
    "the", "a", "an", "and", "or", "but", "you", "your", "youre", "its", "it",
    "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "at",
    "by", "for", "with", "from", "not", "no", "do", "does", "did", "has",
    "have", "had", "will", "can", "could", "would", "there", "their", "they",
    "them", "this", "that", "these", "those", "than", "then", "more", "most",
    "some", "any", "all", "one", "two", "every", "each", "about", "into",
    "over", "under", "up", "down", "out", "off", "just", "only", "even",
    "still", "also", "very", "much", "many", "own", "same", "other", "new",
    "old", "how", "what", "why", "when", "where", "who", "which", "if", "so",
    "because", "while", "before", "after", "until", "actually", "really",
    "almost", "nearly", "enough", "makes", "make", "made", "take", "takes",
    "get", "gets", "got", "know", "knows", "think", "see", "sees", "look",
    "years", "year", "day", "days", "time", "times", "people", "world",
    "thing", "things", "way", "ways", "fact", "facts", "did",
    # Quantifiers and comparatives. These sit right next to the subject and
    # would otherwise be picked as it — "last woolly" instead of "woolly
    # mammoths", "group flamingos" instead of "flamingos".
    "last", "first", "next", "group", "called", "long", "longer", "longest",
    "big", "bigger", "biggest", "wide", "wider", "small", "smaller", "far",
    "near", "high", "higher", "low", "lower", "deep", "deeper", "half",
    "whole", "full", "real", "true", "best", "worst", "good", "bad", "less",
    "least", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "hundred", "thousand", "million", "billion", "trillion", "boil", "punch",
    "replaces", "grains", "minutes", "seconds", "hours",
}


def subject_terms(lines, limit=3):
    """The thing this script is literally about, from its own words.

    Matching on the theme alone is what put elephants behind a fact about a
    shrimp: the theme was 'animals' and the library answered with animals. The
    hook line names the subject, so read it from there.
    """
    import re
    text = " ".join((lines or [])[:2])
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text)]
    out, seen = [], set()
    for w in words:
        lw = w.lower().strip("'-")
        # "shrimp's" is not a searchable noun; "shrimp" is.
        if lw.endswith("'s") or lw.endswith("s'"):
            lw = lw[:-2].strip("'")
        if len(lw) < 3 or lw in _SUBJ_STOP or lw in seen:
            continue
        seen.add(lw)
        out.append(lw)
        if len(out) >= limit:
            break
    return out


def _slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40] or "misc"


def credit_block(paths):
    """The attribution lines CC BY requires, for the images actually used.

    Public-domain and CC0 images need no credit, so they are left out — a wall
    of unnecessary credits buries the subscribe line for no legal benefit.
    """
    man = load_manifest()["images"]
    out, seen = [], set()
    for p in paths or []:
        key = "/".join(os.path.normpath(p).split(os.sep)[-2:])
        info = man.get(key)
        if not info:
            continue
        lic = (info.get("license") or "").strip()
        if _ok_license(lic, allow_by=False):
            continue                       # PD/CC0 — no obligation
        artist = (info.get("artist") or "Unknown").strip()
        line = f"· {artist} — {lic}"
        if info.get("page"):
            line += f" — {info['page']}"
        if line not in seen:
            seen.add(line)
            out.append(line)
    if not out:
        return ""
    return "Images (CC BY, via Wikimedia Commons / Openverse):\n" + "\n".join(out)


def for_script(lines, theme, n, allow_fetch=True, allow_by=True):
    """Images of what THIS script is about, falling back to its theme.

    Tries a cached per-subject folder first, fetches that subject on demand if
    the network allows, and only then falls back to the broader theme library —
    so a build never fails just because a subject has no pictures.
    """
    terms = subject_terms(lines)
    if not terms:
        return pick(theme, n)

    query = " ".join(terms[:2])
    key = os.path.join("_subjects", _slug(query))
    got = pick(key, n)
    have = len([f for f in os.listdir(os.path.join(IMG_ROOT, key))
                if f.endswith(".jpg")]) if os.path.isdir(os.path.join(IMG_ROOT, key)) else 0

    if have < max(2, n // 2) and allow_fetch:
        # Search the subject on its own and paired with the theme, which
        # disambiguates ("shrimp" alone can return a seafood plate).
        queries = [query, f"{terms[0]} {theme}" if theme else terms[0], terms[0]]
        try:
            fetch_theme(key, count=n, allow_by=allow_by, queries=queries, quiet=True)
        except Exception:
            pass
        got = pick(key, n)

    if len(got) >= max(2, n // 2):
        return got
    themed = pick(theme, n)
    if not got:
        return themed
    # Blend: real subject shots first, theme images to fill the rest.
    merged = got + [p for p in themed if p not in got]
    return merged[:n] if len(merged) >= n else (merged * n)[:n]


def status():
    if not os.path.isdir(IMG_ROOT):
        print("no images yet — run: python3 imagery.py --stock")
        return
    man = load_manifest()
    total = 0
    for theme in sorted(os.listdir(IMG_ROOT)):
        d = os.path.join(IMG_ROOT, theme)
        if not os.path.isdir(d):
            continue
        n = len([f for f in os.listdir(d) if f.endswith(".jpg")])
        total += n
        print(f"  {theme:<16} {n:>4}")
    print(f"  {'TOTAL':<16} {total:>4}   ({len(man['images'])} in manifest)")
    lics = {}
    for v in man["images"].values():
        lics[v.get("license", "?")] = lics.get(v.get("license", "?"), 0) + 1
    if lics:
        print("\n  licences:")
        for k, v in sorted(lics.items(), key=lambda kv: -kv[1]):
            print(f"    {v:>4}  {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", action="store_true", help="fill every theme")
    ap.add_argument("--theme", default=None)
    ap.add_argument("--channel", default=None, help="only this channel's themes")
    ap.add_argument("--count", type=int, default=30, help="images per theme")
    ap.add_argument("--allow-by", action="store_true",
                    help="also accept CC BY (requires crediting the author)")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    try:
        import netcfg
        netcfg.apply()
    except Exception:
        pass

    if a.status:
        return status()
    os.makedirs(IMG_ROOT, exist_ok=True)

    if a.theme:
        fetch_theme(a.theme, a.count, a.allow_by)
        return
    if not a.stock:
        ap.error("give --stock, --theme, or --status")

    themes = (themes_for(a.channel) if a.channel else sorted(THEME_QUERIES))
    print(f"Stocking {len(themes)} theme(s), up to {a.count} images each "
          f"({'PD/CC0 + CC BY' if a.allow_by else 'PD/CC0 only'})…")
    total = 0
    for t in themes:
        try:
            total += fetch_theme(t, a.count, a.allow_by)
        except KeyboardInterrupt:
            print("\ninterrupted")
            break
        except Exception as e:
            print(f"  {t:<14} ! {type(e).__name__}: {str(e)[:70]}")
    print(f"\nAdded {total} image(s). Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()
