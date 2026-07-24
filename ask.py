#!/usr/bin/env python3
"""
ask.py — your help bot. Ask it anything about running the channel or the system.

Uses a free local model (Ollama) or Claude if available; otherwise answers from a
built-in FAQ. Always works, always free.

  python3 ask.py "how do I upload a video?"
  python3 ask.py "the dashboard won't open, what do I do?"
"""

import sys

import ai_brain

CONTEXT = """You are the built-in help assistant for 'Mindset Refuel', a faceless
YouTube Shorts motivation channel run by a solo beginner creator in India who has
1-2 hours a day and no money for paid tools. Answer their questions clearly, kindly,
and practically. Keep answers short (a few sentences or a short list).

How the system works (all local, on their Mac, free):
- They run  ./dashboard.sh  which opens the AI Pilot at http://localhost:5050.
- The Pilot prepares ONE optimized video per day with a title, description, and
  Instagram caption, plus 4 steps. They upload it to YouTube (as a Short) and
  Instagram Reels, pin their product link, and reply to comments.
- Files: pilot.py (today's video), make_video.py (builder), ai_brain.py (coach +
  scripts), channel_stats.py (pulls their real views), make_compilation.py (weekly
  long-form), doctor.py (health check), character.py (stick-figure narrator).
- Growth truth (2026): every Short is tested on a 50-500 seed pool; the first 3
  seconds decide retention (bold-claim/curiosity-gap hooks win); 15-35s length;
  their own voice+music earns YouTube's original-audio bonus under 50k subs.
- Money order: sell their digital product (wallpaper pack + ebook) + affiliate
  links NOW; sponsorships around 10k followers; ad revenue only after 1k subs +
  10M Shorts views in 90 days (9-18 months). Be honest that it takes months.
- If something breaks, tell them to run:  python3 doctor.py
Answer as this assistant. If you don't know, point them to HANDBOOK.md."""

FAQ = [
    (("upload", "post", "publish"),
     "Open ./dashboard.sh → 'Today's Mission' shows one video. Click copy title, "
     "copy description, copy caption; upload the .mp4 to YouTube as a Short and to "
     "Instagram Reels; pin your product link; then click 'I uploaded this'."),
    (("run", "start", "open", "dashboard", "won't", "cant", "can't"),
     "In Terminal: `cd ~/youtube` then `./dashboard.sh`. It opens "
     "http://localhost:5050. If it errors, run `python3 doctor.py` — it prints the "
     "exact fix. To stop it, press Ctrl+C."),
    (("money", "earn", "monetize", "income", "paid"),
     "Fastest money: your digital product (wallpaper pack + ebook on Gumroad) + an "
     "affiliate book link, in every description + pinned comment. Ad revenue comes "
     "much later (1k subs + 10M Shorts views/90d). See STRATEGY.md."),
    (("views", "grow", "growth", "algorithm", "traction"),
     "Post daily, hook hard in the first 3 seconds, keep videos 15-35s, and reply "
     "to comments in the first hour. Volume + retention + engagement beats "
     "everything. Click 'AI Coach' in the dashboard for advice on your real data."),
    (("script", "run out", "out of", "topic", "idea"),
     "You won't run out — the composer has 500+ combos and the Pilot picks the best "
     "topic daily. If it ever says 'all combos used', ask me to add a new bank."),
    (("voice", "robot", "music", "background"),
     "Voice is edge-tts (natural) with an offline Piper fallback; music is safe "
     "self-generated ambient. To add a stick-figure narrator, set \"character\": "
     "true in config.json."),
    (("comment", "reply", "engage"),
     "Reply to every comment in the first hour after posting — it's the single "
     "biggest signal that tells YouTube to push your Short wider."),
]


def rule_answer(q):
    ql = q.lower()
    for keys, ans in FAQ:
        if any(k in ql for k in keys):
            return ans
    return ("I'm not sure about that one — check HANDBOOK.md, or try rephrasing. "
            "For anything broken, run `python3 doctor.py`.")


def answer(q):
    text, _ = ai_brain.llm(system=CONTEXT, user=q, max_tokens=500)
    return text.strip() if text else rule_answer(q)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 ask.py \"your question\"")
        sys.exit(0)
    print(answer(" ".join(sys.argv[1:])))
