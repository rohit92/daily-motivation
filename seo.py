#!/usr/bin/env python3
"""
seo.py — the search surface every upload has been missing.

Until now `upload_youtube.upload()` sent a snippet with only title, description
and a hardcoded categoryId of 22. No `tags` field at all. All 28 videos on the
three channels went up with zero tags, and every one of them — including the
English-teaching channel and the science-facts channel — was filed under
"People & Blogs".

That shows up in the numbers: of 2,285 lifetime views on the motivation
channel, YT_SEARCH accounted for 26. About one percent. The Shorts feed was
carrying everything, and the Shorts feed forgets you the moment a video cools.
Tags and category are what let a video keep earning views months later, and
they are the difference between "browse" traffic and traffic that compounds.

Tags here are real search phrases, not hashtags. Hashtags belong in the title
and description (metadata.py already does that); the tags field wants the words
someone would actually type into the search box.

  python3 seo.py --show --channel education     # what a video would get
  python3 seo.py --channel facts --theme ocean
"""
import argparse

import paths as _paths

# YouTube's own numbers: 500 characters total across all tags, and any single
# tag over 30 chars is routinely ignored. We stay well under both.
MAX_TAGS_CHARS = 460
MAX_TAG_LEN = 30

# Filing a spoken-English lesson under "People & Blogs" tells YouTube to
# recommend it beside vlogs. Category is a topical routing hint and it was
# wrong on two of the three channels.
CATEGORY_BY_NICHE = {
    "motivation": "22",            # People & Blogs — correct for talking-head motivation
    "everyday-english": "27",      # Education
    "did-you-know-facts": "27",    # Education — the bank spans science AND history
}

# Broad terms: high volume, high competition. These rarely rank on their own but
# they tell YouTube what neighbourhood the video lives in.
BROAD_BY_NICHE = {
    "motivation": ["motivation", "motivational video", "self improvement",
                   "discipline", "mindset", "success mindset"],
    "everyday-english": ["learn english", "spoken english", "english speaking",
                         "english lesson", "speak english fluently",
                         "english for beginners"],
    "did-you-know-facts": ["did you know", "facts", "amazing facts",
                           "interesting facts", "fun facts", "science facts"],
}

# Theme terms: lower volume, far less competition, and much closer to what a
# real person types. This is where a small channel can actually rank.
THEME_TERMS = {
    # --- motivation -------------------------------------------------------
    "discipline": ["self discipline", "how to be disciplined", "discipline over motivation"],
    "startnow": ["how to start", "stop procrastinating", "just start"],
    "consistency": ["how to be consistent", "consistency is key", "daily habits"],
    "focus": ["how to focus", "deep focus", "stop distractions"],
    "doubt": ["self doubt", "overcome self doubt", "believe in yourself"],
    "comeback": ["comeback story", "bounce back", "never give up"],
    "growth": ["personal growth", "self growth", "become better"],
    "comparison": ["stop comparing yourself", "comparison is the thief of joy"],
    "patience": ["be patient", "trust the process", "delayed gratification"],
    "fear": ["overcome fear", "face your fears", "fear of failure"],
    "identity": ["who you are", "self identity", "become that person"],
    "ownership": ["take responsibility", "own your life", "extreme ownership"],
    # --- everyday-english -------------------------------------------------
    "phrases": ["english phrases", "daily english phrases", "common english phrases"],
    "vocabulary": ["english vocabulary", "improve vocabulary", "english words"],
    "grammar": ["english grammar", "grammar mistakes", "common grammar errors"],
    "pronunciation": ["english pronunciation", "how to pronounce", "pronounce correctly"],
    "confidence": ["speak english confidently", "english speaking confidence",
                   "stop being shy in english"],
    "connectors": ["linking words english", "english connectors", "sentence connectors"],
    "smalltalk": ["small talk english", "how to make small talk", "english conversation"],
    "workplace": ["business english", "office english", "english for work"],
    "listening": ["english listening practice", "improve english listening"],
    "idioms": ["english idioms", "common idioms", "idioms meaning"],
    "questions": ["english questions", "how to ask questions in english"],
    "storytelling": ["tell a story in english", "english speaking practice"],
    # --- did-you-know-facts ----------------------------------------------
    "space": ["space facts", "universe facts", "astronomy facts"],
    "history": ["history facts", "historical facts", "unknown history"],
    "animals": ["animal facts", "weird animal facts", "nature facts"],
    "biology": ["human body facts", "biology facts", "body facts"],
    "physics": ["physics facts", "science explained", "how things work"],
    "geography": ["geography facts", "world facts", "country facts"],
    "ocean": ["ocean facts", "deep sea facts", "marine facts"],
    "sleep": ["sleep facts", "why we sleep", "dream facts"],
    "food": ["food facts", "weird food facts", "food science"],
    "technology": ["technology facts", "tech facts", "invention facts"],
    "weather": ["weather facts", "storm facts", "climate facts"],
    "psychology": ["psychology facts", "human behavior", "mind facts"],
}

FORMAT_TAGS = ["shorts", "youtube shorts"]
LONGFORM_FORMAT_TAGS = ["explained", "deep dive"]


def _brand_tags(channel):
    """The channel's own name and handle, so 'Speak Fluent' finds Speak Fluent."""
    meta = _paths.channel_meta(channel)
    out = []
    name = (meta.get("name") or "").strip()
    if name:
        out.append(name.lower())
        # 'speakfluent' as one word: how people actually type a channel name
        squashed = name.lower().replace(" ", "")
        if squashed != name.lower():
            out.append(squashed)
    handle = (meta.get("handle") or "").lstrip("@").strip()
    if handle:
        # Handles carry separators and often a random uniqueness suffix
        # (@mind_blown-t2h). Nobody searches "mind_blown-t2h"; they'd type
        # "mind blown". Normalise the separators and drop the junk token.
        parts = [p for p in handle.lower().replace("_", " ").replace("-", " ").split()
                 if not (len(p) <= 3 and any(c.isdigit() for c in p))]
        if parts:
            out.append(" ".join(parts))
    return out


def category_id(channel):
    niche = _paths.channel_meta(channel).get("niche", "motivation")
    return CATEGORY_BY_NICHE.get(niche, "22")


def tags_for(channel, theme=None, longform=False, title=""):
    """The tag list for one video: brand, theme, broad, format — in that order.

    Ordering matters because YouTube weights earlier tags more, and because the
    500-char cap means the tail gets cut. Specific-and-winnable goes first;
    broad-and-competitive goes last, where losing it costs least.
    """
    niche = _paths.channel_meta(channel).get("niche", "motivation")
    tags = []
    tags += _brand_tags(channel)
    tags += THEME_TERMS.get((theme or "").strip().lower(), [])
    tags += BROAD_BY_NICHE.get(niche, BROAD_BY_NICHE["motivation"])
    tags += LONGFORM_FORMAT_TAGS if longform else FORMAT_TAGS

    # Pull two content words out of the title. These are the only tags that can
    # match the exact phrasing of this specific video.
    for word in _title_terms(title):
        if word not in tags:
            tags.append(word)

    return _fit(tags)


_STOP = {"the", "a", "an", "and", "or", "but", "you", "your", "youre", "i", "im",
         "is", "are", "was", "were", "be", "to", "of", "in", "on", "it", "its",
         "this", "that", "for", "with", "at", "by", "from", "not", "no", "do",
         "does", "did", "have", "has", "will", "wont", "can", "cant", "just",
         "how", "what", "why", "when", "shorts", "more", "than", "then", "they",
         "them", "he", "she", "his", "her", "we", "us", "our", "one", "get"}


def _title_terms(title):
    """Two-word phrases from the title, minus hashtags and filler."""
    import re
    clean = re.sub(r"#\w+", " ", title or "")
    clean = re.sub(r"[^\w\s]", " ", clean).lower()
    words = [w for w in clean.split() if w not in _STOP and len(w) > 2]
    return [" ".join(words[i:i + 2]) for i in range(0, min(len(words), 4), 2)
            if len(words[i:i + 2]) == 2]


# Words too common inside a niche to identify a theme: "motivation" appears in
# half the motivation titles and tells us nothing about which theme it is.
_GENERIC = {"english", "motivation", "facts", "fact", "shorts", "speak",
            "learn", "know", "life", "day", "today", "people", "make", "makes"}


def guess_theme(channel, title):
    """Best-guess theme from a title, for videos with no theme on record.

    The back catalogue predates theme tracking, so a lookup returns nothing for
    most older videos and they fall back to broad tags only — the tags least
    likely to ever rank. Matching the title against each theme's own search
    terms recovers the specific ones.
    """
    import re
    # Strip hashtags first. metadata.py appends a rotating hashtag set that has
    # nothing to do with this video's theme — leaving them in made half the
    # motivation catalogue guess "discipline" purely off a trailing #discipline.
    clean = re.sub(r"#\w+", " ", title or "")
    words = set(re.sub(r"[^\w\s]", " ", clean.lower()).split())
    words = {w for w in words if len(w) > 3 and w not in _STOP and w not in _GENERIC}
    if not words:
        return ""

    try:
        import script_composer as sc
        sc.set_channel(channel)
        themes = [t for t in sc.BANK if t in THEME_TERMS]
    except Exception:
        themes = list(THEME_TERMS)

    best, best_score = "", 0
    for theme in themes:
        vocab = set()
        for term in [theme] + THEME_TERMS.get(theme, []):
            vocab |= {w for w in term.lower().split()
                      if len(w) > 3 and w not in _STOP and w not in _GENERIC}
        # Prefix match so "started"/"starting" both hit "start", and
        # "failure"/"failing" both hit "fail".
        score = sum(1 for w in words for v in vocab
                    if w.startswith(v[:5]) or v.startswith(w[:5]))
        if score > best_score:
            best, best_score = theme, score
    return best if best_score else ""


def _fit(tags):
    """Dedupe, drop over-long tags, and stop at YouTube's 500-char budget."""
    out, seen, used = [], set(), 0
    for t in tags:
        t = t.strip().lower()
        if not t or t in seen or len(t) > MAX_TAG_LEN:
            continue
        # YouTube counts a comma between tags; a tag containing a space is
        # quoted, costing two more characters.
        cost = len(t) + 1 + (2 if " " in t else 0)
        if used + cost > MAX_TAGS_CHARS:
            break
        out.append(t)
        seen.add(t)
        used += cost
    return out


# --- channel-level ------------------------------------------------------
# All three channels have an empty description and empty keywords. The channel
# description is what YouTube reads to decide what the CHANNEL is about — it
# feeds the recommendation of every video on it, and it is the first thing a
# human sees when they tap the avatar deciding whether to subscribe.

CHANNEL_ABOUT = {
    "motivation": (
        "Short, honest motivation — no hype, no fluff.\n\n"
        "Every day: one idea about discipline, focus and getting back up, in "
        "under a minute. Longer breakdowns every week.\n\n"
        "If you're building something and it's taking longer than you thought, "
        "you're in the right place.\n\n"
        "🔔 Subscribe — one hit of motivation every single day."),
    "everyday-english": (
        "Speak English with confidence — one lesson a day, under a minute.\n\n"
        "Real phrases people actually use at work, in conversation and online. "
        "No textbook grammar drills, no complicated rules. Just the English "
        "that gets you understood.\n\n"
        "Perfect if you can read English well but freeze when it's time to "
        "speak.\n\n"
        "🔔 Subscribe — one English tip every single day."),
    "did-you-know-facts": (
        "True facts that sound made up.\n\n"
        "One surprising, verified fact a day — space, the ocean, the human "
        "body, history and the strange edges of science. Every claim is "
        "checked before it goes out.\n\n"
        "🔔 Subscribe — one mind-blowing fact every single day."),
}

# The `keywords` field on brandingSettings: channel-wide search terms. Space
# separated, quoted when a phrase, 500 chars total.
CHANNEL_KEYWORDS = {
    "motivation": ["motivation", "motivational shorts", "self improvement",
                   "discipline", "mindset", "success", "personal growth",
                   "daily motivation", "self discipline", "motivational speech"],
    "everyday-english": ["learn english", "spoken english", "english speaking",
                         "english lesson", "speak english fluently",
                         "english vocabulary", "english grammar", "esl",
                         "english for beginners", "daily english"],
    "did-you-know-facts": ["did you know", "facts", "amazing facts",
                           "science facts", "interesting facts", "fun facts",
                           "history facts", "space facts", "trivia",
                           "mind blowing facts"],
}


def channel_about(channel):
    niche = _paths.channel_meta(channel).get("niche", "motivation")
    return CHANNEL_ABOUT.get(niche, CHANNEL_ABOUT["motivation"])


def channel_keywords(channel):
    """Space-separated, phrases quoted — the format the API expects."""
    niche = _paths.channel_meta(channel).get("niche", "motivation")
    words = CHANNEL_KEYWORDS.get(niche, CHANNEL_KEYWORDS["motivation"])
    out, used = [], 0
    for w in words:
        piece = f'"{w}"' if " " in w else w
        if used + len(piece) + 1 > 480:
            break
        out.append(piece)
        used += len(piece) + 1
    return " ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default=None)
    ap.add_argument("--longform", action="store_true")
    ap.add_argument("--title", default="")
    ap.add_argument("--show", action="store_true")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()

    tags = tags_for(a.channel, a.theme, a.longform, a.title)
    budget = sum(len(t) + 1 + (2 if " " in t else 0) for t in tags)
    print(f"channel : {a.channel}  (category {category_id(a.channel)})")
    print(f"theme   : {a.theme or '—'}")
    print(f"tags    : {len(tags)} tags, {budget}/{MAX_TAGS_CHARS} chars")
    for t in tags:
        print(f"          · {t}")
    if a.show:
        print(f"\nchannel keywords: {channel_keywords(a.channel)}")
        print(f"\nchannel about:\n{channel_about(a.channel)}")


if __name__ == "__main__":
    main()
