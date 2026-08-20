#!/usr/bin/env python3
"""A dated series of channel metrics, so trends can be read instead of guessed.

Why this exists
---------------
Every growth claim made about these channels so far came from comparing two
readings taken at arbitrary moments, days apart, with nothing recorded in
between. That produced real mistakes: "73.4 -> 77.3 views/day" was reported as
growth when it was noise on a tiny base, and a 37x long-form multiple was
quoted off eleven views.

Two numbers are not a trend. This records one row per channel per day so the
question "are views actually climbing?" has an answer that does not depend on
when someone happened to look.

  python3 growth.py --snapshot        # record today (idempotent per day)
  python3 growth.py --report 7        # last 7 days, with deltas

The nightly autopilot calls --snapshot. Re-running on the same day overwrites
that day's row rather than appending, so a manual run cannot double-count.

Reading the output
------------------
`views/day` is YouTube's own 30-day rolling average, so it MOVES SLOWLY and a
single day's change is mostly noise. `shorts_90d` and `subs` are cumulative
counters and are the honest ones to watch: they can only go up, so a flat line
is unambiguous. The report prints day-over-day change on the cumulative
figures for that reason.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES = os.path.join(HERE, ".work", "growth.json")

# monetize.py owns the API calls and the metric definitions. Shelling out to it
# keeps one definition of "watch hours" rather than a second, drifting copy.
MONETIZE_TIMEOUT = 300


def load():
    try:
        with open(SERIES, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"days": {}}


def save(data):
    os.makedirs(os.path.dirname(SERIES), exist_ok=True)
    with open(SERIES, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def measure(channel=None):
    """Today's numbers straight from monetize.py, or None if it could not run."""
    cmd = [sys.executable, os.path.join(HERE, "monetize.py"), "--json"]
    if channel:
        cmd += ["--channel", channel]
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           timeout=MONETIZE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    try:
        # monetize prints warnings to stderr but JSON to stdout; still, be strict
        # about finding the array rather than trusting the whole stream.
        out = p.stdout[p.stdout.index("["):]
        return json.loads(out)
    except Exception:
        return None


def snapshot(channel=None, when=None):
    """Record today's row. Overwrites the same day rather than appending."""
    rows = measure(channel)
    if not rows:
        return None
    day = (when or date.today()).isoformat()
    data = load()
    today = data["days"].setdefault(day, {})
    for r in rows:
        today[r["slug"]] = {
            "subs": r.get("subs"),
            "shorts_90d": r.get("shorts_90d"),
            "watch_hours": r.get("watch_hours"),
            "views_per_day": (r.get("per_day") or {}).get("views"),
            "avg_view_sec": r.get("avg_view_sec"),
            "uploads_90d": r.get("uploads_90d"),
        }
    data["days"][day] = today
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    save(data)
    return today


def report(days=7, out=print):
    data = load()
    all_days = sorted(data.get("days", {}))
    if not all_days:
        out("No snapshots recorded yet. Run: python3 growth.py --snapshot")
        return
    window = all_days[-days:]
    slugs = sorted({s for d in window for s in data["days"][d]})

    for slug in slugs:
        out("")
        out(f"  {slug}")
        out(f"    {'date':12}{'subs':>6}{'shorts/90d':>12}{'Δ':>8}"
            f"{'views/day':>11}{'hours':>8}")
        prev = None
        for d in window:
            row = data["days"][d].get(slug)
            if not row:
                continue
            sh = row.get("shorts_90d")
            delta = "" if prev is None or sh is None else f"{sh - prev:+d}"
            # Round on the way out. monetize reports views/day as a raw
            # float, so a value like 144.93333333333334 blew past its column
            # and ran into the neighbouring one, which made the table unreadable
            # on exactly the days someone would be scanning it for a trend.
            def num(x, dp=1):
                return "-" if x is None else f"{float(x):.{dp}f}"
            out(f"    {d:12}{str(row.get('subs')):>6}{str(sh):>12}{delta:>8}"
                f"{num(row.get('views_per_day')):>11}"
                f"{num(row.get('watch_hours')):>8}")
            if sh is not None:
                prev = sh

    span = len(window)
    out("")
    if span < 3:
        out(f"  {span} day(s) recorded — too few to read a trend. The 'views/day'")
        out("  column is a 30-day rolling average and barely moves day to day;")
        out("  watch the shorts/90d delta instead, and give it a week.")
    else:
        out(f"  {span} days recorded. shorts/90d and subs are cumulative counters,")
        out("  so their deltas are real. views/day is a 30-day rolling average —")
        out("  slow to move, and not evidence on its own.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", action="store_true", help="record today")
    ap.add_argument("--report", nargs="?", type=int, const=7, metavar="DAYS")
    ap.add_argument("--channel", default=None)
    a = ap.parse_args()

    if a.snapshot:
        got = snapshot(a.channel)
        if got is None:
            print("· could not read metrics (monetize.py failed or timed out)")
            return 1
        print(f"✓ recorded {len(got)} channel(s) for {date.today().isoformat()}")
    elif a.report is not None:
        report(a.report)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
