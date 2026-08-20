#!/usr/bin/env python3
"""
dashboard.py — Mindset Refuel AI Pilot (full-page, tabbed control room).

  ./dashboard.sh   then open  http://localhost:5050

Tabs: Today (one mission) · Uploaded (your posted videos) · Coach · Settings.
Feature toggles live in Settings so the Today screen stays clean.
"""

import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import date

from flask import Flask, jsonify, request, send_from_directory

import netcfg
import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- multi-channel: data paths are resolved per request from ?channel= ----
# These module-level names default to the motivation channel (backward compatible
# with every existing route/builder that reads them). sel_channel() re-points
# them for the current request; the local dashboard serves one user at a time.
_P0 = _paths.paths(None)
OUTPUT = _P0["output"]
LONGFORM_DIR = _P0["long_form"]
LIBRARY = _P0["library"]
TODAY = _P0["today"]
CONFIG = _P0["config"]
CHANNEL = _paths.DEFAULT_CHANNEL


def channels():
    """All channels from the registry (for the switcher)."""
    return _paths.load_registry()


def active_channels():
    return _paths.active_channels()


def sel_channel(slug=None):
    """Point the module data paths at `slug` (or the ?channel= request arg).
    Returns the resolved slug."""
    global OUTPUT, LONGFORM_DIR, LIBRARY, TODAY, CONFIG, CHANNEL
    if slug is None:
        try:
            slug = request.args.get("channel")
        except Exception:
            slug = None
    valid = {c["slug"] for c in channels()}
    slug = slug if slug in valid else _paths.DEFAULT_CHANNEL
    P = _paths.paths(slug)
    OUTPUT, LONGFORM_DIR = P["output"], P["long_form"]
    LIBRARY, TODAY, CONFIG = P["library"], P["today"], P["config"]
    CHANNEL = slug
    return slug
AUTOPILOT_PLIST = os.path.expanduser(
    "~/Library/LaunchAgents/com.mindsetrefuel.autopilot.plist")
# Use THIS interpreter for subprocesses (the one with the libraries installed),
# and append Homebrew for ffmpeg/ollama — don't prepend, or Homebrew's python3
# would shadow ours.
PY = sys.executable
ENV = {**os.environ, "PATH": os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin"}

app = Flask(__name__)
JOB = {"running": False, "log": [], "done_msg": "", "coach": ""}
COACH_CHAT = []   # running [{role:'user'|'assistant', content}] transcript


def log(m): JOB["log"].append(m)


# Scripts that accept --channel (per-channel data). trend_scan/make_compilation/
# doctor/ai_brain operate on shared/global data and take no --channel.
_CHANNEL_AWARE = {"pilot.py", "make_video.py", "metadata.py", "upload_youtube.py",
                  "channel_stats.py", "analytics.py", "channel_control.py",
                  "evening.py", "storyteller.py", "make_longform.py", "progress.py",
                  "schedule_queue.py"}


def _with_channel(cmd, channel):
    """Append --channel to the child command when the script understands it."""
    if cmd and channel and cmd[0] in _CHANNEL_AWARE:
        return [*cmd, "--channel", channel]
    return cmd


def run(cmd, label, channel=None):
    log(f"▸ {label} …")
    env = {**ENV, **netcfg.proxy_env()}   # fresh each run: proxy toggle needs no restart
    p = subprocess.run([PY, *_with_channel(cmd, channel)], cwd=HERE, env=env,
                       capture_output=True, text=True)
    # keep enough lines for the 🌇 evening summary/checklist to show whole
    for t in (p.stdout or p.stderr).strip().splitlines()[-30:]:
        log("   " + t)
    if p.returncode != 0:
        log(f"✗ {label} failed"); raise RuntimeError(label)
    log(f"✓ {label}")


def job(cmd, label, ok, channel=None):
    try:
        JOB["log"] = []; run(cmd, label, channel=channel); JOB["done_msg"] = ok
    except Exception:
        JOB["done_msg"] = f"{label} failed — check the terminal."
    finally:
        JOB["running"] = False


def run_all_job():
    """The 'Run all 3 — one click' engine: prepare today's Short for every ACTIVE
    channel; on Sundays also build each channel's weekly long-form."""
    try:
        JOB["log"] = []
        sunday = date.today().weekday() == 6
        chans = active_channels()
        log(f"🚀 Running all {len(chans)} active channel(s)"
            + (" + weekly long-form (Sunday)" if sunday else ""))
        made = 0
        for c in chans:
            slug, name = c["slug"], c.get("name", c["slug"])
            try:
                run(["pilot.py"], f"{name}: prepare today's Short", channel=slug)
                made += 1
            except Exception:
                log(f"   ✗ {name}: Short failed — continuing")
            if sunday:
                story = (load(_paths.paths(slug)["config"], {}) or {}).get("story_mode", True)
                cmd = (["storyteller.py", "--make"] if story else ["make_longform.py"])
                try:
                    run(cmd, f"{name}: weekly long-form", channel=slug)
                except Exception:
                    log(f"   ✗ {name}: long-form failed — continuing")
        JOB["done_msg"] = f"All done ✅ {made}/{len(chans)} channels have today's Short ready"
    except Exception as e:
        JOB["done_msg"] = f"Run-all failed — {e}"
    finally:
        JOB["running"] = False


def coach_job():
    try:
        JOB["log"] = []; log("▸ Asking your coach …")
        env = {**ENV, **netcfg.proxy_env()}
        p = subprocess.run([PY, "ai_brain.py", "--analyze"], cwd=HERE, env=env,
                           capture_output=True, text=True)
        JOB["coach"] = (p.stdout or p.stderr).strip(); JOB["done_msg"] = "Coach ready ✅"
    except Exception:
        JOB["done_msg"] = "Coach failed."
    finally:
        JOB["running"] = False


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save_json(path, data):
    """Atomic write — a background job reading mid-write must never see a
    half-written library.json/config.json."""
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w"), indent=2)
    os.replace(tmp, path)


def mission():
    m = load(TODAY)
    if not (m and m.get("date") == date.today().isoformat()):
        return None
    # The calendar (schedule_queue.py) uploads ahead of the release time, so a
    # mission written this morning can name a video that is ALREADY on YouTube
    # waiting to go public. Still showing it with a live "upload" button is one
    # click away from posting the same video twice, which is exactly the reused
    # content YouTube penalizes. Only 'ready' means genuinely un-posted.
    v = ((load(LIBRARY, {"videos": {}}) or {}).get("videos") or {}).get(
        m.get("file", ""))
    if v is not None and v.get("status") != "ready":
        return None
    return m


def calendar_html():
    """The posting calendar (schedule.json) rendered as a compact strip.

    Uploads now happen ahead of time with YouTube's publishAt, so 'nothing to do
    today' is the normal, healthy state. Without showing the calendar that looks
    broken — this is the panel that says "yes, it's handled, here's when".
    """
    q = load(os.path.join(HERE, "schedule.json"), {}) or {}
    items = q.get("items") or []
    if not items:
        return ""
    today = date.today().isoformat()
    upcoming = [i for i in items if i["publish_date"] >= today][:24]
    if not upcoming:
        return ""

    by_day = {}
    for i in upcoming:
        by_day.setdefault(i["publish_date"], []).append(i)

    cols = []
    for day in sorted(by_day):
        rows = []
        for i in sorted(by_day[day], key=lambda x: x["channel"]):
            live = i["status"] == "uploaded"
            mark = "✅" if live else "🕓"
            note = "on YouTube, goes public automatically" if live else "queued"
            kind = " · long" if i.get("kind") == "longform" else ""
            rows.append(
                f"<div style='margin:4px 0;font-size:12px' title='{note}'>"
                f"{mark} <b>{dhtml(i['channel'])}</b>{kind}<br>"
                f"<span class='muted'>"
                f"{dhtml((i.get('title') or '').split('#')[0].strip()[:34])}</span></div>")
        label = "TODAY" if day == today else day[5:]
        cols.append(
            f"<div style='flex:1;min-width:150px;background:#0e1626;"
            f"border:1px solid var(--line);border-radius:12px;padding:10px 12px'>"
            f"<div style='font-weight:700;margin-bottom:6px'>{label}</div>"
            f"{''.join(rows)}</div>")

    done = sum(1 for i in items if i["status"] == "uploaded")
    return (f"<div class='mtitle' style='margin-bottom:8px'>📅 Your posting calendar "
            f"— {done} already on YouTube, publishing themselves</div>"
            f"<div class='why' style='margin-bottom:8px'>✅ = uploaded and waiting for "
            f"its release time. 🕓 = queued; it uploads automatically the day before. "
            f"You don't have to be at the computer.</div>"
            f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px'>"
            + "".join(cols) + "</div>")


def queue_card(slug):
    """What this ONE channel does next, with the button that does it.

    Replaces a dead end. The page used to say "No video prepared for today" and
    offer only "Prepare", which was wrong in the two cases that now matter: the
    video may already be on YouTube waiting for its release time, or the next
    one may be sitting in the calendar. Both looked like "nothing exists" and
    invited a rebuild of content that was already handled.
    """
    q = load(os.path.join(HERE, "schedule.json"), {}) or {}
    mine = [i for i in (q.get("items") or []) if i["channel"] == slug]
    today = date.today().isoformat()

    def card(title, why, row):
        return (f"<div class='mission'><div class='m-body'>"
                f"<div class='mtitle'>{title}</div><div class='why'>{why}</div>"
                f"<div class='row'>{row}</div></div></div>")

    live = [i for i in mine if i["status"] == "uploaded"
            and i["publish_date"] == today]
    if live:
        i = live[0]
        # post_time_ist is the key upload_youtube actually schedules against;
        # "post_time" never existed, so this card used to say "prime time" on
        # every channel instead of each channel's real, staggered slot.
        when = (load(CONFIG, {}) or {}).get("post_time_ist", "19:30") + " IST"
        watch = "".join(
            f"<button class='mini' onclick=\"window.open("
            f"'https://youtu.be/{esc(x['video_id'])}','_blank')\">▶ "
            f"{'long-form' if x.get('kind') == 'longform' else 'Short'}</button>"
            for x in live if x.get("video_id"))
        # Today being covered must not hide a broken upload further down the
        # queue — that is how failures went unnoticed before.
        broken = [i for i in mine if i["status"] == "failed"]
        warn = (f"<br><span style='color:var(--gold)'>⚠ {len(broken)} later "
                f"upload(s) failed and will be retried automatically — see the "
                f"calendar above.</span>" if broken else "")
        return card(
            f"✅ Today is done — {len(live)} video(s) already on YouTube",
            f"Uploaded and scheduled. YouTube makes {'them' if len(live) > 1 else 'it'} "
            f"public at {esc(when)} today by itself — you don't have to be at the "
            f"computer. Nothing to click." + warn,
            watch + "<button class='mini' onclick='pilot()'>🚀 Build an extra one</button>")

    nxt = sorted((i for i in mine if i["status"] in ("pending", "failed")),
                 key=lambda i: i["publish_date"])
    if nxt:
        i = nxt[0]
        late = i["status"] == "failed"
        head = (i.get("title") or "").split("#")[0].strip()[:60]
        # All three channels share one API project: 10,000 units a day, 1,600 per
        # upload. Offering a button that cannot run today is worse than saying so.
        budget = q.get("daily_budget", 8000)
        left = (budget - (q.get("spent", {}) or {}).get(today, 0)) // 1600
        if left < 1:
            btn = ("<button class='primary' disabled style='opacity:.45;"
                   "cursor:not-allowed'>⤴ Upload now — quota used up today</button>")
            note = ("<br><span style='color:var(--gold)'>Today's YouTube upload "
                    "quota is spent (6 a day across all 3 channels). This uploads "
                    "itself tomorrow morning — nothing is lost.</span>")
        else:
            btn = ("<button class='primary' onclick='queueNow()'>⤴ Upload to "
                   f"YouTube now</button>")
            note = (f"<br><span class='muted'>{left} upload(s) left in today's "
                    f"shared API quota.</span>")
        return card(
            ("⚠ Last attempt failed — send it again"
             if late else f"🕓 Next up: {dhtml(head)}"),
            (f"Its release date is <b>{i['publish_date']}</b>. It uploads itself the "
             f"day before, so you can ignore this. The button sends it to YouTube "
             f"right now instead — it still stays private until "
             f"{i['publish_date']}, so the calendar doesn't change.")
            + (f"<br><span style='color:var(--gold)'>Error: "
               f"{dhtml(str(i.get('error', ''))[:120])}</span>" if late else "")
            + note,
            btn + "<button class='go' onclick='pilot()'>🚀 Build a new one</button>")

    ready = sum(1 for n, v in (load(LIBRARY, {"videos": {}}) or {}).get(
        "videos", {}).items()
        if v.get("status") == "ready" and os.path.exists(os.path.join(OUTPUT, n)))
    if ready:
        return card(
            f"📦 {ready} video(s) built and waiting — not on the calendar yet",
            "They're rendered and ready; they just have no release date. "
            "Scheduling gives each one a day and uploads them automatically.",
            "<button class='primary' onclick='planQueue()'>🗓 Schedule them</button>"
            "<button class='go' onclick='pilot()'>🚀 Build another</button>")

    return card(
        "No video prepared for today.",
        "The Pilot will scan trends and build one optimized video.",
        "<button class='primary' onclick=\"pilot()\">🚀 Prepare today's video</button>")


def latest_longform():
    """(filename, meta) of the newest long-form video, or (None, None)."""
    lf = (load(LIBRARY, {}) or {}).get("longform", {})
    if not lf:
        return None, None
    name = max(lf, key=lambda k: (lf[k].get("created", ""), k))
    return name, lf[name]


def esc(s):
    return (s.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
             .replace("\n", "\\n").replace('"', "&quot;"))


def dhtml(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("\n", "<br>"))


def tesc(s):
    """Escape for inside a <textarea> — keep real newlines (no <br>)."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_progress_html():
    import progress
    progress.set_channel(CHANNEL)          # show THIS channel's numbers, not motivation's
    s = progress.summary()
    p = progress.get_profile()
    f = lambda n: f"{n:,}"

    cards = [(f(s["subs"]), "subscribers"), (f(s["posted"]), "videos posted"),
             (f(s["video_views"]), "views on your videos"),
             (f(s["avg_views"]), "avg views / video"),
             (f(s["likes"]), "total likes"), (f(s["ready"]), "ready to post")]
    stat_cards = "".join(f"<div class='stat'><div class='n'>{n}</div>"
                         f"<div class='l'>{l}</div></div>" for n, l in cards)

    bar = min(100, s["subs"] / 1000 * 100)
    last = s["last_posted"] or "—"
    mon = (f"<div class='card' style='max-width:960px'><h3 style='margin-top:0'>Road to "
           f"monetization</h3><div style='display:flex;align-items:center;gap:12px;margin:10px 0'>"
           f"<div class='pbar' style='flex:1'><i style='width:{bar:.1f}%'></i></div>"
           f"<div class='muted' style='white-space:nowrap'>{f(s['subs'])} / 1,000 subs</div></div>"
           f"<div class='muted'>Then you also need <b>10,000,000 Shorts views in 90 days</b> OR "
           f"4,000 long-form watch-hours. Fastest lever: post daily + a weekly long-form compile. "
           f"Your product + affiliate can earn before ad revenue. Last posted: <b>{last}</b>.</div></div>")

    if s["top"]:
        rows = "".join(f"<tr><td>{dhtml(t['title'][:60])}</td><td>{dhtml(str(t['theme']))}</td>"
                       f"<td class='v'>{f(t['views'])}</td><td>{f(t['likes'])}</td></tr>"
                       for t in s["top"])
        top_html = (f"<table class='ptable'><tr><th>Video</th><th>Theme</th><th>Views</th>"
                    f"<th>Likes</th></tr>{rows}</table>")
    else:
        top_html = ("<div class='muted'>No view data yet. Post a few, then click "
                    "<b>Sync my stats</b> in Settings to pull your real numbers.</div>")
    top_card = (f"<div class='card' style='max-width:960px'><h3 style='margin-top:0'>Top "
                f"performing videos</h3>{top_html}</div>")

    # retention — the number that actually decides which Shorts get pushed
    lib_ch = (load(LIBRARY, {}) or {}).get("channel", {})
    an = lib_ch.get("analytics") or {}
    if an.get("videos"):
        titles = {v["id"]: (v.get("title") or "").split("#")[0].strip()[:55]
                  for v in lib_ch.get("live_videos", [])}
        rrows = ""
        ranked = sorted(an["videos"].items(), key=lambda kv: -kv[1]["avg_pct"])
        for vid, d2 in ranked:
            pct = d2["avg_pct"]
            color = "var(--green)" if pct >= 70 else ("var(--gold)" if pct >= 50 else "#e06a6a")
            w = min(100, pct)
            rrows += (f"<tr><td>{dhtml(titles.get(vid, vid))}</td>"
                      f"<td style='width:38%'><div class='pbar'><i style='width:{w:.0f}%;"
                      f"background:{color}'></i></div></td>"
                      f"<td class='v' style='color:{color}'>{pct:.0f}%</td>"
                      f"<td>{d2['avg_sec']}s</td><td>{d2['subs_gained']:+d}</td></tr>")
        retention_card = (
            f"<div class='card' style='max-width:960px'><h3 style='margin-top:0'>Retention — "
            f"what the algorithm actually judges</h3>"
            f"<div class='muted' style='margin-bottom:8px'>Average % of each video people watch. "
            f"<b style='color:var(--green)'>≥70%</b> gets pushed wider · "
            f"<b style='color:#e06a6a'>&lt;50%</b> = the hook loses them. "
            f"Synced {an.get('synced','')}.</div>"
            f"<table class='ptable'><tr><th>Video</th><th></th><th>watched</th>"
            f"<th>avg time</th><th>subs</th></tr>{rrows}</table></div>")
    else:
        retention_card = (
            "<div class='card' style='max-width:960px'><h3 style='margin-top:0'>Retention</h3>"
            "<div class='muted'>The one number views can't show: how much of each video people "
            "actually watch. Connect YouTube in Settings, then click <b>📊 Sync retention</b> "
            "(or tell the coach: “sync retention”).</div></div>")

    themed = [t for t in s["themes"] if t["theme"] != "unlabeled"]
    maxv = max((t["views"] for t in themed), default=0)
    if themed:
        trows = ""
        for t in themed[:8]:
            w = (t["views"] / maxv * 100) if maxv else 0
            trows += (f"<tr><td>{dhtml(t['theme'])}</td><td>{t['count']}</td>"
                      f"<td style='width:45%'><div class='pbar'><i style='width:{w:.0f}%'></i>"
                      f"</div></td><td class='v'>{f(t['views'])}</td></tr>")
        theme_html = (f"<table class='ptable'><tr><th>Theme</th><th># videos</th><th></th>"
                      f"<th>Views</th></tr>{trows}</table>")
        if s["best_theme"]:
            theme_html += (f"<div class='muted' style='margin-top:10px'>→ Your best theme is "
                           f"<b>{dhtml(s['best_theme'])}</b>. Make more of it.</div>")
    else:
        theme_html = "<div class='muted'>Themes rank here once your videos have views.</div>"
    theme_card = (f"<div class='card' style='max-width:960px'><h3 style='margin-top:0'>What's "
                  f"working by theme</h3>{theme_html}</div>")

    def ta(idv, label, hint, value):
        return (f"<div class='field'><label>{label} <small>— {hint}</small></label>"
                f"<textarea id='{idv}'>{tesc(value)}</textarea></div>")
    profile_card = (
        "<div class='card' style='max-width:800px'><h3 style='margin-top:0'>Channel profile — "
        "teach your AI</h3><div class='muted' style='margin-bottom:14px'>Your local AI reads this "
        "every time it writes a script or answers in the Coach. The more accurate this is, the more "
        "your videos sound like <b>your</b> channel.</div>"
        + ta("pf_goal", "Goal", "what success looks like", p["goal"])
        + ta("pf_aud", "Audience", "who you're talking to", p["audience"])
        + ta("pf_style", "Voice / style", "tone, pacing, do's and don'ts", p["style"])
        + ta("pf_notes", "Notes", "niche, themes, anything else", p["notes"])
        + "<button class='primary' onclick='saveProfile()'>Save profile</button></div>")

    return (f"<div class='stats'>{stat_cards}</div>{mon}{retention_card}"
            f"{top_card}{theme_card}{profile_card}")


def build_studio_html():
    """The Story Studio tab: this week's story, the dated plan, and the
    what/where/when upload guide — the whole 'stolen' workflow in one place."""
    lib = load(LIBRARY, {"videos": {}})
    lf = lib.get("longform") or {}
    story_on = (load(CONFIG, {}) or {}).get("story_mode", True)
    word = "story" if story_on else "long-form video"
    emoji = "📖" if story_on else "🎬"
    # story channels show their story long-forms; other niches show every long-form
    items = ({k: v for k, v in lf.items() if v.get("kind") == "story"}
             if story_on else lf)

    # --- this week's big video card ---
    if items:
        name = max(items, key=lambda k: (items[k].get("created", ""), k))
        m = items[name]
        mins, secs = int(m.get("duration_sec", 0) // 60), int(m.get("duration_sec", 0) % 60)
        badge = "✅ uploaded" if m.get("status") == "uploaded" else "🟡 ready to upload"
        thumb = (f"<img src='/lf/{m['thumb']}' width='240' "
                 f"style='border-radius:10px;border:1px solid var(--line)'>"
                 if m.get("thumb") else "")
        upbtn = ("" if m.get("status") == "uploaded" else
                 f"<button class='go' onclick=\"lfUpload('{esc(name)}')\">⤴ Upload to YouTube</button>")
        chaps = " · ".join(n for _, n in m.get("chapters", [])[:5])
        story_card = f"""<div class="mission">
 <div>{thumb}</div>
 <div class="m-body">
  <span class="tag">{emoji} {word} · {mins}m {secs:02d}s · {badge}</span>
  <div class="mtitle">{dhtml(m['title'])}</div>
  <div class="why">Chapters: {dhtml(chaps)}…</div>
  <div class="copyrow">
   <button class='mini' onclick="copyText('{esc(m['title'])}')">copy title</button>
   <button class='mini' onclick="copyText('{esc(m['description'])}')">copy description</button>
   <button class='mini' onclick="copyText('{esc(m.get('ig_caption', ''))}')">copy IG promo</button>
   <button class='mini' onclick="copyText('{esc(m.get('pin_comment', ''))}')">copy pinned comment</button>
   <button class='mini' onclick="reveal('long','{esc(m['file'])}')">📂 Reveal file</button>
  </div>
  <div class="row">{upbtn}
   <button class="primary" onclick="post('/story','Building your weekly {word} (several minutes)',true)">{emoji} Make a new {word}</button>
  </div>
 </div></div>"""
    else:
        story_card = f"""<div class="mission"><div class="m-body">
  <div class="mtitle">No {word} yet — this is the big-channel format.</div>
  <div class="why">One click: the AI writes a chaptered {word} in your channel's voice,
   films it with chapter cards and a thumbnail, and registers it ready to upload. 100% free, all local.</div>
  <div class="row"><button class="primary"
   onclick="post('/story','Building your first {word} (several minutes)',true)">{emoji} Make my first {word}</button></div>
 </div></div>"""

    # --- story-shorts strip ---
    st = [(n, v) for n, v in lib.get("videos", {}).items()
          if str(v.get("id", "")).startswith("st")]
    if st:
        rows = "".join(
            f"<tr><td>{dhtml(v['title'][:58])}</td><td>{v['status']}</td>"
            f"<td>{'auto-queued as a daily video' if v['status'] == 'ready' else '—'}</td></tr>"
            for n, v in sorted(st, key=lambda kv: kv[1]["seq"]))
        shorts_card = (f"<div class='card' style='max-width:960px'><h3 style='margin-top:0'>"
                       f"✂️ Shorts cut from your stories</h3><table class='ptable'>"
                       f"<tr><th>Short</th><th>status</th><th></th></tr>{rows}</table>"
                       f"<div class='muted' style='margin-top:8px'>Ready story-shorts are picked up "
                       f"automatically as the next daily videos — no extra work.</div></div>")
    else:
        shorts_card = ""

    # --- dated plan ---
    plan = load(os.path.join(HERE, "story_plan.json"))
    if plan and plan.get("weeks"):
        rows = ""
        for w in plan["weeks"]:
            sun = date.fromisoformat(w["sunday"]).strftime("%a %d %b")
            sdays = ", ".join(date.fromisoformat(d).strftime("%a %d")
                              for d in w.get("story_shorts_days", []))
            rows += (f"<tr><td><b>{sun}</b></td><td>📖 {dhtml(w['story'])}</td>"
                     f"<td class='v'>{', '.join(w.get('themes', []))}</td></tr>"
                     f"<tr><td class='muted'>{sdays}</td>"
                     f"<td class='muted' colspan='2'>✂️ its Shorts run as those days' daily videos</td></tr>")
        plan_html = (f"<table class='ptable'><tr><th>When</th><th>What</th><th>Themes</th></tr>{rows}</table>"
                     f"<div class='row' style='margin-top:10px'><button class='mini' "
                     f"onclick=\"post('/story_plan','Replanning the next 4 weeks',true)\">🗓 Regenerate plan</button></div>")
    else:
        plan_html = ("<div class='muted'>No plan yet.</div><div class='row' style='margin-top:10px'>"
                     "<button class='go' onclick=\"post('/story_plan','Planning your next 4 weeks',true)\">"
                     "🗓 Plan my next 4 weeks</button></div>")
    plan_card = (f"<div class='card' style='max-width:960px'><h3 style='margin-top:0'>"
                 f"🗓 The next 4 weeks — planned for you</h3>{plan_html}</div>")

    # --- what / where / when guide ---
    guide_card = """<div class="card" style="max-width:960px"><h3 style="margin-top:0">📌 What to upload, where, and when</h3>
<table class="ptable">
<tr><th>When</th><th>What</th><th>Where &amp; how</th></tr>
<tr><td><b>Sunday ~11 AM</b></td><td>📖 The weekly story</td>
 <td>YouTube as a <b>normal video</b> (NOT a Short). The ⤴ button does everything —
 thumbnail + first comment included. Then pin the comment (⋮ → Pin). Post the IG promo caption on Instagram.</td></tr>
<tr><td><b>Every day 7:30 PM</b></td><td>🎬 The daily Short</td>
 <td>YouTube Shorts (autopilot builds it; posts itself once Auto-upload is ON) + the same file to <b>Instagram Reels</b>.</td></tr>
<tr><td><b>Tue &amp; Thu</b></td><td>✂️ Story-Shorts</td>
 <td>Nothing extra to do — they auto-queue as those days' daily videos and pull viewers to the full story.</td></tr>
<tr><td><b>Sunday +2 min</b></td><td>💾 Backup</td><td>Settings → Back up my data.</td></tr>
</table>
<div class="muted" style="margin-top:10px">
<b>Why this works (the rules behind the format):</b> the hook opens on the payoff, never backstory ·
an open loop every ~minute keeps viewers from swiping · one niche, always — mixing resets the algorithm ·
long-form builds the 4,000 watch-hours; Shorts are its discovery engine ·
after each story, check the <b>Retention card</b> (Progress tab): where people drop off is the note for next week's story.</div></div>"""

    return story_card + "<div style='height:18px'></div>" + plan_card + shorts_card + guide_card


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mindset Refuel — AI Pilot</title>
<style>
 :root{--bg:#0b0e15;--panel:#141926;--panel2:#1b2233;--line:#26304a;--ink:#eef1f7;
       --dim:#93a0bd;--gold:#e6b450;--blue:#3f7bff;--green:#54c98a}
 *{box-sizing:border-box}
 body{background:radial-gradient(1400px 700px at 80% -15%,#182238,var(--bg) 55%);
      color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0}
 header{display:flex;align-items:center;gap:14px;padding:16px 34px;border-bottom:1px solid var(--line);
        position:sticky;top:0;background:rgba(11,14,21,.86);backdrop-filter:blur(8px);z-index:9}
 .badge{width:46px;height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center;
        font-weight:800;font-size:18px;color:#fff;background:linear-gradient(150deg,#25407a,#0f1830);
        border:1px solid var(--line);letter-spacing:1px}
 h1{font-size:18px;margin:0}.sub{color:var(--dim);font-size:12px}
 nav{margin-left:24px;display:flex;gap:4px}
 .tab{background:transparent;border:0;color:var(--dim);font-size:14px;font-weight:600;padding:9px 16px;
      border-radius:9px;cursor:pointer}
 .tab.on{background:var(--panel2);color:var(--ink)}
 .chanswitch{margin-left:18px;display:flex;gap:6px;align-items:center}
 .chanbtn{background:var(--panel);border:1px solid var(--line);color:var(--dim);
      border-radius:999px;padding:6px 14px;font-size:13px;font-weight:700;cursor:pointer;text-decoration:none}
 .chanbtn.on{color:#fff;border-color:transparent}
 .runall{background:linear-gradient(150deg,#1a2b1f,#122617);border:1px solid #2a5a3a;
      border-radius:16px;padding:20px 24px;margin-bottom:18px;box-shadow:0 10px 40px #0006;max-width:1100px}
 .runall .mtitle{margin:0 0 4px}
 .runall .big{background:linear-gradient(120deg,#54c98a,#3f7bff);border:0;color:#04120a;font-weight:800;
      font-size:16px;padding:13px 26px;border-radius:12px;cursor:pointer}
 .chips{margin-left:auto;display:flex;gap:8px}
 .chip{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:6px 13px;
       font-size:13px;color:var(--dim)}.chip b{color:var(--ink)}
 main{padding:26px 34px;max-width:1500px;margin:auto}
 section{display:none}section.on{display:block}
 .ask{display:flex;gap:8px;margin-bottom:12px;max-width:760px}
 .ask input{flex:1;background:var(--panel);color:var(--ink);border:1px solid var(--line);
      border-radius:11px;padding:12px 15px;font-size:14px}
 .answerbox{background:#0e1626;border:1px solid var(--line);border-radius:12px;padding:14px;
      font-size:14px;color:#dfe6f5;margin-bottom:14px;display:none;max-width:760px}
 .mission{background:linear-gradient(165deg,#17233d,#111726);border:1px solid var(--line);
          border-radius:18px;padding:24px;display:flex;gap:26px;box-shadow:0 12px 44px #0007;max-width:1100px}
 .mission video{border-radius:12px;border:1px solid var(--line);flex:none}
 .m-body{flex:1;min-width:0}
 .tag{display:inline-block;background:#2a2033;color:var(--gold);border:1px solid #4a3a1e;
      border-radius:999px;padding:3px 12px;font-size:12px;font-weight:700}
 .mtitle{font-size:19px;font-weight:700;margin:12px 0 4px}.why{color:var(--dim);font-size:13px}
 .copyrow{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
 .descbox{background:#0e1626;border:1px solid var(--line);border-radius:10px;padding:11px 13px;
      font-size:12px;color:#cdd6ea;margin-top:8px;line-height:1.55}.descbox b{color:var(--gold)}
 .steps{margin:12px 0 0;padding:0;list-style:none}
 .steps li{padding:6px 0 6px 24px;position:relative;font-size:14px}
 .steps li:before{content:"›";position:absolute;left:6px;color:var(--gold);font-weight:800}
 button{border:0;border-radius:10px;padding:11px 17px;font-size:14px;font-weight:600;cursor:pointer;
        color:#fff;background:var(--panel2);border:1px solid var(--line)}button:hover{filter:brightness(1.15)}
 .primary{background:linear-gradient(150deg,#f0a83a,#e6b450);color:#20160a;border:0;font-size:15px;padding:13px 22px}
 .go{background:linear-gradient(150deg,#3f7bff,#2b5fd6);border:0}
 .mini{padding:6px 12px;font-size:12px}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px}
 .vcard{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
 .vcard video{width:100%;border-radius:8px;border:1px solid var(--line)}
 .vcard .t{font-size:12px;color:var(--ink);margin-top:6px;line-height:1.4}
 .vcard:hover{border-color:var(--gold)}
 .vlink{display:block;color:inherit;text-decoration:none}
 .vnum{font-size:22px;font-weight:800;color:var(--gold);line-height:1.1}
 .vnum span{font-size:12px;color:var(--dim);font-weight:400;margin-left:5px}
 .vmeta{font-size:11px;color:var(--dim);margin-top:5px}
 pre.coach{background:#0e1626;border:1px solid var(--line);border-radius:14px;padding:18px;
      white-space:pre-wrap;font:13px/1.6 inherit;color:#dfe6f5;margin:14px 0 0;max-width:900px}
 .coachhead{display:flex;justify-content:space-between;align-items:center;max-width:900px;margin-bottom:10px}
 .chat{max-width:900px;background:#0e1626;border:1px solid var(--line);border-radius:14px;
      padding:14px;min-height:130px;max-height:52vh;overflow-y:auto;display:flex;
      flex-direction:column;gap:10px;margin-bottom:12px}
 .msg{padding:10px 14px;border-radius:13px;font-size:14px;line-height:1.5;max-width:82%;
      white-space:pre-wrap;word-wrap:break-word}
 .msg.user{align-self:flex-end;background:#243357;color:#eaf0ff;border:1px solid #33477a}
 .msg.assistant,.msg.coach{align-self:flex-start;background:#151d31;color:#dfe6f5;border:1px solid var(--line)}
 .console{max-width:760px;background:#0b1220;border:1px solid var(--line);border-radius:12px;
      padding:12px 14px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
      color:#b9c6e6;white-space:pre-wrap;min-height:22px;margin-top:14px}
 .stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;
      max-width:960px;margin-bottom:18px}
 .stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
 .stat .n{font-size:26px;font-weight:800;color:var(--ink);line-height:1.1}
 .stat .l{font-size:12px;color:var(--dim);margin-top:4px}
 .ptable{width:100%;max-width:900px;border-collapse:collapse;font-size:13px;margin-top:4px}
 .ptable th{text-align:left;color:var(--dim);font-weight:600;padding:8px 10px;
      border-bottom:1px solid var(--line);font-size:12px}
 .ptable td{padding:9px 10px;border-bottom:1px solid #182035;color:#dfe6f5}
 .ptable td.v{font-weight:700;color:var(--gold);white-space:nowrap}
 .pbar{height:10px;border-radius:99px;background:#1a2236;overflow:hidden;min-width:80px}
 .pbar>i{display:block;height:100%;background:linear-gradient(90deg,#e6b450,#f0a83a)}
 .field{margin-bottom:13px;max-width:760px}
 .field label{display:block;font-size:13px;color:var(--ink);margin-bottom:5px;font-weight:600}
 .field small{color:var(--dim);font-weight:400}
 textarea{width:100%;background:#0e1626;color:var(--ink);border:1px solid var(--line);
      border-radius:10px;padding:10px 12px;font:14px/1.5 inherit;resize:vertical;min-height:52px}
 .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;
       margin-bottom:16px;max-width:760px}
 .toggle{display:flex;align-items:center;justify-content:space-between;padding:12px 4px;
         border-bottom:1px solid var(--line)}.toggle:last-child{border:0}
 .toggle .lab{font-size:14px}.toggle .lab small{display:block;color:var(--dim);font-size:12px}
 .sw{position:relative;width:46px;height:26px}.sw input{display:none}
 .sw span{position:absolute;inset:0;background:#2a3350;border-radius:99px;transition:.2s}
 .sw span:before{content:"";position:absolute;height:20px;width:20px;left:3px;top:3px;background:#fff;
      border-radius:50%;transition:.2s}.sw input:checked+span{background:var(--green)}
 .sw input:checked+span:before{transform:translateX(20px)}
 select{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px}
 .muted{color:var(--dim);font-size:12px}
 .cmt{padding:12px 2px;border-bottom:1px solid var(--line)}
 .cmt:last-child{border-bottom:0}
 .cmt-text{font-size:14px;color:#dfe6f5;margin-top:4px;line-height:1.5}
 #toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);display:none;
      background:var(--panel2);border:1px solid var(--line);border-radius:12px;
      padding:12px 20px;font-size:14px;color:var(--ink);box-shadow:0 10px 40px #000a;
      z-index:50;max-width:80vw;text-align:center}
 #toast.err{border-color:#7a3b3b;background:#2a1717}
</style></head><body>

<header>
 <div class="badge">{brand_initials}</div>
 <div><h1>{ch_title}</h1><div class="sub">AI Pilot · {today}</div></div>
 <div class="chanswitch">{channel_switcher}</div>
 <nav>
  <button class="tab on" data-t="today" onclick="tab('today')">Today</button>
  <button class="tab" data-t="studio" onclick="tab('studio')">Studio 📖</button>
  <button class="tab" data-t="uploaded" onclick="tab('uploaded')">Uploaded</button>
  <button class="tab" data-t="progress" onclick="tab('progress')">Progress</button>
  <button class="tab" data-t="coach" onclick="tab('coach')">Coach</button>
  <button class="tab" data-t="settings" onclick="tab('settings')">Settings</button>
 </nav>
 <div class="chips">{streak_chip}<div class="chip">{subs} <b>subs</b></div>
  <div class="chip"><b>{posted}</b> posted</div></div>
</header>

<main>
 <section id="today" class="on">
  <div class="ask"><input id="q" placeholder="Ask the bot anything… e.g. how do I upload?"
     onkeydown="if(event.key==='Enter')askBot()"><button onclick="askBot()">Ask</button></div>
  <div id="answer" class="answerbox"></div>
  {runall_html}
  {evening_html}
  {mission_html}
  {longform_html}
 </section>

 <section id="studio">
  {studio_html}
 </section>

 <section id="uploaded">
  {comments_html}
  <div class="grid">{uploaded_html}</div>
 </section>

 <section id="progress">
  {progress_html}
 </section>

 <section id="coach">
  <div class="coachhead">
   <div><h3 style="margin:0">Coach chat</h3>
    <div class="muted">Ask anything — it knows your real numbers · {coach_engine}</div></div>
   <button class="mini" onclick="coachReset()">Clear chat</button>
  </div>
  <div id="chat" class="chat">{coach_chat_html}</div>
  <div class="ask" style="max-width:900px">
   <input id="cq" placeholder='Chat, or command me: "make today&#39;s video" · "make a long video" · "status"'
      onkeydown="if(event.key==='Enter')coachSend()">
   <button class="go" onclick="coachSend()">Send</button>
  </div>
  <div class="row">
   <button onclick="post('/coach','Analyzing your real numbers',true)">📊 Full report on my numbers</button>
  </div>
  {coach_html}
 </section>

 <section id="settings">
  <div class="card"><h3 style="margin-top:0">Features</h3>{toggles}</div>
  <div class="card"><h3 style="margin-top:0">YouTube connection (Google)</h3>{google_html}</div>
  <div class="card"><h3 style="margin-top:0">Network</h3>{network_html}</div>
  <div class="card"><h3 style="margin-top:0">Tools</h3>
   <div class="muted" style="margin-bottom:10px">Each tool prints live output below so you can see it working.</div>
   <div class="row">
    <button onclick="post('/sync_stats','Syncing your channel stats',true)">⟳ Sync my stats</button>
    <button onclick="post('/scan','Scanning trends',false)">📈 Trend scan now</button>
    <button onclick="post('/longform','Building a long-form video (several minutes)',true)">🎥 Make long-form video</button>
    <button onclick="post('/doctor','Running the health check',false)">🩺 Health check</button>
    <button onclick="post('/sync_analytics','Pulling retention analytics',true)">📊 Sync retention</button>
    <button onclick="post('/apply_pins','Posting questions on all videos',true)">📌 Pin questions everywhere</button>
    <button onclick="backup()">💾 Back up my data</button>
   </div>
   <pre id="console" class="console">{console_init}</pre>
  </div>
 </section>
</main>
<div id="toast"></div>

<script>
 let RELOAD_AFTER=false;
 function tab(t){document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id===t));
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
  try{localStorage.setItem('mrtab',t)}catch(e){}}
 window.addEventListener('load',()=>{try{const t=localStorage.getItem('mrtab');if(t)tab(t)}catch(e){}
  const box=document.getElementById('chat');if(box)box.scrollTop=box.scrollHeight;});
 function copyText(t){navigator.clipboard.writeText(t);toast('Copied ✓',false,1500)}
 function toast(msg,err,hideMs){const el=document.getElementById('toast');
  el.textContent=msg;el.className=err?'err':'';el.style.display='block';
  if(hideMs)setTimeout(()=>{el.style.display='none'},hideMs)}
 function setConsole(txt){const c=document.getElementById('console');if(c)c.textContent=txt}
 async function poll(){const j=await(await fetch('/progress')).json();
  const err=(j.done_msg||'').toLowerCase().includes('fail');
  const logtxt=(j.log&&j.log.length)?j.log.join('\\n'):'Working…';
  setConsole(logtxt);
  toast(j.done_msg||(j.log.length?j.log[j.log.length-1]:'Working…'),err);
  if(j.running){setTimeout(poll,1000);return}
  if(j.done_msg){setConsole(((j.log||[]).join('\\n')+'\\n\\n'+j.done_msg).trim());
   if(RELOAD_AFTER&&!err){setTimeout(()=>location.reload(),1200)}
   else{toast(j.done_msg,err,6000)}}}
 // The channel currently shown (set from the server-rendered page).
 const CURCH = (new URLSearchParams(location.search).get('channel')) || 'motivation';
 function withCh(u){return u+(u.includes('?')?'&':'?')+'channel='+encodeURIComponent(CURCH)}
 async function run(u,l,reload){RELOAD_AFTER=!!reload;toast(l+'…');setConsole(l+'…');
  await fetch(withCh(u),{method:'POST'});poll()}
 async function post(u,l,reload){return run(u,l,reload)}
 async function runAll(){RELOAD_AFTER=true;toast('Running all 3 channels…');
  setConsole('Preparing today\\'s Short for every active channel…');
  await fetch('/run_all',{method:'POST'});poll()}
 async function pilot(){return run('/pilot','Preparing today\\'s video (a minute or two)',true)}
 async function autoup(){return run('/autoupload','Uploading today\\'s video — it goes live at prime time',true)}
 async function queueNow(){return run('/queue_now','Uploading your next queued video to YouTube',true)}
 async function planQueue(){return run('/plan_queue','Giving your ready videos a release date',true)}
 async function done(){await fetch(withCh('/done_today'),{method:'POST'});location.reload()}
 async function setCfg(k,v){await fetch('/config?key='+encodeURIComponent(k)+'&val='+encodeURIComponent(v),{method:'POST'});toast('Saved ✓',false,1500)}
 async function askBot(){const q=document.getElementById('q').value.trim();if(!q)return;
  const b=document.getElementById('answer');b.style.display='block';b.textContent='…';
  const j=await(await fetch('/ask?q='+encodeURIComponent(q))).json();b.textContent=j.answer}
 function addMsg(who,text){const box=document.getElementById('chat');
  const d=document.createElement('div');d.className='msg '+who;d.textContent=text;
  box.appendChild(d);box.scrollTop=box.scrollHeight;return d}
 async function coachSend(){const i=document.getElementById('cq');const q=i.value.trim();if(!q)return;
  i.value='';addMsg('user',q);const t=addMsg('assistant','…thinking');
  try{const j=await(await fetch('/coach_chat?q='+encodeURIComponent(q))).json();
   t.textContent=j.answer;
   if(j.action){RELOAD_AFTER=!!j.reload;poll()}}
  catch(e){t.textContent='(coach unreachable — is Ollama running?)'}}
 async function setAutopilot(on){toast(on?'Turning the morning autopilot ON…':'Turning autopilot OFF…');
  const j=await(await fetch('/autopilot?on='+on,{method:'POST'})).json();
  toast(j.msg,!j.ok,5000)}
 async function reveal(kind,f){await fetch('/reveal?kind='+kind+'&f='+encodeURIComponent(f),{method:'POST'});
  toast('Opened in Finder — drag the file into YouTube ✓',false,3500)}
 async function draftReply(i){const d=document.getElementById('dr'+i);
  d.style.display='block';d.textContent='…writing a reply';
  try{const j=await(await fetch('/draft_reply?i='+i)).json();
   d.textContent='';const t=document.createElement('div');t.textContent=j.reply;d.appendChild(t);
   const row=document.createElement('div');row.style.marginTop='8px';row.style.display='flex';row.style.gap='8px';
   const s=document.createElement('button');s.className='mini go';s.textContent='↩ Send reply on YouTube';
   s.onclick=async()=>{s.disabled=true;s.textContent='sending…';
    const r=await(await fetch('/send_reply?i='+i+'&text='+encodeURIComponent(j.reply),{method:'POST'})).json();
    toast(r.msg,!r.ok,5000);s.textContent=r.ok?'✓ sent':'✗ failed — copy instead';s.disabled=r.ok};
   const b=document.createElement('button');b.className='mini';b.textContent='copy reply';
   b.onclick=()=>copyText(j.reply);
   row.appendChild(s);row.appendChild(b);d.appendChild(row);
  }catch(e){d.textContent='(could not draft — is Ollama running?)'}}
 async function backup(){toast('Backing up your data…');
  const j=await(await fetch('/backup',{method:'POST'})).json();
  toast(j.msg,!j.ok,5000)}
 async function lfUpload(f){const u='/upload_longform'+(f?'?f='+encodeURIComponent(f):'');
  return run(u,'Uploading to YouTube (video, thumbnail, first comment)',true)}
 async function coachReset(){await fetch('/coach_reset',{method:'POST'});
  const box=document.getElementById('chat');box.innerHTML='';
  addMsg('assistant','Cleared. Ask me anything about growing the channel.')}
 function val(id){const e=document.getElementById(id);return e?e.value:''}
 async function saveProfile(){const b={goal:val('pf_goal'),audience:val('pf_aud'),
   style:val('pf_style'),notes:val('pf_notes')};
  toast('Saving profile…');
  await fetch('/save_profile',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(b)});
  toast('Channel profile saved ✓ — your AI will use it from now on',false,3000)}
</script>
</body></html>"""


def yt_connected():
    """One-time Google connect done → every upload/comment is one click."""
    return (os.path.exists(os.path.join(HERE, "client_secret.json"))
            and os.path.exists(os.path.join(HERE, "assets", "yt_token.json")))


@app.route("/")
def home():
    cur = sel_channel()                 # ?channel= → point data paths at it
    lib = load(LIBRARY, {"videos": {}})
    ch = lib.get("channel", {})
    cfg = load(CONFIG, {})
    posted = (ch.get("video_count")
              or sum(1 for v in lib["videos"].values() if v.get("status") == "uploaded"))
    m = mission()

    # the ONE button: sync → pins → today's video uploaded (prime-time) → checklist
    if yt_connected():
        evening_html = """<div class="mission" style="margin-bottom:18px"><div class="m-body">
  <div class="mtitle">🌇 One click runs your whole evening</div>
  <div class="why">Syncs your numbers, posts question-comments, uploads today's video
   (it goes live at 7:30 PM by itself — click any time of day), and leaves you a
   tiny checklist of the human bits (pin, Reel, replies).</div>
  <div class="row"><button class="primary"
   onclick="run('/evening','Running your whole evening — sync, pins, upload',true)">🌇 Do my evening — 1 click</button></div>
 </div></div>"""
    else:
        evening_html = ""

    if m:
        pin = m.get("pin_comment") or ""
        pinbtn = (f"<button class='mini' onclick=\"copyText('{esc(pin)}')\">copy pinned comment</button>"
                  if pin else "")
        pinbox = (f"<div class='descbox'><b>Pinned comment</b> (post it, then ⋮ → Pin)"
                  f"<br>{dhtml(pin)}</div>" if pin else "")
        copyrow = (
            f"<button class='mini' onclick=\"copyText('{esc(m['title'])}')\">copy title</button>"
            f"<button class='mini' onclick=\"copyText('{esc(m['description'])}')\">copy description</button>"
            f"<button class='mini' onclick=\"copyText('{esc(m['ig_caption'])}')\">copy IG caption</button>"
            f"{pinbtn}")
        steps = "".join(f"<li>{s}</li>" for s in m["steps"])
        autobtn = ("<button class='primary' onclick='autoup()'>⤴ Upload to YouTube — 1 click</button>"
                   if yt_connected() else "")
        qu = str(cfg.get("queue_until") or "").strip()
        qwarn = ""
        try:
            queue_covers = bool(qu) and date.today() <= date.fromisoformat(qu)
        except ValueError:
            queue_covers = False
            qwarn = (f"<div class='why' style='color:var(--gold)'>⚠ Settings problem: "
                     f"queue_until '{esc(qu)}' is not YYYY-MM-DD — the one-per-day "
                     f"queue guard is OFF.</div>")
        if autobtn and queue_covers:
            qwarn = (f"<div class='why' style='color:var(--gold)'>⚠ Your hand-scheduled "
                     f"queue already posts today (through {qu}) — uploading now would "
                     f"mean 2 videos in one day.</div>")
        mission_html = f"""<div class="mission">
 <video src="/video/{m['file']}?channel={cur}" width="200" height="356" controls preload="metadata"></video>
 <div class="m-body">
  <span class="tag">{m['theme']} · post {m['post_time']}</span>
  <div class="mtitle">{dhtml(m['title'])}</div><div class="why">{dhtml(m['reason'])}</div>
  <div class="copyrow">{copyrow}</div>
  <div class="descbox"><b>Description</b><br>{dhtml(m['description'])}</div>
  <div class="descbox"><b>Instagram caption</b><br>{dhtml(m['ig_caption'])}</div>
  {pinbox}
  <ul class="steps">{steps}</ul>
  <div class="row">
   <button class="mini" onclick="reveal('short','{esc(m['file'])}')">📂 Reveal video file</button>
   <button class="mini" onclick="window.open('https://www.youtube.com/upload','_blank')">⬆ Open YouTube upload</button>
   <button class="mini" onclick="window.open('https://www.instagram.com','_blank')">📷 Open Instagram</button>
  </div>
  <div class="row">{autobtn}<button class="go" onclick="done()">✓ I uploaded it myself</button>
   <button class="go" onclick="pilot()">↻ Make a different one</button></div>
  {qwarn}
 </div></div>"""
    else:
        mission_html = queue_card(cur)

    # weekly long-form card (the watch-hours engine — one per week is plenty)
    lf_name, lf = latest_longform()
    if lf:
        mins = int(lf.get("duration_sec", 0) // 60)
        secs = int(lf.get("duration_sec", 0) % 60)
        state = lf.get("status", "ready")
        badge = "✅ uploaded" if state == "uploaded" else "🟡 ready to upload"
        thumb = (f"<img src='/lf/{lf['thumb']}?channel={cur}' width='240' "
                 f"style='border-radius:10px;border:1px solid var(--line)'>"
                 if lf.get("thumb") else "")
        upbtn = ("" if state == "uploaded" else
                 "<button class='go' onclick='lfUpload()'>⤴ Upload to YouTube</button>")
        longform_html = f"""<div class="mission" style="margin-top:18px">
 <div>{thumb}</div>
 <div class="m-body">
  <span class="tag">long-form · {mins}m {secs:02d}s · {badge}</span>
  <div class="mtitle">{dhtml(lf['title'])}</div>
  <div class="why">Long-form builds the 4,000 watch-hours path. Post one a week.</div>
  <div class="copyrow">
   <button class='mini' onclick="copyText('{esc(lf['title'])}')">copy title</button>
   <button class='mini' onclick="copyText('{esc(lf['description'])}')">copy description</button>
   <button class='mini' onclick="copyText('{esc(lf.get('ig_caption',''))}')">copy IG promo</button>
   <button class='mini' onclick="copyText('{esc(lf.get('pin_comment',''))}')">copy pinned comment</button>
   <button class='mini' onclick="reveal('long','{esc(lf['file'])}')">📂 Reveal file</button>
   <button class='mini' onclick="window.open('https://www.youtube.com/upload','_blank')">⬆ Open YouTube upload</button>
  </div>
  <div class="row">{upbtn}
   <button onclick="post('/longform','Building a new long-form video (several minutes)',true)">🎥 Make a new one</button>
  </div>
 </div></div>"""
    else:
        longform_html = """<div class="mission" style="margin-top:18px"><div class="m-body">
  <div class="mtitle">No long-form video yet.</div>
  <div class="why">A 4-minute chaptered video, written and voiced like your Shorts —
   with a thumbnail, chapters and description done for you. One per week builds the
   4,000 watch-hours monetization path.</div>
  <div class="row"><button class="go"
   onclick="post('/longform','Building your long-form video (several minutes)',true)">🎥 Make my first long video</button></div>
 </div></div>"""

    try:
        progress_html = build_progress_html()
    except Exception as e:
        progress_html = f"<div class='muted'>Progress unavailable: {e}</div>"

    try:
        studio_html = build_studio_html()
    except Exception as e:
        studio_html = f"<div class='muted'>Studio unavailable: {e}</div>"

    # Prefer the REAL channel (works even after you delete local files); each
    # card links to the live Short. Fall back to local players if not synced.
    live = ch.get("live_videos") or []
    if live:
        def _ucard(v):
            title = dhtml((v.get("title") or "").split("#")[0].strip()[:60])
            url = v.get("url", "")
            a0 = f"<a href='{url}' target='_blank' rel='noopener' class='vlink'>" if url else "<div class='vlink'>"
            a1 = "</a>" if url else "</div>"
            return (f"<div class='vcard'>{a0}"
                    f"<div class='vnum'>{v.get('views',0):,}<span>views</span></div>"
                    f"<div class='t'>{title}</div>"
                    f"<div class='vmeta'>{v.get('likes',0)} likes · {v.get('comments',0)} comments</div>"
                    f"{a1}</div>")
        uploaded_html = "".join(_ucard(v) for v in sorted(live, key=lambda v: -v.get("views", 0)))
    else:
        up = [(n, v) for n, v in sorted(lib["videos"].items(), key=lambda kv: -kv[1]["seq"])
              if v.get("status") == "uploaded" and os.path.exists(os.path.join(OUTPUT, n))]
        uploaded_html = "".join(
            f"<div class='vcard'><video src='/video/{n}' preload='none' controls></video>"
            f"<div class='t'>{v['title'][:52]}</div></div>" for n, v in up) or \
            "<div class='muted'>Nothing uploaded yet. Click ‘Sync my stats’ in "\
            "Settings to pull your live videos from YouTube.</div>"

    # streak chip — the one number that decides whether this channel grows
    streak_chip = ""
    try:
        import progress as _prog
        _prog.set_channel(CHANNEL)         # this channel's streak, not motivation's
        _sum = _prog.summary()
        _streak, _since = _sum.get("streak"), _sum.get("days_since_post")
        if _streak is not None:
            if _streak > 0:
                streak_chip = (f"<div class='chip'>🔥 <b>{_streak}</b>-day streak</div>")
            else:
                streak_chip = (f"<div class='chip' style='border-color:#7a3b3b'>"
                               f"⚠️ <b>{_since}</b> days since last post</div>")
    except Exception:
        pass

    # comment inbox — reply fast, grow fast (synced by 'Sync my stats')
    comments = ch.get("recent_comments") or []
    if comments:
        items = ""
        for i, c in enumerate(comments[:15]):
            when = (c.get("published") or "")[:10]
            vurl = c.get("url", "")
            openbtn = (f"<button class='mini' onclick=\"window.open('{vurl}','_blank')\">"
                       f"open video</button>" if vurl else "")
            items += (f"<div class='cmt'><div><b>{dhtml(c.get('author',''))}</b> "
                      f"<span class='muted'>on “{dhtml(c.get('video',''))}” · {when}</span></div>"
                      f"<div class='cmt-text'>{dhtml(c.get('text',''))}</div>"
                      f"<div class='row' style='margin-top:8px'>"
                      f"<button class='mini' onclick='draftReply({i})'>💡 Draft my reply</button>"
                      f"{openbtn}</div>"
                      f"<div id='dr{i}' class='descbox' style='display:none'></div></div>")
        comments_html = (f"<div class='card' style='max-width:900px;margin-bottom:20px'>"
                         f"<h3 style='margin-top:0'>💬 Recent comments "
                         f"<span class='muted'>reply within the hour — it's the #1 growth signal</span></h3>"
                         f"{items}</div>")
    elif live:
        pins_done = len(ch.get("pins_posted", []))
        pinall = ("" if pins_done >= len(live) else
                  "<div class='row' style='margin-top:10px'><button class='go' "
                  "onclick=\"post('/apply_pins','Posting your question on every live video',true)\">"
                  "📌 Post my question on all videos</button></div>")
        comments_html = ("<div class='card' style='max-width:900px;margin-bottom:20px'>"
                         "<h3 style='margin-top:0'>💬 Comments</h3><div class='muted'>"
                         "No viewer comments yet — seed them: one click posts your "
                         "engagement question on every live video (needs the YouTube "
                         "connection in Settings). New comments appear here after "
                         "<b>Sync my stats</b>.</div>" + pinall + "</div>")
    else:
        comments_html = ""

    _report = (JOB.get("coach", "").replace("&", "&amp;")
               .replace("<", "&lt;").replace(">", "&gt;"))
    coach_html = f"<pre class='coach'>{_report}</pre>" if JOB.get("coach") else ""

    if COACH_CHAT:
        coach_chat_html = "".join(
            f"<div class='msg {'user' if m['role']=='user' else 'assistant'}'>"
            f"{dhtml(m['content'])}</div>" for m in COACH_CHAT)
    else:
        coach_chat_html = ("<div class='msg assistant'>Hey — I'm your assistant and I can "
            "see your real numbers AND control the channel. Commands I run: "
            "\"make today's video\" · \"make a long video\" · \"sync my stats\" · "
            "\"sync retention\" · \"pin questions on my videos\" · \"scan trends\" · "
            "\"analyze\" · \"status\". Or just ask me anything.</div>")

    try:
        import ai_brain
        coach_engine = "powered by " + ai_brain.engine_status()
    except Exception:
        coach_engine = "offline coach"

    if JOB.get("log"):
        console_init = "\n".join(JOB["log"])
        console_init = (console_init.replace("&", "&amp;")
                        .replace("<", "&lt;").replace(">", "&gt;"))
        if JOB.get("done_msg"):
            console_init += "\n\n" + JOB["done_msg"]
    else:
        console_init = "Output from tools appears here."

    feats = [("schedule_uploads", "Prime-time publishing",
              "Click upload ANY time — the video goes live at 7:30 PM IST by itself"),
             ("story_mode", "Sunday story mode", "Weekly long-form = a story (the best retention format)"),
             ("endcap", "Subscribe end-cap", "2s branded 'Subscribe' outro inside every video"),
             ("character", "Stick-figure narrator", "Off is best for a clean look"),
             ("scan_on_generate", "Scan trends on every video", "Different topics over time"),
             ("ai_scripts", "AI-written scripts", "Needs Ollama or an API key"),
             ("auto_upload", "Auto-upload to YouTube", "Needs one-time Google setup")]
    on_by_default = {"endcap", "story_mode", "schedule_uploads"}
    toggles = ""
    for k, lab, hint in feats:
        ck = "checked" if cfg.get(k, k in on_by_default) else ""
        toggles += (f"<div class='toggle'><div class='lab'>{lab}<small>{hint}</small></div>"
                    f"<label class='sw'><input type='checkbox' {ck} "
                    f"onchange=\"setCfg('{k}',this.checked)\"><span></span></label></div>")
    ap_ck = "checked" if os.path.exists(AUTOPILOT_PLIST) else ""
    toggles += (f"<div class='toggle'><div class='lab'>Morning autopilot"
                f"<small>Builds today's video at 7 AM by itself (+ Sunday long-form). "
                f"Works without a hosted model — it can run locally.</small></div>"
                f"<label class='sw'><input type='checkbox' {ap_ck} "
                f"onchange=\"setAutopilot(this.checked)\"><span></span></label></div>")
    priv = cfg.get("upload_privacy", "public")
    opts = "".join(f"<option {'selected' if priv==o else ''}>{o}</option>"
                   for o in ("public", "unlisted", "private"))
    toggles += (f"<div class='toggle'><div class='lab'>Upload privacy<small>for auto-upload</small></div>"
                f"<select onchange=\"setCfg('upload_privacy',this.value)\">{opts}</select></div>")
    voice = cfg.get("voice", "")
    vopts = "".join(
        f"<option value='{v}' {'selected' if voice == v else ''}>{lbl}</option>"
        for v, lbl in [("", "US male — Andrew (current)"),
                       ("en-IN-PrabhatNeural", "Indian English male — Prabhat"),
                       ("en-IN-NeerjaNeural", "Indian English female — Neerja")])
    toggles += (f"<div class='toggle'><div class='lab'>Voice style"
                f"<small>Your audience is mostly India — try the Indian voices on a few "
                f"videos and compare views</small></div>"
                f"<select onchange=\"setCfg('voice',this.value)\">{vopts}</select></div>")

    cs_ok = os.path.exists(os.path.join(HERE, "client_secret.json"))
    tok_ok = os.path.exists(os.path.join(HERE, "assets", "yt_token.json"))
    if cs_ok and tok_ok:
        gstat = ("<div style='color:var(--green);font-weight:600'>✅ Connected — the system can "
                 "manage your channel</div><div class='muted'>Auto-upload, retention analytics, "
                 "comment replies, question-comments on every video, thumbnails.</div>")
    elif cs_ok:
        gstat = ("<div style='color:var(--gold);font-weight:600'>🟡 One click left</div>"
                 "<div class='muted'>client_secret.json found. Approve once in your browser and "
                 "the system takes over.</div>"
                 "<div class='row' style='margin-top:10px'><button class='go' "
                 "onclick=\"post('/google_connect','Opening Google — approve in the browser',true)\">"
                 "🔗 Connect YouTube now</button></div>")
    else:
        gstat = ("<div style='color:var(--gold);font-weight:600'>⬜ Not connected (one-time, ~5 min, free)</div>"
                 "<div class='muted' style='margin-top:6px'>This gives the system control of your "
                 "channel: <b>auto-upload</b>, <b>retention analytics</b> (the number that decides "
                 "which Shorts get pushed), <b>one-click question comments on every video</b>, "
                 "<b>direct comment replies</b> and <b>thumbnails</b>.<br>"
                 "1. console.cloud.google.com → your existing project<br>"
                 "2. Enable <b>YouTube Data API v3</b> AND <b>YouTube Analytics API</b><br>"
                 "3. OAuth consent screen → External → add yourself as a Test user<br>"
                 "4. Credentials → Create credentials → OAuth client ID → <b>Desktop app</b><br>"
                 "5. Download the JSON → rename to <b>client_secret.json</b> → drop it in ~/youtube/ "
                 "— a <b>Connect</b> button appears here.</div>")
    google_html = gstat

    import netcfg
    mode = cfg.get("proxy_mode", "on" if cfg.get("use_proxy") else "off")
    px = tesc(cfg.get("proxy", ""))
    try:
        detected = netcfg.detected()
    except Exception as e:
        detected = f"(detection error: {e})"
    modeopts = "".join(
        f"<option value='{v}' {'selected' if mode == v else ''}>{lbl}</option>"
        for v, lbl in [("auto", "Auto-detect (recommended)"),
                       ("on", "Always use proxy"),
                       ("off", "Never use proxy (direct)")])
    network_html = (
        f"<div class='toggle'><div class='lab'>Network mode"
        f"<small>Auto figures out college vs hotspot by itself</small></div>"
        f"<select onchange=\"setCfg('proxy_mode',this.value);setTimeout(()=>location.reload(),500)\">"
        f"{modeopts}</select></div>"
        f"<div class='muted' style='margin:12px 0 2px'>Detected now: <b style='color:var(--gold)'>"
        f"{detected}</b></div>"
        f"<div class='field' style='margin-top:12px'><label>Proxy address "
        f"<small>— your college proxy host:port</small></label>"
        f"<input value=\"{px}\" onchange=\"setCfg('proxy',this.value)\" "
        f"style=\"width:100%;max-width:420px;background:#0e1626;color:var(--ink);"
        f"border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:14px inherit\"></div>"
        f"<div class='muted'>On <b>Auto</b>, the app checks whether the college proxy is "
        f"reachable and switches by itself — no need to toggle when you change networks. If the "
        f"proxy blocks the neural voice, videos still build with the offline voice. Your local "
        f"AI (Ollama) always stays direct.</div>"
        f"<div class='row' style='margin-top:12px'>"
        f"<button class='go' onclick=\"post('/netcheck','Testing the connection to YouTube',false)\">"
        f"🌐 Test my connection to YouTube</button></div>"
        f"<div class='muted'>Run this once <b>on the college wifi</b>. It doesn't just ping the "
        f"proxy — it actually calls Google through it, which is the only way to tell a working "
        f"proxy from one that answers and then refuses everything.</div>")

    # ---- channel switcher (one pill per channel) + Run-all-3 card ----
    cmeta = _paths.channel_meta(cur)
    switcher_bits = []
    for c in channels():
        on = "on" if c["slug"] == cur else ""
        col = c.get("brand_color", [240, 190, 70])
        style = (f"background:rgb({col[0]},{col[1]},{col[2]});" if c["slug"] == cur else "")
        switcher_bits.append(
            f"<a class='chanbtn {on}' style=\"{style}\" href='/?channel={c['slug']}'>"
            f"{dhtml(c.get('name', c['slug']))}</a>")
    channel_switcher = "".join(switcher_bits)

    # ---- MASTER strip: every channel at a glance, all on one screen ----
    cal_items = (load(os.path.join(HERE, "schedule.json"), {}) or {}).get("items") or []
    today_iso = date.today().isoformat()
    master_cards = []
    for c in channels():
        s = c["slug"]; Pc = _paths.paths(s)
        libc = load(Pc["library"], {}) or {}
        chc = libc.get("channel", {}) or {}
        # Only call it today's video if the mission is actually for TODAY. The
        # card used to show yesterday's title while the page below it said "no
        # video prepared", which read as "ready" and sent you to click Prepare.
        mc = load(Pc["today"], {}) or {}
        fresh = mc.get("date") == date.today().isoformat()
        # The calendar is the strongest signal: if today's video is already on
        # YouTube waiting for its release time, say so. Otherwise this card
        # nags you to post something that is, in fact, already handled.
        sched = next((i for i in cal_items
                      if i["channel"] == s and i["publish_date"] == today_iso
                      and i.get("kind") != "longform"), None)
        if sched and sched["status"] == "uploaded":
            mt = "✅ posts by itself tonight"
        elif sched:
            mt = "🕓 queued — uploads automatically"
        elif fresh:
            mt = "🎬 " + ((mc.get("title", "") or "").split("#")[0].strip()
                          or "ready to post")[:32]
        else:
            # nothing for today — but a buffered video may already be built,
            # in which case preparing is instant (no new render).
            buffered = any(
                v.get("status") == "ready"
                and os.path.exists(os.path.join(Pc["output"], n))
                for n, v in (libc.get("videos") or {}).items())
            mt = ("📦 buffered — 1 click to post" if buffered
                  else "⚪ needs preparing")
        col = c.get("brand_color", [240, 190, 70])
        ring = "2px solid #fff" if s == cur else "1px solid var(--line)"
        master_cards.append(
            f"<a href='/?channel={s}' style=\"flex:1;min-width:180px;text-decoration:none;"
            f"background:#0e1626;border:{ring};border-radius:12px;padding:12px 14px;color:var(--ink)\">"
            f"<div style='display:flex;align-items:center;gap:8px'>"
            f"<span style='width:12px;height:12px;border-radius:3px;"
            f"background:rgb({col[0]},{col[1]},{col[2]})'></span>"
            f"<b>{dhtml(c.get('name', s))}</b></div>"
            f"<div class='muted' style='margin:6px 0 4px'>{chc.get('subs',0):,} subs · "
            f"{chc.get('video_count',0)} posted</div>"
            f"<div style='font-size:13px;opacity:.85'>{dhtml(mt)}</div></a>")
    master_html = ("<div class='mtitle' style='margin-bottom:8px'>📺 All channels — at a glance "
                   "(click one to open it)</div>"
                   "<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px'>"
                   + "".join(master_cards) + "</div>")

    n_active = len(active_channels())
    is_sun = date.today().weekday() == 6
    runall_html = (master_html
        + calendar_html()
        + f"<div class='runall'><div class='mtitle'>🚀 Run all {n_active} channels — one click</div>"
        f"<div class='why'>Generates today's Short for every channel"
        + (" and builds each weekly long-form (it's Sunday)" if is_sun else "")
        + f". They then auto-upload themselves at prime time — you don't lift a finger.</div>"
        f"<div class='row' style='margin-top:12px'>"
        f"<button class='big' onclick='runAll()'>Run all {n_active} — one click</button></div></div>")

    # channel initials for the header badge (e.g. "MB" for Mind Blown)
    brand_initials = "".join(w[0] for w in cmeta.get("name", "MR").split()[:2]).upper() or "MR"
    ch_title = ch.get("title") or cmeta.get("name", "Mindset Refuel")

    return (PAGE.replace("{ch_title}", ch_title)
            .replace("{brand_initials}", brand_initials)
            .replace("{channel_switcher}", channel_switcher)
            .replace("{runall_html}", runall_html)
            .replace("{subs}", f"{ch.get('subs',0):,}").replace("{posted}", str(posted))
            .replace("{today}", date.today().strftime("%a, %d %b %Y"))
            .replace("{evening_html}", evening_html)
            .replace("{mission_html}", mission_html)
            .replace("{longform_html}", longform_html)
            .replace("{studio_html}", studio_html)
            .replace("{streak_chip}", streak_chip)
            .replace("{comments_html}", comments_html)
            .replace("{google_html}", google_html)
            .replace("{uploaded_html}", uploaded_html)
            .replace("{progress_html}", progress_html)
            .replace("{coach_chat_html}", coach_chat_html)
            .replace("{coach_engine}", coach_engine)
            .replace("{coach_html}", coach_html)
            .replace("{console_init}", console_init)
            .replace("{toggles}", toggles)
            .replace("{network_html}", network_html))


@app.route("/video/<path:name>")
def video(name):
    ch = request.args.get("channel") or CHANNEL
    return send_from_directory(_paths.paths(ch)["output"], name)


_KICK_LOCK = threading.Lock()


def _kick(target, *a):
    with _KICK_LOCK:               # two fast clicks must not start two jobs
        if JOB["running"]:
            return jsonify(ok=False)
        JOB["running"] = True; JOB["done_msg"] = ""
    threading.Thread(target=target, args=a, daemon=True).start()
    return jsonify(ok=True)


def _req_channel():
    """Channel for a POST action: form field, query arg, else motivation."""
    slug = (request.form.get("channel") or request.args.get("channel")
            or _paths.DEFAULT_CHANNEL)
    valid = {c["slug"] for c in channels()}
    return slug if slug in valid else _paths.DEFAULT_CHANNEL


@app.route("/run_all", methods=["POST"])
def run_all(): return _kick(run_all_job)


@app.route("/pilot", methods=["POST"])
def pilot(): return _kick(job, ["pilot.py"], "Pilot preparing today's video (a minute or two)", "Ready ✅", _req_channel())


@app.route("/autoupload", methods=["POST"])
def autoupload(): return _kick(job, ["upload_youtube.py"], "Auto-uploading to YouTube",
                               "Uploaded ✅ — the console shows when it goes live", _req_channel())


def queue_now_job(channel=None):
    """Send this channel's next queued video to YouTube now. It keeps its planned
    release date, so this can never put two videos on one day.

    The message reports what actually happened. A run that hit the daily API
    quota uploads nothing and still exits cleanly — announcing "On YouTube ✅"
    there is the same silent lie that made uploads go missing in the first place.
    """
    try:
        JOB["log"] = []
        run(["schedule_queue.py", "--run", "--now", "--limit", "1"],
            "Uploading your next queued video", channel=channel)
        tail = " ".join(JOB["log"][-8:])
        if "quota budget reached" in tail or "quotaExceeded" in tail:
            JOB["done_msg"] = ("Not sent — today's YouTube upload quota is used up "
                               "(6 uploads a day for all channels together). It "
                               "uploads by itself tomorrow; nothing is lost.")
        elif "Nothing due" in tail or "Done — 0 uploaded" in tail:
            JOB["done_msg"] = "Nothing left in this channel's queue to send."
        elif "FAILED" in tail:
            JOB["done_msg"] = "YouTube rejected it — see the console above."
        else:
            JOB["done_msg"] = ("On YouTube ✅ — it goes public on its planned "
                               "date by itself")
    except Exception:
        JOB["done_msg"] = "Upload failed — check the console above."
    finally:
        JOB["running"] = False


@app.route("/netcheck", methods=["POST"])
def netcheck():
    return _kick(job, ["netcfg.py", "--check"], "Testing the route to YouTube",
                 "Connection test done — read the console above")


@app.route("/queue_now", methods=["POST"])
def queue_now(): return _kick(queue_now_job, _req_channel())


@app.route("/plan_queue", methods=["POST"])
def plan_queue():
    return _kick(job, ["schedule_queue.py", "--plan"], "Scheduling your ready videos",
                 "Scheduled ✅ — each one now has a release date and uploads itself")


@app.route("/evening", methods=["POST"])
def evening(): return _kick(job, ["evening.py"],
                            "Running your whole evening (sync → pins → upload)",
                            "Evening done ✅ — your 2-minute checklist is in the console",
                            _req_channel())


@app.route("/coach", methods=["POST"])
def coach(): return _kick(coach_job)


# chat commands → the script the assistant runs + whether to reload after
ACTION_JOBS = {
    "evening":        (["evening.py"],
                       "Evening done ✅ — your checklist is in the console", True),
    "make_short":     (["pilot.py"], "Ready ✅", True),
    "make_story":     (["storyteller.py", "--make"], "Story ready ✅ — see the Studio tab", True),
    "make_longform":  (["make_longform.py"], "Long-form ready ✅", True),
    "apply_pins":     (["channel_control.py", "--apply-pins"],
                       "Questions posted ✅ — now pin each one (⋮ → Pin)", True),
    "sync_analytics": (["analytics.py", "--sync"], "Retention synced ✅", True),
    "sync_stats":     (["channel_stats.py"], "Real numbers in ✅", True),
    "trend_scan":     (["trend_scan.py", "--region", "US"], "Trends updated ✅", False),
}


@app.route("/coach_chat")
def coach_chat():
    import ai_brain
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify(answer="Ask me anything about growing the channel.")
    COACH_CHAT.append({"role": "user", "content": q})

    # direct commands actually RUN (the assistant works, not just talks)
    action = None
    try:
        action = ai_brain.detect_intent(q)
    except Exception:
        pass
    if action == "status":
        text = ai_brain.status_text()
        COACH_CHAT.append({"role": "assistant", "content": text})
        return jsonify(answer=text, engine="assistant")
    if action == "analyze":
        if JOB["running"]:
            text = "One thing at a time — I'm still working on the previous job. Watch the status bar."
            COACH_CHAT.append({"role": "assistant", "content": text})
            return jsonify(answer=text, engine="assistant")
        _kick(coach_job)
        text = "📊 On it — running the full analysis of your real numbers. The report lands below this chat in a few seconds."
        COACH_CHAT.append({"role": "assistant", "content": text})
        return jsonify(answer=text, engine="assistant", action=action, reload=True)
    if action in ACTION_JOBS:
        if JOB["running"]:
            text = "One thing at a time — I'm still working on the previous job. Watch the status bar."
            COACH_CHAT.append({"role": "assistant", "content": text})
            return jsonify(answer=text, engine="assistant")
        cmd, ok, reload_after = ACTION_JOBS[action]
        _kick(job, cmd, ai_brain.ACTION_LABELS[action], ok, _req_channel())
        text = f"🚀 On it — {ai_brain.ACTION_LABELS[action].lower()}. Watch the status bar; I'll refresh the page when it's done."
        COACH_CHAT.append({"role": "assistant", "content": text})
        return jsonify(answer=text, engine="assistant", action=action, reload=reload_after)

    try:
        text, engine = ai_brain.coach_reply(COACH_CHAT[-12:])   # last few turns
    except Exception as e:
        text, engine = f"(coach error: {e})", "error"
    COACH_CHAT.append({"role": "assistant", "content": text})
    return jsonify(answer=text, engine=engine)


@app.route("/coach_reset", methods=["POST"])
def coach_reset():
    COACH_CHAT.clear()
    return jsonify(ok=True)


@app.route("/save_profile", methods=["POST"])
def save_profile():
    import progress
    progress.set_channel(_req_channel())   # save to THIS channel's profile
    data = request.get_json(force=True, silent=True) or {}
    progress.save_profile(data)
    return jsonify(ok=True)


@app.route("/scan", methods=["POST"])
def scan(): return _kick(job, ["trend_scan.py", "--region", "US"], "Trend scan", "Trends updated ✅")


@app.route("/sync_stats", methods=["POST"])
def sync_stats(): return _kick(job, ["channel_stats.py"], "Sync stats", "Real view counts in ✅", _req_channel())


@app.route("/compile", methods=["POST"])
def compile_long(): return _kick(job, ["make_compilation.py"], "Compilation", "Long-form ready ✅")


@app.route("/longform", methods=["POST"])
def longform():
    ch = _req_channel()
    mins = str(load(_paths.paths(ch)["config"], {}).get("longform_minutes", 4))
    return _kick(job, ["make_longform.py", "--minutes", mins],
                 "Building a long-form video (several minutes — grab a chai)",
                 "Long-form ready ✅ — see the Today tab", ch)


@app.route("/lf/<path:name>")
def lf_file(name):
    ch = request.args.get("channel") or CHANNEL
    return send_from_directory(_paths.paths(ch)["long_form"], name)


def lf_upload_job(want=None, channel=None):
    try:
        JOB["log"] = []
        channel = channel or _paths.DEFAULT_CHANNEL
        P = _paths.paths(channel)
        lib_path, lfdir = P["library"], P["long_form"]
        lf_all = (load(lib_path, {}) or {}).get("longform", {})
        if want:
            name, meta = want, lf_all.get(want)
        elif lf_all:
            name = max(lf_all, key=lambda k: (lf_all[k].get("created", ""), k))
            meta = lf_all[name]
        else:
            name, meta = None, None
        if not meta or meta.get("status") == "uploaded":
            JOB["done_msg"] = "Nothing to upload — build a long-form video first."
            return
        path = os.path.join(lfdir, meta["file"])
        if not os.path.exists(path):
            JOB["done_msg"] = "The video file is gone — build a new one."
            return
        cmd = ["upload_youtube.py", "--file", path, "--title", meta["title"],
               "--desc", meta["description"], "--longform"]
        thumb = os.path.join(lfdir, meta.get("thumb") or "")
        if meta.get("thumb") and os.path.exists(thumb):
            cmd += ["--thumb", thumb]
        if meta.get("pin_comment"):
            cmd += ["--comment", meta["pin_comment"]]
        run(cmd, "Upload long-form to YouTube", channel=channel)
        lib = load(lib_path, {"videos": {}})
        if name in lib.get("longform", {}):
            lib["longform"][name]["status"] = "uploaded"
            save_json(lib_path, lib)
        JOB["done_msg"] = "Long-form uploaded ✅"
    except Exception:
        JOB["done_msg"] = "Upload failed — is the one-time Google setup done? (see Settings console)"
    finally:
        JOB["running"] = False


@app.route("/upload_longform", methods=["POST"])
def upload_longform():
    want = os.path.basename(request.args.get("f", "")) or None
    return _kick(lf_upload_job, want, _req_channel())


@app.route("/story", methods=["POST"])
def story():
    ch = _req_channel()
    # story format is motivation-only (storyteller = motivation archetypes). Other
    # niches build a niche long-form instead — same routing the Sunday autopilot uses.
    story_on = (load(_paths.paths(ch)["config"], {}) or {}).get("story_mode", True)
    if story_on:
        return _kick(job, ["storyteller.py", "--make"],
                     "Writing and filming this week's story (several minutes — chai time)",
                     "Story ready ✅ — it's on the Studio tab with its Shorts", ch)
    return _kick(job, ["make_longform.py"],
                 "Building this week's long-form video (several minutes — chai time)",
                 "Long-form ready ✅ — it's on the Studio tab", ch)


@app.route("/story_plan", methods=["POST"])
def story_plan():
    return _kick(job, ["storyteller.py", "--plan"],
                 "Planning your next 4 weeks of stories", "Plan ready 🗓", _req_channel())


@app.route("/doctor", methods=["POST"])
def doctor(): return _kick(job, ["doctor.py"], "Health check", "Health check done ✅")


@app.route("/reveal", methods=["POST"])
def reveal():
    """Show the video file in Finder so uploading is a drag-and-drop."""
    kind = request.args.get("kind", "short")
    name = os.path.basename(request.args.get("f", ""))    # no path tricks
    P = _paths.paths(_req_channel())
    folder = P["long_form"] if kind == "long" else P["output"]
    path = os.path.join(folder, name)
    if name and os.path.exists(path):
        subprocess.run(["open", "-R", path])
        return jsonify(ok=True)
    return jsonify(ok=False)


@app.route("/draft_reply")
def draft_reply():
    import ai_brain
    try:
        i = int(request.args.get("i", "-1"))
    except ValueError:
        i = -1
    lib = load(LIBRARY, {"videos": {}})
    comments = (lib.get("channel", {}).get("recent_comments") or [])
    if not (0 <= i < len(comments)):
        return jsonify(reply="(comment not found — sync your stats again)")
    c = comments[i]
    try:
        text, engine = ai_brain.draft_reply(c.get("text", ""), c.get("video", ""))
    except Exception as e:
        text, engine = f"(draft failed: {e})", "error"
    return jsonify(reply=text, engine=engine)


@app.route("/backup", methods=["POST"])
def backup():
    """One-click backup of the channel's brain (every json + plan + schedule).
    Videos aren't included — they live on YouTube; these files are what can't
    be rebuilt."""
    import zipfile
    from datetime import datetime
    bdir = os.path.join(HERE, "backups")
    os.makedirs(bdir, exist_ok=True)
    out = os.path.join(bdir, f"brain_{datetime.now().strftime('%Y-%m-%d_%H%M')}.zip")
    keep = ["library.json", "content.json", "state.json", "config.json",
            "profile.json", "links.json", "trends_report.json", "today.json",
            "schedule.csv", "posting_plan.md"]
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in keep:
                p = os.path.join(HERE, f)
                if os.path.exists(p):
                    z.write(p, f)
            for f in sorted(os.listdir(LONGFORM_DIR)):
                if f.endswith("_meta.json"):
                    z.write(os.path.join(LONGFORM_DIR, f), f"long_form/{f}")
        old = sorted(f for f in os.listdir(bdir) if f.startswith("brain_"))
        for f in old[:-7]:                        # keep the newest 7
            os.remove(os.path.join(bdir, f))
        kb = os.path.getsize(out) // 1024
        return jsonify(ok=True, msg=f"Backed up ✅ backups/{os.path.basename(out)} ({kb} KB)")
    except Exception as e:
        return jsonify(ok=False, msg=f"Backup failed: {e}")


@app.route("/apply_pins", methods=["POST"])
def apply_pins():
    return _kick(job, ["channel_control.py", "--apply-pins"],
                 "Posting your question on every live video",
                 "Questions posted ✅ — open each video once and tap ⋮ → Pin")


@app.route("/sync_analytics", methods=["POST"])
def sync_analytics():
    return _kick(job, ["analytics.py", "--sync"],
                 "Pulling retention analytics from YouTube", "Retention synced ✅")


@app.route("/google_connect", methods=["POST"])
def google_connect():
    return _kick(job, ["yt_auth.py", "--connect"],
                 "Opening Google in your browser — approve once",
                 "Connected ✅ — the system can now manage your channel")


@app.route("/send_reply", methods=["POST"])
def send_reply():
    try:
        i = int(request.args.get("i", "-1"))
    except ValueError:
        i = -1
    text = (request.args.get("text") or "").strip()
    lib = load(LIBRARY, {"videos": {}})
    comments = (lib.get("channel", {}).get("recent_comments") or [])
    if not (0 <= i < len(comments)) or not text:
        return jsonify(ok=False, msg="Comment not found — sync your stats again.")
    tid = comments[i].get("thread_id")
    if not tid:
        return jsonify(ok=False, msg="No thread id — run 'Sync my stats' once to refresh.")
    try:
        import channel_control
        channel_control.reply_to(tid, text)
        return jsonify(ok=True, msg="Reply posted on YouTube ✅")
    except Exception as e:
        import yt_auth
        if isinstance(e, yt_auth.NotConnected):
            return jsonify(ok=False, msg=str(e))
        return jsonify(ok=False, msg=f"Reply failed: {e}")


@app.route("/autopilot", methods=["POST"])
def autopilot_toggle():
    on = request.args.get("on") == "true"
    act = "install" if on else "uninstall"
    p = subprocess.run([PY, "scheduler.py", act], cwd=HERE, env=ENV,
                       capture_output=True, text=True)
    ok = p.returncode == 0
    msg = ((p.stdout or p.stderr or "").strip().splitlines() or ["done"])[-1]
    if ok and on:
        msg = "Morning autopilot ON — today's video will be ready by ~7:15 AM ✅"
    elif ok:
        msg = "Morning autopilot OFF"
    return jsonify(ok=ok, msg=msg)


@app.route("/ask")
def ask_route():
    import ask as askmod
    q = request.args.get("q", "").strip()
    return jsonify(answer=askmod.answer(q) if q else "Ask me something!")


@app.route("/config", methods=["POST"])
def set_config():
    cfg = load(CONFIG, {})
    k, val = request.args.get("key"), request.args.get("val")
    if k:
        cfg[k] = True if val == "true" else False if val == "false" else val
        save_json(CONFIG, cfg)
    return jsonify(ok=True)


@app.route("/done_today", methods=["POST"])
def done_today():
    P = _paths.paths(_req_channel())
    lib_path, today_path = P["library"], P["today"]
    m = load(today_path)
    m = m if m and m.get("date") == date.today().isoformat() else None
    if m:
        lib = load(lib_path, {"videos": {}})
        base = m["file"].replace("_toon", "")
        for n in (m["file"], base):
            if n in lib["videos"]:
                lib["videos"][n]["status"] = "uploaded"
        lib["last_upload_date"] = date.today().isoformat()
        save_json(lib_path, lib)
        if os.path.exists(today_path):
            os.remove(today_path)
    return jsonify(ok=True)


@app.route("/progress")
def progress(): return jsonify(running=JOB["running"], log=JOB["log"], done_msg=JOB["done_msg"])


def open_in_chrome(url):
    """Money-making happens in Chrome (the channel's Google login lives there),
    even though the system default browser is Brave."""
    try:
        subprocess.run(["open", "-a", "Google Chrome", url], check=True)
    except Exception:
        webbrowser.open(url)          # Chrome missing → whatever browser works


if __name__ == "__main__":
    port = 5050
    already_running = False
    try:                          # is OUR dashboard on the port (not some other app)?
        import urllib.request
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/progress", timeout=2)
        already_running = "running" in json.loads(req.read().decode())
    except Exception:
        pass
    if already_running:                    # double-clicked again → just open it
        print(f"\n  Dashboard already running →  http://localhost:{port}\n")
        open_in_chrome(f"http://localhost:{port}")
    else:
        threading.Timer(1.0, lambda: open_in_chrome(f"http://localhost:{port}")).start()
        print(f"\n  Mindset Refuel AI Pilot →  http://localhost:{port}\n")
        app.run(host="127.0.0.1", port=port, debug=False)
