#!/usr/bin/env python3
"""
schedule_queue.py — plan a posting calendar across all channels and upload it
without ever blowing the YouTube API quota.

WHY THIS EXISTS
  A YouTube API project gets 10,000 quota units per day, and ONE video upload
  (videos.insert) costs 1,600 of them. That is six uploads a day for the whole
  system — all three channels share a single OAuth client, so they share the
  same 10,000. Trying to push a week of content in one afternoon does not fail
  gracefully: uploads 7+ die with quotaExceeded, and the old code marked them
  uploaded anyway.

  So the calendar and the transfer are separated:
    * PLAN assigns each ready video a public release date (one per channel per
      day). Nothing is uploaded.
    * RUN uploads only what is due, newest budget first, and stops before the
      quota runs out. YouTube's publishAt then flips each video public at its
      channel's prime-time slot on the right day.

  Run daily (the autopilot does this) and the calendar just happens: ~3 uploads
  a day, ~4,800 units, comfortably inside the budget, forever.

  python3 schedule_queue.py --plan --until 2026-07-30   # build the calendar
  python3 schedule_queue.py --status                    # show the calendar
  python3 schedule_queue.py --run                       # upload what's due
  python3 schedule_queue.py --run --dry-run             # show what WOULD upload
"""
import argparse
import json
import os
import sys
import traceback
from datetime import date, timedelta

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "schedule.json")

# Real YouTube Data API v3 costs. videos.insert is the expensive one; the
# read-back check in upload_youtube costs 1. Keep a margin under 10,000 so the
# dashboard's stats/analytics calls can still run on the same day.
UPLOAD_UNITS = 1600
DAILY_BUDGET = 8000                 # 5 uploads/day, ~2,000 units left over
# Upload this many days before a video is due to go public. A small lead means
# a failed transfer still has days of retries before its release time.
LEAD_DAYS = 1
# Below this a "long-form" earns no meaningful watch-time and just clutters the
# channel; the real ones in this project run 5-7 minutes.
MIN_LONGFORM_SEC = 180


def load(path, default=None):
    return json.load(open(path)) if os.path.exists(path) else default


def save(data):
    json.dump(data, open(QUEUE, "w"), indent=2)


def blank():
    return {"daily_budget": DAILY_BUDGET, "spent": {}, "items": []}


def spent_today(q):
    return q.get("spent", {}).get(date.today().isoformat(), 0)


def _entry(slug, name, v, kind):
    return {
        "channel": slug,
        "file": name,
        "kind": kind,
        "title": v.get("title", ""),
        "description": v.get("description", ""),
        "pin_comment": v.get("pin_comment", ""),
        "thumb": v.get("thumb", ""),
    }


def ready_videos(slug):
    """Un-posted, playable Shorts for a channel, oldest first.

    'ready' is the only status that means postable: 'uploaded' is already live
    and 'duplicate' was retired by reconcile.py because the same script is
    already on the channel.
    """
    P = _paths.paths(slug)
    lib = load(P["library"], {"videos": {}}) or {"videos": {}}
    out = []
    for name, v in (lib.get("videos") or {}).items():
        if v.get("status") != "ready":
            continue
        if not os.path.exists(os.path.join(P["output"], name)):
            continue
        out.append((v.get("seq", 0), name, _entry(slug, name, v, "short")))
    return [e for _, _, e in sorted(out, key=lambda x: (x[0], x[1]))]


def ready_longform(slug):
    """Un-posted long videos, best first. 16:9, custom thumbnail, tracked under
    library['longform'] rather than ['videos'].

    Two rules keep this useful. Anything under MIN_LONGFORM_SEC is skipped — a
    90-second video is the worst of both worlds: too long for the Shorts feed,
    too short to earn watch-hours. And the NEWEST is posted first, because the
    backlog here is weeks old and stale uploads are the least valuable thing a
    channel can publish.
    """
    P = _paths.paths(slug)
    lib = load(P["library"], {}) or {}
    out = []
    for name, v in (lib.get("longform") or {}).items():
        if v.get("status") != "ready":
            continue
        path = os.path.join(P["long_form"], name)
        if not os.path.exists(path):
            continue
        if float(v.get("duration_sec") or 0) < MIN_LONGFORM_SEC:
            continue
        out.append((v.get("created", ""), name, _entry(slug, name, v, "longform")))
    return [e for _, _, e in sorted(out, reverse=True)]


def item_path(item):
    P = _paths.paths(item["channel"])
    root = P["long_form"] if item.get("kind") == "longform" else P["output"]
    return os.path.join(root, item["file"])


def plan(until, replan=False):
    """Assign each ready video a public release date, one per channel per day."""
    q = load(QUEUE, blank()) or blank()
    if replan:
        q["items"] = [i for i in q["items"] if i.get("status") == "uploaded"]

    done = {(i["channel"], i["file"]) for i in q["items"]}
    today = date.today()
    added = 0

    for c in _paths.active_channels():
        slug = c["slug"]
        # One Short per channel per day. Long-form is a different format, so it
        # may share a date with a Short — it does not eat a daily slot.
        taken = {i["publish_date"] for i in q["items"]
                 if i["channel"] == slug and i.get("kind", "short") == "short"}
        day = today
        for e in ready_videos(slug):
            if (slug, e["file"]) in done:
                continue
            while day.isoformat() in taken:
                day += timedelta(days=1)
            if day > until:
                break
            q["items"].append({**e, "publish_date": day.isoformat(),
                               "status": "pending"})
            taken.add(day.isoformat())
            added += 1

        # Long videos go out one per week — put the first on the nearest
        # Saturday (or today if today is already a weekend day).
        lf_day = today
        while lf_day.weekday() not in (5, 6) and lf_day < until:
            lf_day += timedelta(days=1)
        for e in ready_longform(slug):
            if (slug, e["file"]) in done or lf_day > until:
                continue
            q["items"].append({**e, "publish_date": lf_day.isoformat(),
                               "status": "pending"})
            added += 1
            lf_day += timedelta(days=7)

    q["items"].sort(key=lambda i: (i["publish_date"], i["channel"]))
    save(q)
    print(f"Planned {added} new post(s) through {until}.")
    return q


def show(q=None):
    q = q or load(QUEUE, blank()) or blank()
    items = q.get("items", [])
    if not items:
        print("Calendar is empty — run --plan first.")
        return
    print(f"\n  POSTING CALENDAR      (budget {q.get('daily_budget', DAILY_BUDGET)} "
          f"units/day = {q.get('daily_budget', DAILY_BUDGET)//UPLOAD_UNITS} uploads/day)")
    print(f"  spent today: {spent_today(q)} units\n")
    cur = None
    for i in items:
        if i["publish_date"] != cur:
            cur = i["publish_date"]
            print(f"  {cur}")
        icon = {"uploaded": "✓", "pending": "·", "failed": "✗"}.get(i["status"], "?")
        extra = f"  → {i['video_id']}" if i.get("video_id") else ""
        if i.get("error"):
            extra = f"  ({i['error'][:60]})"
        print(f"     {icon} {i['channel']:11} {i['file']:18} "
              f"{i['title'][:40]}{extra}")
    n_pending = sum(1 for i in items if i["status"] == "pending")
    print(f"\n  {n_pending} pending, "
          f"{sum(1 for i in items if i['status'] == 'uploaded')} uploaded, "
          f"{sum(1 for i in items if i['status'] == 'failed')} failed")


def due(q, today=None, channel=None, lead=None):
    """Items that should be uploaded now: due within LEAD_DAYS, oldest first.

    `lead` overrides the lead time (the dashboard's "upload it now" button pushes
    it wide open so the next queued video can go early), and `channel` narrows it
    to one channel so a button on the Speak Fluent page never posts to Mind Blown.
    """
    today = today or date.today()
    lead = LEAD_DAYS if lead is None else lead
    cutoff = today + timedelta(days=lead)
    return [i for i in q["items"]
            if i["status"] in ("pending", "failed")
            and (channel is None or i["channel"] == channel)
            and date.fromisoformat(i["publish_date"]) <= cutoff]


def run(dry=False, limit=None, channel=None, now=False):
    q = load(QUEUE, blank()) or blank()
    if not q.get("items"):
        print("Calendar is empty — run --plan first.")
        return 0

    import upload_youtube as U
    today = date.today().isoformat()
    budget = q.get("daily_budget", DAILY_BUDGET)
    spent = q.get("spent", {}).get(today, 0)
    # `now` sends the next queued video early. It keeps its planned release
    # date, so going early costs nothing: YouTube still holds it until then and
    # the day it was meant for stays covered by exactly one video.
    todo = due(q, channel=channel, lead=3650 if now else None)
    if not todo:
        print("Nothing due today. Calendar is ahead of schedule.")
        return 0

    print(f"{len(todo)} post(s) due · {spent}/{budget} units used today "
          f"({(budget - spent) // UPLOAD_UNITS} uploads left in budget)\n")

    posted = 0
    for item in todo:
        if limit is not None and posted >= limit:
            print(f"· stopping at --limit {limit}")
            break
        if spent + UPLOAD_UNITS > budget:
            print(f"· daily quota budget reached — the rest upload tomorrow "
                  f"automatically (they are not due yet).")
            break

        slug, name = item["channel"], item["file"]
        P = _paths.paths(slug)
        path = item_path(item)
        longform = item.get("kind") == "longform"
        if not os.path.exists(path):
            item["status"] = "failed"
            item["error"] = "file missing on disk"
            print(f"✗ {slug}/{name}: file is gone")
            continue

        # Someone may have posted this by hand from the dashboard since the
        # calendar was planned. The library is the source of truth for what is
        # still un-posted — if this is no longer 'ready', the day is covered and
        # uploading it again would put the same video on the channel twice.
        if not longform:
            lib = load(P["library"], {"videos": {}}) or {"videos": {}}
            cur = (lib.get("videos") or {}).get(name, {})
            if cur and cur.get("status") != "ready":
                item["status"] = "uploaded"
                item.setdefault("video_id", cur.get("video_id", ""))
                print(f"· {slug}/{name}: already posted elsewhere "
                      f"({cur.get('status')}) — skipping")
                continue

        thumb = None
        if longform and item.get("thumb"):
            cand = os.path.join(P["long_form"], item["thumb"])
            thumb = cand if os.path.exists(cand) else None

        U.set_channel(slug)
        pub = U.publish_time(on_date=date.fromisoformat(item["publish_date"]))
        when = pub or "immediately (slot already passed)"
        print(f"→ {slug}: {name} [{item.get('kind', 'short')}]  "
              f"release {item['publish_date']} ({when})")
        if dry:
            spent += UPLOAD_UNITS
            posted += 1
            continue

        try:
            vid = U.upload(path, item["title"], item["description"],
                           thumb=thumb, comment=item.get("pin_comment"),
                           longform=longform, publish_at=pub)
            item["status"] = "uploaded"
            item["video_id"] = vid
            item.pop("error", None)
            mark_done(P, item, vid, pub, U)
            posted += 1
        except Exception as e:
            item["status"] = "failed"
            item["error"] = f"{type(e).__name__}: {e}"
            print(f"✗ {slug}/{name} FAILED: {type(e).__name__}: {str(e)[:200]}")
            if "quota" in str(e).lower():
                print("  → that's the daily API quota. Everything else waits "
                      "for tomorrow; nothing is lost.")
                save_run(q, today, spent)
                return posted
            traceback.print_exc(limit=2)
        finally:
            # Count the units even on failure: a failed insert still charges.
            spent += UPLOAD_UNITS
            save_run(q, today, spent)

    if dry:
        print(f"\nDRY RUN — {posted} would upload, {spent}/{budget} units. "
              f"Nothing was sent and the quota ledger is untouched.")
        return posted
    save_run(q, today, spent)
    print(f"\nDone — {posted} uploaded, {spent}/{budget} units used today.")
    return posted


def clear_mission(P, filename, covers_today):
    """Drop today.json once this channel's slot for today is filled.

    Two cases, both of which otherwise leave the dashboard lying:
      * the mission names the exact file we just sent — showing it with a live
        "upload" button is one click away from posting it twice;
      * the mission names a DIFFERENT file while we posted today's video from
        the calendar. The mission then advertises tomorrow's video as today's,
        which is how the channel card read "Motivation is a liar" on a day that
        video was not due.
    """
    m = load(P["today"]) or {}
    if not m:
        return
    same = m.get("file") in (filename, filename.replace("_toon", ""))
    if same or covers_today:
        try:
            os.remove(P["today"])
        except OSError:
            pass


def mark_done(P, item, vid, pub, U):
    """Write the result back to the channel's library, in the right section."""
    if item.get("kind") != "longform":
        U.mark_uploaded(P["library"], item["file"], vid, pub)
        clear_mission(P, item["file"],
                      covers_today=item["publish_date"] == date.today().isoformat())
        return
    lib = load(P["library"], {}) or {}
    entry = (lib.setdefault("longform", {})).get(item["file"])
    if entry is None:
        return
    entry["status"] = "uploaded"
    entry["video_id"] = vid
    entry["uploaded_at"] = date.today().isoformat()
    if pub:
        entry["publish_at"] = pub
    json.dump(lib, open(P["library"], "w"), indent=2)


def save_run(q, today, spent):
    q.setdefault("spent", {})[today] = spent
    # keep the ledger small: only the last 14 days matter
    for d in sorted(q["spent"])[:-14]:
        q["spent"].pop(d, None)
    save(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="build the calendar")
    ap.add_argument("--replan", action="store_true",
                    help="discard pending entries and rebuild the calendar")
    ap.add_argument("--until", help="last release date, YYYY-MM-DD")
    ap.add_argument("--status", action="store_true", help="show the calendar")
    ap.add_argument("--run", action="store_true", help="upload what is due")
    ap.add_argument("--dry-run", dest="dry", action="store_true")
    ap.add_argument("--limit", type=int, help="upload at most this many now")
    ap.add_argument("--now", action="store_true",
                    help="send the next queued video early (it keeps its "
                         "planned release date)")
    # Deliberately NOT paths.add_channel_arg(): that defaults to motivation, and
    # this is the one cross-channel tool — a default here would quietly turn the
    # nightly all-channel run into a motivation-only run.
    ap.add_argument("--channel", default=None,
                    help="only this channel (default: all of them)")
    a = ap.parse_args()

    if a.plan or a.replan:
        until = (date.fromisoformat(a.until) if a.until
                 else date.today() + timedelta(days=6))
        show(plan(until, replan=a.replan))
    elif a.run:
        run(dry=a.dry, limit=a.limit, channel=a.channel, now=a.now)
    else:
        show()


if __name__ == "__main__":
    main()
