#!/usr/bin/env python3
"""
metadata.py — auto-writes the title, description and Instagram caption for
every video, and keeps library.json (the upload tracker) in sync.

  python3 metadata.py --sync     # scan output/, generate metadata for new videos
  python3 metadata.py --show     # print everything ready to copy-paste

Links (Gumroad/Linktree/affiliate) are read from links.json — fill it once and
every future description includes them automatically.
"""

import argparse
import glob
import json
import os
import re
from datetime import datetime

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
_P = _paths.paths(None)
CONTENT = _P["content"]
LIBRARY = _P["library"]
LINKS = _P["links"]
OUTPUT = _P["output"]
CHANNEL = _paths.DEFAULT_CHANNEL

EMOJI = ["🔥", "💪", "⚡", "🧠", "🚀", "🏆", "⏳", "📈"]

# Per-niche hashtag sets. metadata picks the set matching the active channel.
TAGS_BY_NICHE = {
    "motivation": {
        "yt": [
            "#Shorts #motivation #discipline #mindset",
            "#Shorts #motivation #selfimprovement #successmindset",
            "#Shorts #motivation #hardwork #nevergiveup",
            "#Shorts #motivation #mindset #success",
            "#Shorts #motivation #discipline #selfimprovement",
        ],
        "ig": [
            "#motivation #discipline #mindset #selfimprovement #dailymotivation",
            "#motivation #successmindset #grindset #selfgrowth #mindsetrefuel",
            "#motivation #nevergiveup #hardwork #discipline #motivationdaily",
        ],
        "desc": "#shorts #motivation #discipline #success #mindset",
    },
    "everyday-english": {
        "yt": [
            "#Shorts #English #learnenglish #speakenglish",
            "#Shorts #English #vocabulary #fluency",
            "#Shorts #English #grammar #communication",
            "#Shorts #English #spokenenglish #englishtips",
            "#Shorts #English #speakfluent #learnenglish",
        ],
        "ig": [
            "#english #learnenglish #vocabulary #speakenglish #englishtips",
            "#english #grammar #fluency #spokenenglish #speakfluent",
            "#english #communication #englishlearning #dailyenglish #esl",
        ],
        "desc": "#shorts #english #learnenglish #speakenglish #fluency",
    },
    "did-you-know-facts": {
        "yt": [
            "#Shorts #facts #didyouknow #science",
            "#Shorts #facts #history #interesting",
            "#Shorts #facts #sciencefacts #mindblown",
            "#Shorts #facts #didyouknow #history",
            "#Shorts #facts #funfacts #knowledge",
        ],
        "ig": [
            "#facts #didyouknow #science #history #mindblown",
            "#facts #funfacts #sciencefacts #interesting #knowledge",
            "#facts #historyfacts #didyouknow #trivia #mindblownfacts",
        ],
        "desc": "#shorts #facts #didyouknow #science #history",
    },
}


def _niche():
    return _paths.channel_meta(CHANNEL).get("niche", "motivation")


def _tags():
    return TAGS_BY_NICHE.get(_niche(), TAGS_BY_NICHE["motivation"])

# Pinned first comment for every video. Comments are a strong ranking signal
# and the channel has ZERO — an either/or question is the cheapest way to start.
# Auto-posted when auto-upload is on; otherwise copy it from the mission card.
THEME_PINS = {
    "discipline": "Honest answer: discipline or motivation — which one runs your life right now? 👇",
    "starting": "What's the ONE thing you keep putting off? Type it here — make it real. 👇",
    "consistency": "Day 1 or one day? Comment which one you're choosing. 👇",
    "focus": "How many hours did your phone steal from you today? Be honest. 👇",
    "self-belief": "Type 'I'm built for this' if you needed to hear it today. 🔥",
    "hard work": "Talent or work ethic — which one wins in the long run? Defend your answer. 👇",
    "comeback": "What setback are you coming back from? Someone here needs your story. 👇",
    "doubt": "Whose doubt hurt more — other people's, or your own? 👇",
}
GENERIC_PINS = [
    "Which line hit you hardest? Quote it below. 👇",
    "Rate your discipline this week: 1-10. No lying. 👇",
    "Tag the person who needs to hear this today.",
    "What are you working on right now? Say it publicly. 👇",
]

# Per-niche engagement pins for the new channels.
PINS_BY_NICHE = {
    "everyday-english": [
        "Which phrase will you use today? Type it below 👇",
        "What English word do you always forget? Drop it here 👇",
        "Save this and use one line in a real conversation today.",
        "Repeat the tricky line out loud — then comment 'done' ✅",
    ],
    "did-you-know-facts": [
        "Did you already know this one? Yes or no 👇",
        "Comment a fact you think will surprise us 👇",
        "Tag someone who won't believe this.",
        "Which fact blew your mind the most? 👇",
    ],
}


def pin_comment_from(lines, theme, n):
    """One engagement-bait question per video: theme-matched, else rotated."""
    niche = _niche()
    if niche in PINS_BY_NICHE:
        return PINS_BY_NICHE[niche][n % len(PINS_BY_NICHE[niche])]
    return (THEME_PINS.get((theme or "").strip().lower())
            or GENERIC_PINS[n % len(GENERIC_PINS)])


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def title_from(lines, n):
    """Build a <=95 char title from the hook lines."""
    hook = lines[0].rstrip(".,;: ")
    if len(hook) < 28 and len(lines) > 1:
        second = lines[1].rstrip(".,;: ")
        joined = f"{hook} {second}"
        if len(joined) <= 55:
            hook = joined
    emoji = EMOJI[n % len(EMOJI)]
    yt = _tags()["yt"]
    tags = yt[n % len(yt)].split()
    title = f"{hook} {emoji} " + " ".join(tags)
    while len(title) > 99 and tags:
        tags.pop()                       # drop whole hashtags, never cut mid-tag
        title = f"{hook} {emoji} " + " ".join(tags)
    return title[:99]


def _channel_bits():
    """(handle, follow-line, product-line) tuned per channel."""
    meta = _paths.channel_meta(CHANNEL)
    handle = meta.get("handle", "@mindsetrefuel")
    cont = load(CONTENT, {})
    name = cont.get("channel_name", meta.get("name", "this channel"))
    niche = _niche()
    if niche == "everyday-english":
        follow = f"🔔 Subscribe to {handle} — one English tip every single day."
        prompt = "💬 Which phrase will you use today? Tell me below 👇"
    elif niche == "did-you-know-facts":
        follow = f"🔔 Subscribe to {handle} — one mind-blowing fact every single day."
        prompt = "💬 Did you already know this? Comment below 👇"
    else:
        follow = f"🔔 Subscribe to {handle} — one hit of motivation every single day."
        prompt = "💬 Which line hit you hardest? Tell me in the comments 👇"
    return handle, name, follow, prompt


def description_from(lines, links):
    first = lines[0].rstrip(".,;: ")
    handle, name, follow, prompt = _channel_bits()
    parts = [f"{first}.", "", follow, prompt]
    if links.get("gumroad"):
        parts.append(f"📲 More resources: {links['gumroad']}")
    if links.get("affiliate"):
        parts.append(f"📘 Recommended: {links['affiliate']}")
    if links.get("linktree"):
        parts.append(f"🔗 Everything: {links['linktree']}")
    parts += ["", _tags()["desc"]]
    return "\n".join(parts)


def ig_caption_from(lines, n, links=None):
    first = lines[0].rstrip(".,;: ")
    ig = _tags()["ig"]
    tags = ig[n % len(ig)]
    handle, name, follow, prompt = _channel_bits()
    bio = ("More in bio 👆\n"
           if (links or {}).get("gumroad") or (links or {}).get("linktree") else "")
    follow_ig = follow.replace("🔔 Subscribe to", "🔔 Follow").replace(" every single day.", ".")
    return (f"{first}. ⚡\n\n{follow_ig}\n"
            f"{prompt}\n"
            f"{bio}\n{tags}")


def sync(quiet=False):
    content = load(CONTENT, {"items": []})
    items = {it["id"]: it for it in content["items"]}
    lib = load(LIBRARY, {"videos": {}})
    links = load(LINKS, {})

    files = sorted(glob.glob(os.path.join(OUTPUT, "*.mp4")))
    added = 0
    for f in files:
        name = os.path.basename(f)
        if name in lib["videos"]:
            continue
        m = re.match(r"(\d+)_([a-z]+\d+)\.mp4", name)   # m001, c008, ai003, …
        if not m:
            continue
        seq, vid = int(m.group(1)), m.group(2)
        item = items.get(vid)
        if not item:
            continue
        lines = item["lines"]
        lib["videos"][name] = {
            "seq": seq,
            "id": vid,
            "theme": item.get("theme", ""),
            "title": title_from(lines, seq),
            "description": description_from(lines, links),
            "ig_caption": ig_caption_from(lines, seq, links),
            "pin_comment": pin_comment_from(lines, item.get("theme", ""), seq),
            "status": "ready",
            "views": 0,
            "created": datetime.now().strftime("%Y-%m-%d"),
        }
        added += 1

    # drop entries whose files were deleted
    gone = [k for k in lib["videos"] if not os.path.exists(os.path.join(OUTPUT, k))]
    for k in gone:
        del lib["videos"][k]

    save(LIBRARY, lib)
    if not quiet:
        print(f"library.json: +{added} new, -{len(gone)} removed, "
              f"{len(lib['videos'])} total")
    return lib


def show():
    lib = load(LIBRARY, {"videos": {}})
    order = sorted(lib["videos"].items(), key=lambda kv: kv[1]["seq"])
    for name, v in order:
        print("=" * 70)
        print(f"FILE   : {name}   [{v['status']}]")
        print(f"TITLE  : {v['title']}")
        print(f"DESC   :\n{v['description']}")
        print(f"IG     :\n{v['ig_caption']}")


def set_channel(channel):
    global CONTENT, LIBRARY, LINKS, OUTPUT, CHANNEL
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    CONTENT, LIBRARY, LINKS, OUTPUT = P["content"], P["library"], P["links"], P["output"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--show", action="store_true")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)
    if a.show:
        show()
    else:
        sync()
