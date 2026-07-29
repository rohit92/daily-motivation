#!/usr/bin/env python3
"""
paths.py — the single source of truth for where each channel's files live.

The system started single-channel: every data file (config.json, content.json,
state.json, library.json, links.json, today.json) and the output/ folder sat in
the project root, next to the code. To support 3 channels on ONE codebase we now
keep the CODE and heavy shared ASSETS at the root, but give every channel its own
data folder:

    channels/<slug>/
        config.json  content.json  state.json  library.json
        links.json   today.json    story_plan.json
        output/            # that channel's finished videos
        long_form/         # that channel's weekly long videos
        assets/brand/      # that channel's logo + banner
        yt_token.json      # that channel's OAuth token

SHARED across channels (stay at the root, never duplicated):
    the .py code, assets/backgrounds/, assets/music/, assets/voices/,
    client_secret.json (one OAuth client authorizes all three channels).

Backward compatibility:
    * Every script defaults to the "motivation" channel when --channel is omitted,
      so the existing launchd jobs and `python3 pilot.py` keep working untouched.
    * If channels/motivation/ has not been created yet (fresh checkout), paths()
      transparently falls back to the OLD root locations, so nothing breaks
      mid-migration.

Usage in any script:
    import paths
    P = paths.paths(channel)      # channel may be None -> "motivation"
    content = P["content"]        # absolute path to that channel's content.json
    P["output"]                   # that channel's output dir (already makedirs'd? no — caller mkdirs)
"""

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNELS_DIR = os.path.join(HERE, "channels")
REGISTRY = os.path.join(HERE, "channels.json")

DEFAULT_CHANNEL = "motivation"

# Files that live PER-CHANNEL (moved out of the root during migration).
_PER_CHANNEL_FILES = [
    "config", "content", "state", "library", "links", "today", "story_plan",
    "profile",   # each channel has its own goal/audience/style for coach + scripts
    "trends",    # each channel scans its own niche, not motivation's
]
_FILE_NAMES = {
    "config": "config.json",
    "content": "content.json",
    "state": "state.json",
    "library": "library.json",
    "links": "links.json",
    "today": "today.json",
    "story_plan": "story_plan.json",
    "profile": "profile.json",
    # Per channel, not shared: a facts channel and a motivation channel are not
    # trending on the same things. One global report meant script_composer
    # weighted all three by whatever motivational Shorts were popular, which
    # left the facts channel with every theme at 1.0 — no signal at all.
    "trends": "trends_report.json",
}

# SHARED roots (identical for every channel).
SHARED = {
    "client_secret": os.path.join(HERE, "client_secret.json"),
    "backgrounds": os.path.join(HERE, "assets", "backgrounds"),
    "music": os.path.join(HERE, "assets", "music"),
    "voices": os.path.join(HERE, "assets", "voices"),
}


def _channel_dir(slug):
    return os.path.join(CHANNELS_DIR, slug)


def migrated(slug=DEFAULT_CHANNEL):
    """True once this channel has been migrated into channels/<slug>/."""
    return os.path.isdir(_channel_dir(slug))


def paths(channel=None):
    """Return a dict of absolute paths for `channel` (default 'motivation').

    If channels/<slug>/ exists we use it. If it does NOT yet exist AND the slug
    is the default motivation channel, we fall back to the OLD root locations so
    the system keeps working before/during the migration.
    """
    slug = channel or DEFAULT_CHANNEL
    cdir = _channel_dir(slug)
    use_channel_dir = os.path.isdir(cdir)

    # Legacy fallback: motivation, not yet migrated -> old root layout.
    legacy = (not use_channel_dir) and (slug == DEFAULT_CHANNEL)

    p = {"slug": slug, "root": HERE, "channel_dir": cdir}

    if legacy:
        base = HERE
        p["output"] = os.path.join(HERE, "output")
        p["long_form"] = os.path.join(HERE, "long_form")
        p["brand"] = os.path.join(HERE, "assets", "brand")
        p["yt_token"] = os.path.join(HERE, "assets", "yt_token.json")
    else:
        base = cdir
        p["output"] = os.path.join(cdir, "output")
        p["long_form"] = os.path.join(cdir, "long_form")
        p["brand"] = os.path.join(cdir, "assets", "brand")
        p["yt_token"] = os.path.join(cdir, "yt_token.json")

    for key in _PER_CHANNEL_FILES:
        p[key] = os.path.join(base, _FILE_NAMES[key])

    # merge shared roots (never per-channel)
    p.update(SHARED)
    return p


def load_registry():
    """Return the list of channel dicts from channels.json (or a default)."""
    if os.path.exists(REGISTRY):
        with open(REGISTRY) as f:
            return json.load(f).get("channels", [])
    # Sensible default if the registry is missing.
    return [{"slug": DEFAULT_CHANNEL, "name": "Mindset Refuel",
             "niche": "motivation", "voice": "en-IN-PrabhatNeural",
             "brand_color": [240, 190, 70], "active": True}]


def active_channels():
    return [c for c in load_registry() if c.get("active", True)]


def channel_meta(slug):
    for c in load_registry():
        if c.get("slug") == slug:
            return c
    return {"slug": slug, "name": slug.title(), "niche": slug,
            "voice": "en-US-AndrewNeural", "brand_color": [240, 190, 70],
            "active": True}


def add_channel_arg(ap):
    """Attach the standard --channel argument to an argparse parser."""
    ap.add_argument("--channel", default=DEFAULT_CHANNEL,
                    help="channel slug (motivation|education|facts). "
                         "Defaults to motivation for backward compatibility.")
    return ap


def brand_label(slug):
    """UPPERCASE on-screen brand label for a channel (falls back to name)."""
    m = channel_meta(slug)
    return (m.get("category_label") or m.get("name") or slug).upper()
