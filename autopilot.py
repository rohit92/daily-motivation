#!/usr/bin/env python3
"""
autopilot.py — the hands-free daily run. This is what the morning schedule
(scheduler.py / launchd) executes, and you can run it yourself any time:

  python3 autopilot.py

What it does, in order (each step is best-effort — one failure never stops
the rest):
  1. Starts your local AI (ollama serve) if it isn't already running.
  2. Syncs your real channel stats from YouTube.
  3. Prepares TODAY's video + mission — unless one is already ready today.
  4. On Sundays, also builds the weekly long-form video (watch-hours engine).
  5. Sends a Mac notification when your video is ready.

EVENING MODE: the schedule also fires at 7:30 PM. If today's mission is still
sitting unposted, you get a "time to post" nudge instead of a rebuild — the
streak is the whole game, and this is its safety net.

Everything is logged to .work/autopilot.log so you can see what happened
while you were away. You wake up → the dashboard already has today's mission.
"""

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNEL = _paths.DEFAULT_CHANNEL
_P = _paths.paths(None)
TODAY = _P["today"]
LIBRARY = _P["library"]
CONFIG = _P["config"]
OUTPUT = _P["output"]
LOG = os.path.join(HERE, ".work", "autopilot.log")   # one shared run log
PY = sys.executable

# Child scripts that accept --channel. A script missing from this set is run
# against the DEFAULT channel no matter which slug the caller is looping on,
# silently — script_composer.py was absent, so the nightly top-up filled
# motivation's queue three times and never touched the other two.
_CHANNEL_AWARE = {"channel_stats.py", "pilot.py", "upload_youtube.py",
                  "storyteller.py", "make_longform.py", "script_composer.py"}


def set_channel(channel):
    global CHANNEL, TODAY, LIBRARY, CONFIG, OUTPUT
    CHANNEL = channel or _paths.DEFAULT_CHANNEL
    P = _paths.paths(CHANNEL)
    TODAY, LIBRARY, CONFIG, OUTPUT = P["today"], P["library"], P["config"], P["output"]
# Same PATH rule as everywhere else: APPEND Homebrew (ffmpeg/ollama), never
# prepend — its python3 must not shadow the one that has our libraries.
ENV = {**os.environ, "PATH": os.environ.get("PATH", "") + os.pathsep + "/opt/homebrew/bin"}


def _proxy_env():
    """Proxy variables for children, or {} for a direct connection."""
    try:
        import netcfg
        return netcfg.proxy_env()
    except Exception:
        return {}


def use_network():
    """Route THIS process (and log which way it went).

    launchd hands the autopilot a bare environment with no proxy set, so on the
    college network every unattended upload was trying to reach googleapis.com
    directly and failing, while the same upload clicked from the dashboard
    worked — the dashboard passes the proxy to the children it spawns.
    """
    try:
        import netcfg
        netcfg.apply()
        log(f"network: {netcfg.detected()}")
        return netcfg.proxy_url()
    except Exception as e:
        log(f"network: proxy check failed ({type(e).__name__}: {e}) — going direct")
        return ""


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def trim_log(max_lines=800):
    if os.path.exists(LOG):
        lines = open(LOG).readlines()
        if len(lines) > max_lines:
            open(LOG, "w").writelines(lines[-max_lines:])


def notify(msg, title="Mindset Refuel"):
    """Mac notification (best-effort — fine if notifications are off)."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title}"'],
            capture_output=True, timeout=10)
    except Exception:
        pass


# How long a child may run before it is treated as wedged. Every one of these
# talks to the network — Google, edge-tts, ollama, Wikimedia — and none of that
# is guaranteed to answer. See run() for why a missing timeout is not a small
# problem.
_TIMEOUTS = {
    "make_longform.py": 3600,     # a 6-minute video, rendered frame by frame
    "storyteller.py": 3600,
    "pilot.py": 1800,             # composes, renders and writes metadata
    "make_video.py": 1800,
}
_DEFAULT_TIMEOUT = 900


def run(label, script, *args):
    log(f"▸ {label}")
    extra = ["--channel", CHANNEL] if script in _CHANNEL_AWARE else []
    limit = _TIMEOUTS.get(script, _DEFAULT_TIMEOUT)
    try:
        # Resolved per run, not at import: launchd fires this at 7:00 and 19:30,
        # and the machine may be on campus for one and at home for the other.
        #
        # The timeout is not defensive padding, it is the difference between one
        # bad night and a dead channel. launchd will not start a second instance
        # while the first is alive, so a child that blocks forever does not just
        # lose its own step — it silently cancels every scheduled run after it.
        # pilot.py once sat in a socket read for 38 hours and took three
        # consecutive runs down with it; nothing published and nothing warned,
        # because the process was still technically "running".
        p = subprocess.run([PY, os.path.join(HERE, script), *args, *extra],
                           cwd=HERE, env={**ENV, **_proxy_env()},
                           capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as e:
        # subprocess.run has already killed the child by the time this is raised.
        for t in (e.stdout or e.stderr or b"").decode(errors="replace").strip().splitlines()[-3:]:
            log(f"    {t}")
        log(f"✗ {label} — TIMED OUT after {limit}s and was killed")
        notify(f"{label} timed out — check the log", "Autopilot")
        return False
    tail = (p.stdout or p.stderr or "").strip().splitlines()[-4:]
    for t in tail:
        log(f"    {t}")
    log(("✓ " if p.returncode == 0 else "✗ ") + label)
    return p.returncode == 0


def ensure_ollama():
    """Start the free local AI if it's installed but not running."""
    sys.path.insert(0, HERE)
    try:
        import ai_brain
        if ai_brain._ollama_up():
            return True
        subprocess.Popen(["ollama", "serve"], env=ENV,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(10):
            time.sleep(1)
            if ai_brain._ollama_up():
                log("✓ started local AI (ollama serve)")
                return True
    except Exception:
        pass
    log("· local AI not available — scripts come from the offline bank")
    return False


def hands_free():
    """True when the system is allowed to post by itself: the user switched
    Auto-upload ON *and* the one-time Google connect is done for THIS channel."""
    if not (load(CONFIG, {}) or {}).get("auto_upload"):
        return False
    try:
        sys.path.insert(0, HERE)
        import yt_auth
        yt_auth.set_channel(CHANNEL)
        return yt_auth.setup_state() == "connected"
    except Exception:
        return False


def longform_due():
    """Weekly long-form, built a few days BEFORE its weekend slot.

    This used to fire only on Sunday — the same day plan() wanted to release it.
    A long-form takes minutes to render and 1,600 quota units to upload, so
    building it on release day left no room for anything to go wrong: a failed
    render, an exhausted quota or a dead network meant no long-form that week,
    with nothing queued to fall back on.

    Building on Thursday by default puts a finished file in the calendar two
    days before plan() schedules it for Saturday/Sunday, which is the same lead
    the Shorts already get. Override with "longform_build_weekday" in
    config.json (0=Monday … 6=Sunday).
    """
    want = (load(CONFIG, {}) or {}).get("longform_build_weekday", 3)   # Thursday
    if date.today().weekday() != want:
        return False
    lf = (load(LIBRARY, {}) or {}).get("longform", {})
    for meta in lf.values():
        try:
            d = date.fromisoformat(meta.get("created", "1970-01-01"))
            if (date.today() - d).days < 6:
                return False
        except ValueError:
            continue
    return True


def today_video_ready():
    """A mission written for TODAY whose video file still exists on disk."""
    m = load(TODAY)
    if (m and m.get("date") == date.today().isoformat() and m.get("file")
            and os.path.exists(os.path.join(OUTPUT, m["file"]))):
        return m
    return None


def run_channel(evening):
    """The full autopilot pass for the currently-selected channel."""
    meta = _paths.channel_meta(CHANNEL)
    cname = meta.get("name", CHANNEL)
    if evening:
        import evening as ev
        cfg = load(CONFIG, {}) or {}
        lib = load(LIBRARY, {"videos": {}}) or {"videos": {}}

        # one-video-per-day guards come first — never double-post
        if ev.queue_active(cfg):
            log(f"[{CHANNEL}] evening: hand-scheduled queue covers today "
                "— not uploading a second video")
            return
        if ev.posted_today(lib):
            log(f"[{CHANNEL}] evening: a video already went out today — skipping upload")
            return

        # BACKSTOP: if the 7 AM run was missed (Mac asleep), there is no mission
        # today. Build one now so a missed morning never becomes a missed post —
        # the daily streak is the #1 Shorts ranking signal, don't lose it to sleep.
        m = today_video_ready()
        if not m:
            log("evening: no video ready for today — building one now (backstop)")
            ensure_ollama()
            run("prepare today's video (pilot)", "pilot.py")
            m = today_video_ready()
        if not m:
            log("evening: could not prepare a video → nudging the human")
            notify("Couldn't auto-build today's video 🎬 Open the dashboard "
                   "and post one — don't break the streak!")
            trim_log()
            return

        if hands_free():
            log(f"[{CHANNEL}] evening: hands-free mode → uploading today's video")
            ok = run("auto-upload today's video (+ first comment)",
                     "upload_youtube.py")
            notify(f"Posted {cname}'s video to YouTube ✅ Streak safe."
                   if ok else
                   f"{cname} auto-upload FAILED — open the dashboard and post manually!",
                   title=cname)
        else:
            log(f"[{CHANNEL}] evening nudge: video ready but auto-upload is off")
            notify(f"{cname}'s video is ready 🎬 Post it now — "
                   "don't break the streak!", title=cname)
        return

    # ---- morning pass for this channel ----
    log(f"[{CHANNEL}] preparing today's video")
    run("sync channel stats", "channel_stats.py")

    m = load(TODAY)
    if m and m.get("date") == date.today().isoformat():
        log(f"[{CHANNEL}] · today's mission already prepared — skipping")
    else:
        if run("prepare today's video (pilot)", "pilot.py"):
            notify(f"{cname}: today's video is ready ✅ It posts itself at 7:30 PM."
                   if hands_free() else
                   f"{cname}: today's video is ready ✅ Open the dashboard when you are.",
                   title=cname)

    if longform_due():
        up = ["--upload"] if hands_free() else []
        if (load(CONFIG, {}) or {}).get("story_mode", True):
            ok = run("weekly STORY video + shorts", "storyteller.py", "--make", *up)
            notify(f"{cname}: this week's story is live 📖"
                   if (ok and up) else
                   f"{cname}: this week's story is built 📖 Upload it from the Studio tab.",
                   title=cname)
        elif run("weekly long-form video", "make_longform.py", *up):
            notify(f"{cname}: this week's long-form is live 🎥"
                   if up else
                   f"{cname}: this week's long-form is built 🎥 Upload it from the dashboard.",
                   title=cname)


def run_calendar():
    """Drive the shared posting calendar (schedule_queue.py).

    This is the ONE place uploads happen. It tops the calendar up with any newly
    built videos, then uploads whatever is due — a day ahead of its release, so a
    failed transfer still has retries left before the video is supposed to go
    public. YouTube's publishAt makes it appear at the channel's prime time.

    It also respects the API quota: all three channels share one 10,000-unit/day
    project and each upload costs 1,600, so the queue stops at five and picks the
    rest up tomorrow instead of failing them.

    The per-channel evening pass below still runs, but its posted_today() guard
    sees what the calendar just did and won't post a second video.
    """
    from datetime import timedelta
    try:
        import schedule_queue as sq
        sq.plan(date.today() + timedelta(days=6))
        posted = sq.run()
        log(f"✓ calendar: {posted} video(s) uploaded")
        backfill_seo()
        return posted
    except Exception as e:
        log(f"✗ calendar failed: {type(e).__name__}: {e}")
        return 0


def backfill_seo():
    """Spend leftover quota tagging the back catalogue, never the upload budget.

    Every video published before seo.py existed went up with no tags and the
    wrong category, and those videos keep earning views for years. There is
    usually a few hundred spare units after the day's uploads — enough for a
    handful of videos — so this chips away on its own instead of waiting for
    someone to remember a one-off script.
    """
    try:
        import seo_backfill as sb
        if sb.quota_left() < sb.VIDEO_UPDATE_UNITS:
            return
        import io
        import contextlib
        buf = io.StringIO()
        argv = sys.argv                    # sb.main() parses argv; put it back
        try:
            with contextlib.redirect_stdout(buf):
                sys.argv = ["seo_backfill.py", "--apply", "--videos-only"]
                sb.main()
        finally:
            sys.argv = argv
        done = sum(1 for line in buf.getvalue().splitlines() if " ✎ " in line)
        if done:
            log(f"✓ SEO backfill: tagged {done} older video(s)")
    except Exception as e:
        log(f"· SEO backfill skipped ({type(e).__name__}: {str(e)[:80]})")


def verify(channels):
    """The end-of-day pass: top the queues up, then check the books.

    These are the chores that were being done by hand. They need no judgment
    when nothing is wrong, and when something IS wrong the useful thing is to
    surface it the same evening rather than discover it days later — a channel
    went dark for two days in August and nothing in the nightly run said so,
    because nothing in the nightly run was looking.

    Report-only by design. reconcile --fix rewrites the library from what
    YouTube currently believes, which is not a thing to do unattended at 19:30.
    """
    problems = []

    for slug in channels:
        set_channel(slug)
        # Keep roughly a week of scripts ahead of the renderer. Cheap, offline,
        # and a no-op when the queue is already deep enough.
        run(f"[{slug}] top up scripts", "script_composer.py", "--ensure", "7")

    for slug in channels:
        set_channel(slug)
        p = subprocess.run([PY, os.path.join(HERE, "reconcile.py"),
                            "--channel", slug],
                           cwd=HERE, env={**ENV, **_proxy_env()},
                           capture_output=True, text=True)
        bad = [ln.strip() for ln in (p.stdout or "").splitlines()
               if ln.lstrip().startswith(("⚠", "✗"))]
        if bad:
            problems.extend(f"[{slug}] {b}" for b in bad)
        log(f"{'✓' if not bad else '⚠'} [{slug}] reconcile: "
            f"{len(bad) or 'no'} discrepanc" + ("y" if len(bad) == 1 else "ies"))

    # A channel with nothing queued AND nothing rendered posts nothing tomorrow.
    # That is the failure that hid for two days, so it is checked explicitly.
    for slug in channels:
        P = _paths.paths(slug)
        used = set((load(P["state"], {}) or {}).get("used_ids", []))
        left = len([i for i in (load(P["content"], {}) or {}).get("items", [])
                    if i["id"] not in used])
        if left == 0:
            problems.append(f"[{slug}] no scripts left to render")

    # One dated row per channel per day. Every growth claim made about these
    # channels so far came from comparing two readings taken whenever someone
    # happened to look, which is how "73.4 -> 77.3 views/day" got reported as
    # growth when it was noise. Recording it nightly is the only way the
    # question gets an answer that does not depend on the timing of the look.
    try:
        import growth
        if growth.snapshot() is None:
            log("· growth: metrics unavailable, no row recorded")
        else:
            log(f"✓ growth: recorded {len(channels)} channel(s)")
    except Exception as e:
        log(f"· growth: snapshot failed ({type(e).__name__}: {e})")

    if problems:
        for p_ in problems:
            log(f"   ! {p_}")
        notify(f"{len(problems)} issue(s) need a look", "Autopilot")
    return problems


def main():
    """Loop the autopilot over every ACTIVE channel (morning prepares each;
    evening uploads each, guarded one-per-day-per-channel). A single --channel
    can still be forced for testing."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=None,
                    help="run just this channel (default: all active channels)")
    a = ap.parse_args()

    evening = datetime.now().hour >= 17
    use_network()          # before anything talks to Google
    ensure_ollama()

    channels = ([a.channel] if a.channel
                else [c["slug"] for c in _paths.active_channels()])
    log(f"=== autopilot run ({'evening' if evening else 'morning'}) — "
        f"channels: {', '.join(channels)} ===")

    # The calendar runs FIRST and covers every channel in one pass, so the
    # per-channel work below only has to fill gaps it could not cover.
    if not a.channel:
        run_calendar()

    for slug in channels:
        set_channel(slug)
        try:
            run_channel(evening)
        except Exception as e:
            log(f"[{slug}] ✗ autopilot error: {e}")

    # Evening only: the morning run has the whole day to fix itself, so a
    # discrepancy found at 7:00 is usually just work not done yet.
    if evening and not a.channel:
        try:
            verify(channels)
        except Exception as e:
            log(f"✗ verify pass: {e}")

    trim_log()
    log("=== autopilot done ===\n")


if __name__ == "__main__":
    main()
