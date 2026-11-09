#!/usr/bin/env python3
"""
ai_brain.py — the intelligence layer. Three tiers, all with a free path:

  1. Ollama (FREE, local, no API key)  ← recommended for you
     Install once:  brew install ollama && ollama pull llama3.2:3b
     Then it writes scripts + coaches you, entirely on your Mac, $0.
  2. Anthropic API (paid, best quality) — used only if a key is set.
  3. Rule-based coach (FREE, always works) — a built-in expert system grounded
     in 2026 YouTube Shorts growth research. No install, no cost, no internet.

So there is always a working, free coach. Priority: Anthropic → Ollama → rules.

  python3 ai_brain.py --ensure 7   # top up scripts (LLM if available, else bank)
  python3 ai_brain.py --write 7    # force-write LLM scripts
  python3 ai_brain.py --analyze    # coaching report
"""

import argparse
import json
import os
import re
import sys
import urllib.request

import script_composer as sc

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content.json")
LIBRARY = os.path.join(HERE, "library.json")
TRENDS = os.path.join(HERE, "trends_report.json")
CONFIG = os.path.join(HERE, "config.json")
AI_KEY_FILE = os.path.join(HERE, "assets", "anthropic_api_key.txt")
OLLAMA = "http://localhost:11434"

# Ollama is ALWAYS local — reach it directly, never via a proxy. On college wifi
# the macOS system/college proxy can otherwise intercept localhost and the coach
# would silently drop to the offline FAQ. This opener ignores all proxies.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, data):
    json.dump(data, open(path, "w"), indent=2)


# ---------- LLM backends (Anthropic → Ollama) ----------

def _anthropic(system, user, max_tokens, model):
    try:
        import anthropic
    except ImportError:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and os.path.exists(AI_KEY_FILE):
        key = open(AI_KEY_FILE).read().strip()
    if not key:
        return None
    try:
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(model=model, max_tokens=max_tokens,
                                     system=system,
                                     messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if b.type == "text")
    except Exception:
        return None


def _ollama_up():
    try:
        _DIRECT.open(OLLAMA + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


def _ollama(system, user, max_tokens, model):
    if not _ollama_up():
        return None
    body = json.dumps({
        "model": model, "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "options": {"num_predict": max_tokens, "temperature": 0.8},
    }).encode()
    try:
        req = urllib.request.Request(OLLAMA + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with _DIRECT.open(req, timeout=240) as r:
            return json.loads(r.read()).get("message", {}).get("content", "")
    except Exception:
        return None


def llm(system, user, max_tokens=1500):
    """Return (text, engine_name) using the best available free-or-paid backend."""
    cfg = load(CONFIG, {})
    t = _anthropic(system, user, max_tokens, cfg.get("ai_model", "default"))
    if t:
        return t, "Anthropic API"
    t = _ollama(system, user, max_tokens, cfg.get("ollama_model", "llama3.2:3b"))
    if t:
        return t, "Ollama (local, free)"
    return None, None


def _anthropic_chat(system, history, max_tokens, model):
    """Multi-turn chat call. history = [{role:'user'|'assistant', content}]."""
    try:
        import anthropic
    except ImportError:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and os.path.exists(AI_KEY_FILE):
        key = open(AI_KEY_FILE).read().strip()
    if not key:
        return None
    try:
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(model=model, max_tokens=max_tokens,
                                     system=system, messages=history)
        return "".join(b.text for b in msg.content if b.type == "text")
    except Exception:
        return None


def _ollama_chat(system, history, max_tokens, model):
    """Multi-turn Ollama call. history = [{role, content}]."""
    if not _ollama_up():
        return None
    msgs = [{"role": "system", "content": system}] + history
    body = json.dumps({
        "model": model, "stream": False, "messages": msgs,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }).encode()
    try:
        req = urllib.request.Request(OLLAMA + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with _DIRECT.open(req, timeout=240) as r:
            return json.loads(r.read()).get("message", {}).get("content", "")
    except Exception:
        return None


COACH_SYSTEM = (
    "You are a blunt, practical, encouraging YouTube Shorts growth coach for "
    "'Mindset Refuel', a small faceless motivation channel run by a solo beginner "
    "in India (1-2 hrs/day, no budget). Ground every answer in 2026 Shorts reality: "
    "the algorithm tests each Short on a 50-500 seed pool; the first 3 seconds "
    "decide retention (aim >70%); bold-claim / curiosity-gap hooks win; keep videos "
    "15-35s; their own voice+music earns the original-audio bonus under 50k subs; "
    "money comes from a digital product + affiliate links BEFORE ad revenue (which "
    "needs 1k subs + 10M Shorts views in 90 days, ~9-18 months out). Be specific "
    "and honest, never hype. Keep replies short — 2-5 sentences or a tight list. "
    "Use the channel's real numbers below whenever they're relevant. The app can "
    "also RUN things when the user gives a direct command ('make today's video', "
    "'make a long video', 'sync my stats', 'scan trends') — if they seem to want "
    "an action but phrased it as a question, tell them the exact command to type."
)


# ---------- assistant actions (chat can DO things, not just talk) ----------
# Detected with plain rules (deterministic, free, works with no model at all);
# the dashboard/terminal maps each action id to the script that runs it.

_QUESTION_START = re.compile(
    r"^\s*(should|would|could|why|when|is|are|was|does|do i|did|how|what(?!'?s (the |my )?"
    r"(status|mission|plan)))", re.I)

_INTENTS = [
    # whole-message match ONLY — it kicks a publish, so "run a trend scan this
    # evening" must never land here
    ("evening",        r"^\s*(do|run|start|handle)\s+(my |the |your )?"
                       r"(whole |full |entire )?(evening( routine)?|routine|"
                       r"everything)\s*[.!]*\s*$"),
    ("make_story",     r"\b(make|create|build|generate|write|tell)\b.{0,40}"
                       r"\bstor(y|ies)\b"),
    ("make_longform",  r"\b(make|create|build|generate|prepare|render)\b.{0,40}"
                       r"\b(long[- ]?form|long(er)? video|longform|compilation)\b"),
    ("make_short",     r"\b(make|create|build|generate|prepare|render)\b.{0,40}"
                       r"\b(video|short|reel|today)\b"),
    ("apply_pins",     r"(\b(apply|post|add|put)\b.{0,30}\bpin|"
                       r"\bpin\b.{0,30}\b(comment|question)s?\b)"),
    ("sync_analytics", r"\b(sync|pull|fetch|get|check)\b.{0,30}"
                       r"\b(retention|analytics)\b"),
    ("sync_stats",     r"\b(sync|update|refresh|pull|fetch)\b.{0,30}"
                       r"\b(stats|numbers|views|subs|channel)\b"),
    ("trend_scan",     r"\b(scan|check|look|search)\b.{0,30}\btrend"),
    ("analyze",        r"\b(analy[sz]e|full report|audit)\b"),
    ("status",         r"\b(status|today'?s mission|what'?s (the |my )?(status|mission|plan))\b"),
]

ACTION_LABELS = {
    "evening":        "Running your whole evening (sync → pins → upload)",
    "make_short":     "Preparing today's video (a minute or two)",
    "make_story":     "Writing and filming this week's story (several minutes)",
    "make_longform":  "Building a long-form video (several minutes)",
    "apply_pins":     "Posting your question comment on every live video",
    "sync_analytics": "Pulling retention analytics from YouTube",
    "sync_stats":     "Syncing your real channel stats",
    "trend_scan":     "Scanning this week's trends",
    "analyze":        "Analyzing your numbers",
    "status":         "Today's status",
}


def detect_intent(q):
    """Return an action id if the message is a direct command, else None.
    Questions ('should I…', 'how do I…') are answered by the coach, not run."""
    text = (q or "").strip()
    if not text:
        return None
    if _QUESTION_START.match(text) and not re.search(_INTENTS[-1][1], text, re.I):
        return None
    for action, pat in _INTENTS:
        if re.search(pat, text, re.I):
            return action
    return None


def status_text():
    """Compact 'where things stand' answer for the status intent."""
    lines = []
    try:
        import progress
        s = progress.summary()
        lines.append(f"{s['title']}: {s['subs']} subs · {s['posted']} posted · "
                     f"{s['video_views']:,} views (avg {s['avg_views']}/video) · "
                     f"{s['subs_to_1k']} subs to monetization threshold.")
        if s["best_theme"]:
            lines.append(f"Best theme: {s['best_theme']}.")
    except Exception:
        pass
    today = load(os.path.join(HERE, "today.json"))
    from datetime import date as _d
    if today and today.get("date") == _d.today().isoformat():
        lines.append(f"Today's mission is ready: \"{today['title'][:60]}\" — "
                     f"post at {today.get('post_time','~8 PM')}.")
    else:
        lines.append("No mission prepared for today yet — say 'make today's video' "
                     "and I'll build one.")
    return "\n".join(lines) or "No data yet — sync your stats first."


def coach_reply(history):
    """Answer a chat turn as the growth coach, grounded in the real channel data.
    history = [{role:'user'|'assistant', content}]. Returns (text, engine)."""
    cfg = load(CONFIG, {})
    system = COACH_SYSTEM + "\n\n--- Your channel's real data ---\n" + _context()
    t = _anthropic_chat(system, history, 600, cfg.get("ai_model", "default"))
    if t:
        return t.strip(), "Anthropic API"
    t = _ollama_chat(system, history, 600, cfg.get("ollama_model", "llama3.2:3b"))
    if t:
        return t.strip(), "Ollama (local, free)"
    # offline fallback: reuse the FAQ bot on the last question
    last = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
    try:
        import ask
        return ask.rule_answer(last), "offline FAQ"
    except Exception:
        return ("Your local coach (Ollama) isn't reachable right now. Start it with "
                "`ollama serve`, or just keep posting daily — that's the #1 lever at "
                "your stage."), "offline"


REPLY_FALLBACKS = [
    "Appreciate you 🙏 What are you working toward right now?",
    "This is why I post. Keep showing up — day one or one day, you chose day one. 🔥",
    "Love this. Come back tomorrow — new one every day. 💪",
    "Respect for saying it out loud. Now go do one small thing today. 🔥",
]


def draft_reply(comment, video_title=""):
    """Draft a short, warm creator reply to a viewer comment. Replying fast is
    the #1 growth signal at this stage — this makes each reply a 5-second job.
    Returns (text, engine)."""
    system = ("You are the creator of Mindset Refuel, a motivational YouTube "
              "channel, replying to a comment on your own video. Reply in under "
              "25 words: warm, human, specific to what they said, never generic "
              "or salesy, at most one emoji. If natural, end with a short "
              "question to keep the thread going. Return ONLY the reply text.")
    user = (f"Video: {video_title or 'a motivation Short'}\n"
            f"Comment: {comment}\n\nYour reply:")
    text, engine = llm(system, user, max_tokens=80)
    if text:
        return text.strip().strip('"'), engine
    return REPLY_FALLBACKS[abs(hash(comment)) % len(REPLY_FALLBACKS)], "offline templates"


def engine_status():
    cfg = load(CONFIG, {})
    if _anthropic("x", "hi", 5, cfg.get("ai_model", "default")):
        return "Anthropic API"
    if _ollama_up():
        return "Ollama (local, free)"
    return "rule-based coach (free)"


def has_ai():
    return engine_status() != "rule-based coach (free)"


# ---------- shared context ----------

def _context():
    parts = []
    # the creator's own channel profile + progress (tailors every script/reply)
    try:
        import progress
        parts.append(progress.context_block())
    except Exception:
        pass
    tr = load(TRENDS)
    if tr:
        parts.append("Trending hashtags: " + ", ".join(t for t, _ in tr.get("hashtags", [])[:8]))
        parts.append("Winning hook words: " + ", ".join(w for w, _ in tr.get("hook_words", [])[:10]))
        parts.append(f"Median winning length: {tr.get('median_len','?')}s")
    lib = load(LIBRARY, {"videos": {}})
    ch = lib.get("channel", {})
    if ch:
        parts.append(f"Channel: {ch.get('title')} — {ch.get('subs',0)} subs")
    # retention (the real ranking signal) — present once analytics is synced
    an = ch.get("analytics") or {}
    if an.get("videos"):
        titles = {v["id"]: v["title"].split("#")[0].strip()[:38]
                  for v in ch.get("live_videos", [])}
        ranked = sorted(an["videos"].items(), key=lambda kv: -kv[1]["avg_pct"])
        best, worst = ranked[0], ranked[-1]
        parts.append(
            f"RETENTION (avg % watched — >70% is what gets pushed): "
            f"best {best[1]['avg_pct']:.0f}% '{titles.get(best[0], '?')}'; "
            f"worst {worst[1]['avg_pct']:.0f}% '{titles.get(worst[0], '?')}'. "
            f"Judge videos by retention over raw views.")
    vids = sorted((v for v in lib["videos"].values() if v.get("views", 0) > 0),
                  key=lambda v: -v["views"])
    if vids:
        parts.append("Your best videos (views | theme | title):")
        for v in vids[:5]:
            parts.append(f"  {v['views']:,} | {v.get('theme','?')} | {v['title'][:55]}")
    return "\n".join(parts) or "No data yet; use general best practices."


# ---------- scripts ----------

def write_scripts(n):
    system = ("You write scripts for a faceless YouTube Shorts motivation channel, "
              "Mindset Refuel. Each script = 6-7 very short spoken lines (5-9 words). "
              "Line 1 is a bold-claim or curiosity-gap HOOK that stops the scroll in "
              "3 seconds (no slow build). Last line is a command. No hashtags, no "
              "emojis, no stage directions. Vary themes.")
    user = (f"{_context()}\n\nWrite {n} NEW scripts leaning into what's trending and "
            f"working. Return ONLY JSON: "
            '{"scripts":[{"theme":"discipline","lines":["l1","l2","..."]}]}')
    text, _ = llm(system, user, max_tokens=3000)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out = []
    for s in data.get("scripts", []):
        lines = [str(x).strip() for x in s.get("lines", []) if str(x).strip()]
        if 3 <= len(lines) <= 9:
            out.append({"theme": s.get("theme", "ai"), "lines": lines})
    return out or None


def append_scripts(scripts):
    content = load(CONTENT, {"items": []})
    existing = {it["id"] for it in content["items"]}
    seq, added = 1, []
    for s in scripts:
        while f"ai{seq:03d}" in existing:
            seq += 1
        it = {"id": f"ai{seq:03d}", "theme": s["theme"], "lines": s["lines"]}
        content["items"].append(it); existing.add(it["id"]); added.append(it); seq += 1
    save(CONTENT, content)
    return added


def ensure(n):
    have = sc.unused_count()
    need = max(0, n - have)
    if need == 0:
        print(f"Already {have} unused scripts."); return
    scripts = write_scripts(need)
    if scripts:
        for it in append_scripts(scripts):
            print(f"  + {it['id']} [{it['theme']}] {it['lines'][0]}")
        print(f"LLM wrote {len(scripts)} scripts.")
        if len(scripts) < need:
            sc.compose(need - len(scripts))
    else:
        print("No LLM — using the offline script bank.")
        sc.compose(need)


# ---------- coaching ----------

def rule_based_coach():
    """Expert system grounded in 2026 Shorts-growth research. Always free."""
    lib = load(LIBRARY, {"videos": {}})
    ch = lib.get("channel", {})
    tr = load(TRENDS, {})
    vids = [v for v in lib["videos"].values() if v.get("views", 0) > 0]
    vids.sort(key=lambda v: -v["views"])
    subs = ch.get("subs", 0)
    posted = sum(1 for v in lib["videos"].values() if v.get("status") == "uploaded")

    L = []
    L.append("=" * 60)
    L.append(f"  COACH — {ch.get('title','Mindset Refuel')} · {subs} subs · "
             f"{posted} posted")
    L.append("=" * 60)

    # 1. stage-based priority
    if subs < 100:
        L.append("\nSTAGE: Ignition (0–100 subs). Your ONLY job is reps + retention.")
        L.append("  • Post daily without fail. The algorithm tests every Short on a")
        L.append("    50–500 seed pool (~70% non-subs) — volume = more lottery tickets.")
    elif subs < 1000:
        L.append("\nSTAGE: Traction (100–1k subs). Double down on what's working.")
    else:
        L.append("\nSTAGE: Monetization push. Drive toward 10M Shorts views/90d + product sales.")

    # 2. what's working (their real data)
    if vids:
        best = vids[0]
        L.append(f"\nWHAT'S WORKING: your top video is '{best['title'][:45]}' "
                 f"({best['views']:,} views).")
        themes = {}
        for v in vids:
            th = v.get("theme") or ""
            if th:
                themes[th] = themes.get(th, 0) + v["views"]
        if themes:
            winner = max(themes, key=themes.get)
            L.append(f"  → Make MORE '{winner}' scripts. Reuse the hook style that won.")
        else:
            L.append(f"  → Reuse that hook style: \"{best['title'].split('#')[0].strip()}\".")
    else:
        L.append("\nWHAT'S WORKING: no view data yet — click 'Sync my stats' after a few posts.")

    # 2b. distance to monetization (their real numbers vs the thresholds)
    total_views = ch.get("total_views", 0)
    L.append("\nDISTANCE TO MONETIZATION (YouTube Partner Program):")
    bar = int(min(subs, 1000) / 1000 * 20)
    L.append(f"  Subscribers  [{'█'*bar}{'·'*(20-bar)}] {subs}/1,000  "
             f"({max(0,1000-subs)} to go)")
    L.append(f"  Then you also need EITHER 10,000,000 Shorts views in 90 days")
    L.append(f"  OR 4,000 long-form watch-hours. (Your lifetime views so far: {total_views:,}.)")
    L.append("  Fastest lever: post daily + weekly long-form compilation. Don't wait")
    L.append("  for ad revenue — your product + affiliate can earn money right now.")

    # 3. the non-negotiable retention rules (researched)
    L.append("\nRETENTION RULES (2026 — this is what gets you pushed wider):")
    L.append("  • First 3 seconds decide everything — aim >70% intro retention.")
    L.append("    Open with a BOLD CLAIM or CURIOSITY GAP. Never a slow build.")
    L.append("  • Keep videos 15–35s. Under 30s needs ~65% avg retention to spread.")
    L.append("  • You already use your OWN voice + music → you qualify for YouTube's")
    L.append("    2026 original-audio bonus (beats trending audio under 50k). Keep it.")

    # 4. trend nudge
    if tr.get("hook_words"):
        hot = ", ".join(w for w, _ in tr["hook_words"][:6])
        L.append(f"\nTHIS WEEK'S HOT HOOKS: {hot}")
        L.append("  → Work 2–3 of these into your next batch's opening lines.")

    # 5. money + growth flow
    L.append("\nMONEY FLOW (don't wait for ad revenue — stack these):")
    L.append("  1. Digital product (your wallpaper pack + ebook) linked in every")
    L.append("     description + pinned comment. Sells 24/7. Highest margin.")
    L.append("  2. Affiliate link (a book you'd recommend) — trust is already built.")
    L.append("  3. Ad revenue comes LATER (9–18 months to eligibility). Don't rely on it.")
    L.append("  • Weekly: post ONE long-form compilation (make_compilation.py) —")
    L.append("    Shorts+long-form grow 41% faster and it builds watch-hours.")

    # 6. this week's checklist
    L.append("\nDO THIS WEEK:")
    L.append("  [ ] Post 1 video/day; reply to comments in the first hour")
    L.append("  [ ] Make more of your winning theme")
    L.append("  [ ] Put your product link in every description")
    L.append("  [ ] Publish one long-form compilation")
    L.append("=" * 60)
    return "\n".join(L)


def analyze():
    text, engine = llm(
        system=("You are a blunt, practical YouTube Shorts growth coach for a small "
                "faceless motivation channel in 2026. Key facts: the algorithm tests "
                "every Short on a 50–500 seed pool; first 3 seconds decide retention "
                "(aim >70%); bold-claim/curiosity-gap hooks win; 15–35s length; own "
                "audio gets a bonus under 50k subs; money comes from product+affiliate "
                "before ad revenue. Give 5–7 specific, honest bullets, no hype."),
        user=f"{_context()}\n\nWhat should I do this week to grow and earn?",
        max_tokens=1000,
    )
    if text:
        print("=" * 60)
        print(f"  YOUR AI COACH  ·  via {engine}")
        print("=" * 60)
        print(text.strip())
    else:
        print(rule_based_coach())


def chat_repl():
    """Terminal assistant — chat AND run actions, no dashboard needed.
    This keeps working forever on just the free local model (Ollama)."""
    import subprocess
    action_cmds = {
        "evening": ["evening.py"],
        "make_short": ["pilot.py"],
        "make_story": ["storyteller.py", "--make"],
        "make_longform": ["make_longform.py"],
        "apply_pins": ["channel_control.py", "--apply-pins"],
        "sync_analytics": ["analytics.py", "--sync"],
        "sync_stats": ["channel_stats.py"],
        "trend_scan": ["trend_scan.py"],
    }
    print("=" * 58)
    print(f"  MINDSET REFUEL ASSISTANT  ·  {engine_status()}")
    print("  Chat, or command me: 'make today's video', 'make a long")
    print("  video', 'sync my stats', 'scan trends', 'analyze', 'status'.")
    print("  Ctrl-C or 'exit' to quit.")
    print("=" * 58)
    history = []
    while True:
        try:
            q = input("\nyou › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q or q.lower() in ("exit", "quit", "q"):
            break
        action = detect_intent(q)
        if action == "status":
            print("\n" + status_text())
            continue
        if action == "analyze":
            analyze()
            continue
        if action in action_cmds:
            print(f"\n▸ {ACTION_LABELS[action]} …")
            r = subprocess.run([sys.executable, *action_cmds[action]], cwd=HERE)
            print("✓ done" if r.returncode == 0 else "✗ that failed — see above")
            continue
        history.append({"role": "user", "content": q})
        text, engine = coach_reply(history[-12:])
        history.append({"role": "assistant", "content": text})
        print(f"\ncoach ({engine}) › {text}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensure", type=int)
    ap.add_argument("--write", type=int)
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--chat", action="store_true",
                    help="interactive assistant in the terminal (chat + actions)")
    ap.add_argument("--engine", action="store_true", help="print which coach is active")
    a = ap.parse_args()
    if a.engine:
        print(engine_status())
    elif a.chat:
        chat_repl()
    elif a.analyze:
        analyze()
    elif a.write:
        s = write_scripts(a.write)
        if s:
            for it in append_scripts(s):
                print(f"  + {it['id']} [{it['theme']}] {it['lines'][0]}")
        else:
            print("No LLM available.")
    elif a.ensure is not None:
        ensure(a.ensure)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
