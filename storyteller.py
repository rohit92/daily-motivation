#!/usr/bin/env python3
"""
storyteller.py — the Story Studio engine (the free version of the
"one prompt → 10-minute faceless video + shorts" workflow).

What it steals from the pros, at ₹0:
  1. TOPIC: scores story archetypes against YOUR retention data + this week's
     trends and picks one (the "research → score → pick" step).
  2. SCRIPT: the local AI writes a real STORY — the hook opens on the payoff,
     every chapter is a beat that ends on a cliffhanger, and an open loop is
     planted roughly every minute (the retention tricks pros get paid for).
     No AI running? A hand-written story bank takes over. Nothing breaks.
  3. VIDEO: rendered by the existing long-form engine (chapter cards, captions,
     your voice, music, thumbnail with a question the title doesn't answer).
  4. SHORTS: the strongest beats become native vertical Shorts — purpose-built
     with karaoke captions, not lazy crops. One story = several uploads.
  5. PLAN: a dated 4-week calendar of what to post, where, and when.

  python3 storyteller.py --make                # this week's story + 2 shorts
  python3 storyteller.py --make --minutes 8 --shorts 3
  python3 storyteller.py --make --upload       # …and publish it (needs Google)
  python3 storyteller.py --plan                # regenerate the 4-week calendar
  python3 storyteller.py --topic               # just show what it would pick
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNEL = _paths.DEFAULT_CHANNEL
_P = _paths.paths(None)
LIBRARY = _P["library"]
CONTENT = _P["content"]
TRENDS = _P["trends"]
CONFIG = _P["config"]
PLAN = _P["story_plan"]
LONGFORM_DIR = _P["long_form"]


def set_channel(channel):
    global CHANNEL, LIBRARY, CONTENT, TRENDS, CONFIG, PLAN, LONGFORM_DIR
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    LIBRARY, CONTENT, TRENDS = P["library"], P["content"], P["trends"]
    CONFIG, PLAN, LONGFORM_DIR = P["config"], P["story_plan"], P["long_form"]


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, data):
    json.dump(data, open(path, "w"), indent=2)


# ---------- 1. topic: archetypes scored against YOUR data ----------
# Each archetype maps to the themes the channel already tracks, so the pick
# leans into what retention proved works (not what merely got views).

ARCHETYPES = [
    {"topic": "The runner who finished last — and why the stadium stood up",
     "themes": ["comeback", "hard work"], "angle": "finishing when winning is gone"},
    {"topic": "The bamboo that took five years to grow one inch",
     "themes": ["consistency", "starting"], "angle": "invisible progress"},
    {"topic": "The janitor who kept a notebook nobody read",
     "themes": ["discipline", "self-belief"], "angle": "working unseen"},
    {"topic": "The boxer who lost every fight for three years",
     "themes": ["comeback", "doubt"], "angle": "losing publicly, learning privately"},
    {"topic": "The student with one hour a day — and the one who had twelve",
     "themes": ["focus", "discipline"], "angle": "constraints beat resources"},
    {"topic": "The old man who planted trees he would never sit under",
     "themes": ["starting", "consistency"], "angle": "starting late is still starting"},
    {"topic": "The message you'd send to yourself one year ago",
     "themes": ["starting", "self-belief"], "angle": "future-regret (your 81% hook)"},
    {"topic": "The blacksmith who struck the stone 100 times",
     "themes": ["consistency", "hard work"], "angle": "the 101st blow"},
]


def pick_topic():
    """Score archetypes: retention-proven themes weigh most, trend hooks help,
    recently-used topics are pushed down. Returns (archetype, reason)."""
    lib = load(LIBRARY, {"videos": {}}) or {}
    ch = lib.get("channel", {})
    an = (ch.get("analytics") or {}).get("videos", {})
    titles = {v["id"]: v.get("title", "") for v in ch.get("live_videos", [])}

    theme_scores = {}
    try:
        import progress
        for vid, d in an.items():                       # retention per theme
            th = progress._infer_theme(titles.get(vid, ""))
            theme_scores[th] = max(theme_scores.get(th, 0), d.get("avg_pct", 0))
        if not theme_scores:
            for t in progress.summary().get("themes", []):
                theme_scores[t["theme"]] = min(70, t["views"] / 10)
    except Exception:
        pass

    hooks = [w for w, _ in (load(TRENDS, {}) or {}).get("hook_words", [])[:10]]
    used = " ".join(m.get("title", "").lower()
                    for m in (lib.get("longform") or {}).values())

    best, best_score, best_why = None, -1, ""
    for a in ARCHETYPES:
        score = sum(theme_scores.get(t, 40) for t in a["themes"]) / len(a["themes"])
        score += sum(3 for w in hooks if w in a["topic"].lower())
        if any(k in used for k in a["topic"].lower().split()[:4]):
            score -= 30                                 # don't repeat a story
        if score > best_score:
            best, best_score = a, score
            best_why = (f"leans on your proven themes "
                        f"({', '.join(a['themes'])}) — {a['angle']}")
    return best, best_why


# ---------- 2. script: AI story with retention engineering ----------

def llm_story(minutes, archetype):
    try:
        import ai_brain
    except Exception:
        return None
    n_chapters = max(4, round(minutes * 60 / 3.6 / 8))
    system = (
        "You write STORY scripts for Mindset Refuel, a faceless motivational "
        "YouTube channel. You are a master of retention: the first line opens "
        "on the PAYOFF or an impossible moment (never backstory); every chapter "
        "is one story beat that ENDS on a cliffhanger or unanswered question "
        "(an open loop, roughly one per minute); the last chapter lands the "
        "lesson in second person ('you'). Short spoken lines, 6-12 words each — "
        "every line is one on-screen caption. Concrete details, no clichés, "
        "no hashtags, no emojis. The story must be ORIGINAL (invented characters, "
        "no real names) but feel true.")
    user = (
        f"Story: {archetype['topic']} (angle: {archetype['angle']}). "
        f"Write a {minutes}-minute chaptered story. Return ONLY JSON:\n"
        f'{{"title":"max 9 words, curiosity gap, no clickbait words like SHOCKING",'
        f'"thumbnail_text":"max 5 punchy words, a question or contradiction",'
        f'"pin_comment":"one engagement question about the story, ends with 👇",'
        f'"chapters":[{{"title":"2-4 words","lines":["..."]}}]}}\n'
        f"Exactly {n_chapters} chapters of 7-9 lines each. The final chapter "
        f'must be titled like a lesson (e.g. "What It Means").')
    text, _ = ai_brain.llm(system, user, max_tokens=4500)
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
    for c in data.get("chapters", []):
        lines = [str(x).strip() for x in c.get("lines", []) if str(x).strip()]
        if c.get("title") and len(lines) >= 4:
            chapters.append({"title": str(c["title"]).strip()[:40],
                             "lines": lines[:10]})
    if len(chapters) < 3:
        return None
    return {"title": str(data.get("title", "")).strip()[:70] or archetype["topic"][:70],
            "thumbnail_text": str(data.get("thumbnail_text", "")).strip()[:40],
            "pin_comment": str(data.get("pin_comment", "")).strip()[:200],
            "chapters": chapters, "engine": "AI story (local, free)"}


# hand-written fallback so story mode works with zero AI, forever
STORY_BANK = [
    {"title": "He Finished Last. The Whole Stadium Stood Up",
     "thumbnail_text": "WHY DID THEY CHEER?",
     "pin_comment": "Would you have finished the race? Be honest. 👇",
     "chapters": [
        {"title": "The Fall", "lines": [
            "Forty thousand people watched him fall.",
            "One hundred and fifty metres from the finish.",
            "His hamstring tore like a snapped cable.",
            "Every other runner crossed the line.",
            "The race was over. Officially.",
            "But he was still on the track.",
            "And then he did something strange."]},
        {"title": "The Choice", "lines": [
            "He got up.",
            "Not to win. Winning was gone.",
            "He got up because the race wasn't.",
            "One leg working, one leg dead weight.",
            "Hopping. Falling. Hopping again.",
            "The medics ran toward him with a stretcher.",
            "He waved them away."]},
        {"title": "The Longest Metres", "lines": [
            "One hundred metres left. It looked like a kilometre.",
            "Every hop sent fire up his leg.",
            "The crowd had gone completely silent.",
            "Forty thousand people, and you could hear him breathing.",
            "He fell again. Face on the track.",
            "The stretcher waited three steps away.",
            "He crawled past it."]},
        {"title": "The Stranger", "lines": [
            "Then a man broke through security.",
            "Pushed past the guards. Ran onto the track.",
            "It was his father.",
            "'You don't have to do this,' he said.",
            "'Yes, I do,' said the son.",
            "'Then we'll finish it together.'",
            "And the stadium rose to its feet."]},
        {"title": "The Finish Line", "lines": [
            "They crossed it arm in arm.",
            "Last place. The slowest time of the day.",
            "No medal. No podium. No anthem.",
            "And the loudest roar of the whole games.",
            "An official tried to stop the father at the line.",
            "He said: 'I started every race with him.'",
            "'I am finishing this one too.'"]},
        {"title": "What It Means", "lines": [
            "Nobody remembers who won that race.",
            "Everybody remembers who finished it.",
            "You will fall. That part is guaranteed.",
            "The plan breaking is not the story ending.",
            "Your race isn't against them.",
            "It's against the version of you that quits.",
            "Get up. Finish. Even ugly. Especially ugly."]}]},
    {"title": "Nothing Grew for Five Years. Then This",
     "thumbnail_text": "5 YEARS. NOTHING.",
     "pin_comment": "What are you watering right now that nobody sees? 👇",
     "chapters": [
        {"title": "The Empty Field", "lines": [
            "A farmer planted bamboo and waited.",
            "Year one: nothing broke the soil.",
            "Year two: still nothing.",
            "His neighbours planted corn and harvested twice.",
            "They laughed at his empty field.",
            "Year three. Year four. Nothing.",
            "Then year five arrived."]},
        {"title": "Year Four", "lines": [
            "Year four was the cruelest one.",
            "Because by then, quitting felt reasonable.",
            "His son begged him to plough the field.",
            "Plant corn like everyone else. Harvest something. Anything.",
            "The farmer walked the empty rows that night.",
            "Nothing above the soil. Not one green blade.",
            "He watered it anyway."]},
        {"title": "Ninety Days", "lines": [
            "In six weeks it grew thirty metres.",
            "Taller than a nine-storey building.",
            "The neighbours called it a miracle.",
            "It wasn't a miracle.",
            "For five years the bamboo grew DOWN.",
            "Roots deep enough to hold a tower.",
            "The growth was invisible. Not absent."]},
        {"title": "The Question", "lines": [
            "Afterwards, everyone asked him the same thing.",
            "'How did you know it would grow?'",
            "He said: 'I didn't.'",
            "'I just knew what I planted.'",
            "'And bamboo doesn't grow like corn.'",
            "Neither does anything worth five years.",
            "Remember that when your soil looks empty."]},
        {"title": "Your Empty Field", "lines": [
            "You posted and nobody watched.",
            "You trained and nothing changed.",
            "You studied and the marks stayed flat.",
            "Everyone around you is harvesting corn.",
            "And you're staring at bare soil.",
            "But roots don't send progress reports.",
            "They just hold on and go deeper."]},
        {"title": "What It Means", "lines": [
            "The years that look like nothing are the foundation.",
            "Quit in year four and the story is 'nothing happened'.",
            "Wait one more season and it's a miracle.",
            "You don't need to see growth to be growing.",
            "Water it anyway.",
            "Show up anyway.",
            "Your year five is coming."]}]},
]

_bank_cursor = {"i": 0}


def bank_story():
    used = " ".join(m.get("title", "").lower()
                    for m in (load(LIBRARY, {}) or {}).get("longform", {}).values())
    for s in STORY_BANK:
        if s["title"].lower()[:25] not in used:
            out = dict(s)
            out["engine"] = "story bank (offline)"
            return out
    out = dict(STORY_BANK[_bank_cursor["i"] % len(STORY_BANK)])
    _bank_cursor["i"] += 1
    out["engine"] = "story bank (offline)"
    return out


# ---------- 3+4. build video + derive native Shorts ----------

def _hook_key(line):
    """A first line reduced to what makes it the same script.

    Matching on the rendered TITLE would miss these: the same hook goes out with
    a rotating emoji, so "…watched him fall 🧠" and "…watched him fall 🔥" are
    different strings and the same video.
    """
    import re
    return re.sub(r"[^a-z0-9 ]", "", (line or "").lower()).strip()


def _already_published(content):
    """Opening lines already used by a script on this channel, cut or live."""
    out = set()
    for it in content.get("items", []):
        if it.get("lines"):
            out.add(_hook_key(it["lines"][0]))
    lib = load(LIBRARY, {"videos": {}}) or {"videos": {}}
    for v in (lib.get("videos") or {}).values():
        # library titles carry the hook plus an emoji and hashtags
        t = (v.get("title") or "").split("#")[0]
        if t:
            out.add(_hook_key(t))
    return out


def derive_shorts(script, n):
    """Turn the story's strongest beats into native vertical Shorts (built by
    the same engine as the daily videos — karaoke captions, end-cap, the lot).
    Each one funnels viewers back to the full story."""
    chapters = script["chapters"]
    # the cold open and the lesson are the strongest standalone beats
    picks = [chapters[0], chapters[-1]] + chapters[1:-1]
    content = load(CONTENT, {"items": []})
    existing = {it["id"] for it in content["items"]}
    spoken = _already_published(content)
    made = []
    for i, ch in enumerate(picks[:n]):
        lines = ch["lines"][:6]
        if len(lines) < 3:
            continue
        # A new id is not a new video. Stories are regenerated weekly from the
        # same source material, so the same beat comes back around — this cut
        # the "Forty thousand people watched him fall" Short a THIRD time, word
        # for word, under a fresh id each time. YouTube reads that as reused
        # content, which is the one thing a channel chasing monetization cannot
        # afford.
        key = _hook_key(lines[0])
        if key in spoken:
            print(f"  ⊘ skipped: \"{lines[0][:45]}\" — already published")
            continue
        spoken.add(key)
        seq = 1
        while f"st{seq:03d}" in existing:
            seq += 1
        sid = f"st{seq:03d}"
        content["items"].append({"id": sid, "theme": "story", "lines": lines})
        existing.add(sid)
        save(CONTENT, content)
        r = subprocess.run([sys.executable, os.path.join(HERE, "make_video.py"),
                            "--id", sid, "--channel", CHANNEL],
                           cwd=HERE, capture_output=True, text=True)
        if r.returncode == 0:
            made.append(sid)
            print(f"  ✂ short {sid}: \"{lines[0][:45]}\"")
        else:
            print(f"  ✗ short {sid} failed: {(r.stderr or r.stdout)[-120:]}")
    if made:
        subprocess.run([sys.executable, os.path.join(HERE, "metadata.py"),
                        "--sync", "--channel", CHANNEL], cwd=HERE, capture_output=True)
    return made


def make(minutes, shorts, upload=False):
    import make_longform as lf
    lf.set_channel(CHANNEL)
    arch, why = pick_topic()
    print(f"📖 Story pick: {arch['topic']}\n   ({why})\n")
    script = llm_story(minutes, arch) or bank_story()
    print(f"Script: \"{script['title']}\" — {len(script['chapters'])} beats "
          f"({script['engine']})")
    theme = arch["themes"][0]
    out, meta = lf.build(minutes, theme, script=script, kind="story")

    made = derive_shorts(script, shorts) if shorts else []
    print(f"\n✓ Story ready: {os.path.relpath(out, HERE)}"
          + (f"  + {len(made)} native Short(s) in output/" if made else ""))
    print("→ Open the dashboard Studio tab: upload button, plan and guide are there.")

    if upload:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "upload_youtube.py"),
             "--file", out, "--title", meta["title"], "--desc", meta["description"],
             "--thumb", os.path.join(LONGFORM_DIR, meta["thumb"]),
             "--comment", meta["pin_comment"], "--longform",
             "--channel", CHANNEL], cwd=HERE, capture_output=True, text=True)
        print(r.stdout or "", end="")
        print(r.stderr or "", end="")
        if r.returncode == 0:
            lib = load(LIBRARY, {"videos": {}})
            if meta["file"] in lib.get("longform", {}):
                e = lib["longform"][meta["file"]]
                e["status"] = "uploaded"
                # Same reason as make_longform: record which video it became,
                # or the story goes live and is untrackable afterwards.
                import upload_youtube as _U
                vid = _U.uploaded_id(r.stdout or "")
                if vid:
                    e["video_id"] = vid
                e["uploaded_at"] = date.today().isoformat()
                save(LIBRARY, lib)
    return out, meta


# ---------- 5. the dated 4-week plan ----------

def build_plan(weeks=4):
    """A dated calendar: which story on which Sunday, where everything goes.
    Daily Shorts stay on the autopilot; story-Shorts slot into Tue/Thu."""
    today = date.today()
    days_to_sun = (6 - today.weekday()) % 7
    first_sun = today + timedelta(days=days_to_sun or 7)
    # rank all archetypes once, then hand out best-first week by week
    ranked = []
    seen = set()
    for _ in range(len(ARCHETYPES)):
        a, why = pick_topic()
        pool = [x for x in ARCHETYPES if x["topic"] not in seen]
        if not pool:
            break
        best = a if a["topic"] not in seen else pool[0]
        ranked.append(best)
        seen.add(best["topic"])
    plan = {"generated": today.isoformat(), "weeks": []}
    for w in range(weeks):
        sun = first_sun + timedelta(weeks=w)
        arch = ranked[w % len(ranked)]
        plan["weeks"].append({
            "sunday": sun.isoformat(),
            "story": arch["topic"],
            "themes": arch["themes"],
            "story_shorts_days": [(sun + timedelta(days=2)).isoformat(),   # Tue
                                  (sun + timedelta(days=4)).isoformat()],  # Thu
        })
    save(PLAN, plan)
    print(f"✓ Story plan written: {weeks} Sundays mapped, starting {first_sun}.")
    return plan


def main():
    ap = argparse.ArgumentParser(description="Story Studio engine")
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--shorts", type=int, default=2)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--topic", action="store_true")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)

    if a.topic:
        arch, why = pick_topic()
        print(f"Would tell: {arch['topic']}\nWhy: {why}")
    elif a.plan:
        build_plan()
    elif a.make:
        mins = a.minutes or (load(CONFIG, {}) or {}).get("story_minutes", 6)
        make(mins, a.shorts, upload=a.upload)
        if not os.path.exists(PLAN):
            build_plan()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
