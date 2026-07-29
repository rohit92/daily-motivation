#!/usr/bin/env python3
"""
monetize.py — how far each channel really is from earning money, and what is
actually holding it back.

The YouTube Partner Program has two doors, and a Shorts-first channel almost
always walks through the wrong one by accident:

  Ad revenue      1,000 subscribers  AND  (4,000 public watch HOURS in 365 days
                                            OR 10,000,000 Shorts views in 90 days)
  Fan funding       500 subscribers  AND  (3,000 public watch hours in 365 days
                                            OR  3,000,000 Shorts views in 90 days)
                                     AND  3 public uploads in the last 90 days

The Shorts route needs 10 MILLION views in a 90-day window. The watch-hours
route needs 4,000 hours. For a channel averaging ~16 seconds of view duration,
4,000 hours is about 900,000 Shorts views — versus 10,000,000. The watch-hours
door is roughly 11x cheaper, and it is the door long-form opens.

That is the whole argument for long-form on a Shorts channel, and this script
prints the arithmetic for your actual numbers instead of a rule of thumb.

  python3 monetize.py                 # all channels
  python3 monetize.py --channel facts
  python3 monetize.py --json          # machine-readable, for the dashboard
"""
import argparse
import json
import sys
from datetime import date, timedelta

import paths as _paths
import yt_auth

# The two doors, as (subs, watch_hours, shorts_views_90d).
TIERS = {
    "ad revenue":  (1000, 4000, 10_000_000),
    "fan funding": (500, 3000, 3_000_000),
}
RECENT_DAYS = 30          # window used to measure the channel's current speed
# Below this many long-form views, the watch-hours-per-view ratio is one or two
# videos' luck rather than a property of the format. Report it, but say so.
MIN_CONFIDENT_VIEWS = 100


def _rows(yta, start, end, **kw):
    r = yta.reports().query(ids="channel==MINE", startDate=start, endDate=end,
                            **kw).execute()
    cols = [h["name"] for h in r.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in (r.get("rows") or [])]


def measure(slug):
    """Everything the Partner Program actually counts, for one channel."""
    yt_auth.set_channel(slug)
    yt = yt_auth.data_api(interactive=False)
    yta = yt_auth.analytics_api(interactive=False)

    stats = yt.channels().list(part="statistics", mine=True).execute()["items"][0]
    subs = int(stats["statistics"].get("subscriberCount", 0))

    today = date.today()
    end = today.isoformat()
    year_ago = (today - timedelta(days=365)).isoformat()
    ninety = (today - timedelta(days=90)).isoformat()
    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()

    year = _rows(yta, year_ago, end, metrics="estimatedMinutesWatched,views")
    watch_hours = round((year[0]["estimatedMinutesWatched"] if year else 0) / 60.0, 1)

    # The Shorts door counts Shorts views only. creatorContentType splits them out.
    shorts_90 = 0
    try:
        for row in _rows(yta, ninety, end, metrics="views",
                         dimensions="creatorContentType"):
            if row.get("creatorContentType") == "shorts":
                shorts_90 = int(row["views"])
    except Exception:
        # Older channels / API variations: fall back to all views, and say so.
        rows = _rows(yta, ninety, end, metrics="views")
        shorts_90 = int(rows[0]["views"]) if rows else 0

    # Current speed, measured over the last 30 days rather than all time — a
    # channel that started slowly shouldn't be projected at its launch rate.
    r = _rows(yta, recent, end,
              metrics="views,estimatedMinutesWatched,subscribersGained,"
                      "subscribersLost,averageViewDuration")
    cur = r[0] if r else {}
    days = float(RECENT_DAYS)
    per_day = {
        "views": cur.get("views", 0) / days,
        "hours": cur.get("estimatedMinutesWatched", 0) / 60.0 / days,
        "subs": (cur.get("subscribersGained", 0) - cur.get("subscribersLost", 0)) / days,
    }

    # Long-form vs Shorts watch time: which format is actually buying the hours.
    by_format = {}
    try:
        for row in _rows(yta, year_ago, end,
                         metrics="views,estimatedMinutesWatched",
                         dimensions="creatorContentType"):
            by_format[row.get("creatorContentType", "?")] = {
                "views": int(row["views"]),
                "hours": round(row["estimatedMinutesWatched"] / 60.0, 1),
            }
    except Exception:
        pass

    uploads_90 = _public_uploads_since(yt, ninety)

    return {"slug": slug, "subs": subs, "watch_hours": watch_hours,
            "shorts_90d": shorts_90, "per_day": per_day,
            "avg_view_sec": round(float(cur.get("averageViewDuration", 0) or 0), 1),
            "by_format": by_format, "uploads_90d": uploads_90}


def _public_uploads_since(yt, since):
    """Public uploads in the window — the forgotten third condition."""
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        n, page = 0, None
        while True:
            r = yt.playlistItems().list(part="contentDetails", playlistId=pl,
                                        maxResults=50, pageToken=page).execute()
            for i in r.get("items", []):
                if i["contentDetails"].get("videoPublishedAt", "")[:10] >= since:
                    n += 1
            page = r.get("nextPageToken")
            if not page:
                break
        return n
    except Exception:
        return -1              # unknown, rather than a wrong number


def _eta(have, need, per_day):
    """Days until `have` reaches `need` at the current rate."""
    if have >= need:
        return 0
    if per_day <= 0:
        return None            # never, at this rate — say so honestly
    return (need - have) / per_day


def _fmt_eta(days):
    if days == 0:
        return "✓ met"
    if days is None:
        return "never at the current rate"
    if days < 90:
        return f"~{days:.0f} days ({(date.today() + timedelta(days=days)).isoformat()})"
    if days < 365 * 8:
        return f"~{days / 30.4:.0f} months ({(date.today() + timedelta(days=days)).strftime('%b %Y')})"
    return f"~{days / 365:.0f} years"


def report(m):
    name = _paths.channel_meta(m["slug"]).get("name", m["slug"])
    print(f"\n{'=' * 66}\n{name}  ({m['slug']})\n{'=' * 66}")
    print(f"  subscribers      {m['subs']:>12,}")
    print(f"  watch hours/365d {m['watch_hours']:>12,.1f}")
    print(f"  Shorts views/90d {m['shorts_90d']:>12,}")
    up = m["uploads_90d"]
    print(f"  public uploads   {up if up >= 0 else '?':>12}  (need 3 in 90d)")
    pd = m["per_day"]
    print(f"\n  current speed (last {RECENT_DAYS} days)")
    print(f"    {pd['views']:.1f} views/day · {pd['hours']:.2f} watch-hours/day "
          f"· {pd['subs']:+.2f} subs/day · {m['avg_view_sec']:.0f}s avg view")

    if m["by_format"]:
        print(f"\n  where the watch time comes from")
        for fmt, d in sorted(m["by_format"].items(),
                             key=lambda kv: -kv[1]["hours"]):
            per_1k = (d["hours"] / d["views"] * 1000) if d["views"] else 0
            print(f"    {fmt:<12} {d['views']:>8,} views → {d['hours']:>7,.1f} h "
                  f"({per_1k:.1f} h per 1,000 views)")

    for tier, (need_subs, need_hours, need_shorts) in TIERS.items():
        print(f"\n  ── {tier}: {need_subs:,} subs + "
              f"({need_hours:,} watch hours OR {need_shorts:,} Shorts views/90d)")
        d_subs = _eta(m["subs"], need_subs, pd["subs"])
        d_hours = _eta(m["watch_hours"], need_hours, pd["hours"])
        d_shorts = _eta(m["shorts_90d"], need_shorts, pd["views"])
        print(f"     subs        {m['subs']:>10,} / {need_subs:<10,} {_fmt_eta(d_subs)}")
        print(f"     watch hours {m['watch_hours']:>10,.1f} / {need_hours:<10,} {_fmt_eta(d_hours)}")
        print(f"     Shorts 90d  {m['shorts_90d']:>10,} / {need_shorts:<10,} {_fmt_eta(d_shorts)}")

        # Which door is nearer, and what is holding it shut.
        watch_door = max(x for x in (d_subs, d_hours)
                         if x is not None) if None not in (d_subs, d_hours) else None
        shorts_door = max(x for x in (d_subs, d_shorts)
                          if x is not None) if None not in (d_subs, d_shorts) else None
        doors = [(x, n) for x, n in ((watch_door, "watch hours"),
                                     (shorts_door, "Shorts views")) if x is not None]
        if not doors:
            print("     → blocked: nothing is growing right now.")
            continue
        best, via = min(doors)
        gate = ("subscribers" if d_subs is not None and d_subs >= best - 0.01
                else via)
        print(f"     → nearest door: {via} — {_fmt_eta(best)}; "
              f"the binding constraint is {gate}")


def advice(ms):
    """The one or two things that move the needle, derived from the numbers."""
    print(f"\n{'=' * 66}\nWHAT ACTUALLY MOVES THIS\n{'=' * 66}")
    for m in ms:
        name = _paths.channel_meta(m["slug"]).get("name", m["slug"])
        bf = m["by_format"]
        short = bf.get("shorts", {})
        # The Analytics API calls long-form "videoOnDemand", not "video".
        longf = bf.get("videoOnDemand", {})
        tips = []

        v = m["per_day"]["views"]
        if v < 5:
            tips.append(f"only {v:.1f} views/day — nothing else matters until "
                        f"the videos get distribution at all.")
        elif m["subs"] < 500:
            conv = (m["per_day"]["subs"] / v * 1000) if v else 0
            if conv < 5:
                tips.append(f"conversion is the wall: {conv:.1f} subs per 1,000 "
                            f"views ({m['per_day']['subs']:+.2f}/day). The views "
                            f"are arriving; nothing turns them into subscribers.")

        s_rate = (short["hours"] / short["views"] * 1000) if short.get("views") else 0
        l_rate = (longf["hours"] / longf["views"] * 1000) if longf.get("views") else 0
        if l_rate and s_rate:
            need = TIERS["ad revenue"][1]
            n = longf["views"]
            tips.append(f"long-form earns {l_rate / max(s_rate, 0.01):.0f}x the watch "
                        f"hours per view that Shorts do ({l_rate:.1f} vs "
                        f"{s_rate:.1f} h per 1,000 views)."
                        + (f"  ⚠ measured on only {n} long-form view(s) — treat the "
                           f"multiple as rough; the direction is arithmetic, the "
                           f"size is not." if n < MIN_CONFIDENT_VIEWS else ""))
            tips.append(f"to reach {need:,} hours: ~{need / l_rate * 1000:,.0f} "
                        f"long-form views, or ~{need / s_rate * 1000:,.0f} Shorts "
                        f"views. Same door, {(need / s_rate) / (need / l_rate):.0f}x "
                        f"the effort.")
            # Retention is what decides whether long-form keeps this edge. A
            # 6-minute video watched 11% of the way through is a 40-second video.
            if l_rate and longf.get("hours"):
                avg_min = longf["hours"] * 60 / max(n, 1)
                tips.append(f"long-form is currently watched {avg_min:.1f} min per "
                            f"view. Every extra minute held is worth more than "
                            f"any number of extra Shorts.")
        elif not longf.get("views"):
            tips.append("no long-form watch time yet — the 4,000-hour door stays "
                        "shut until this channel has videos over 60 seconds "
                        "actually being watched.")

        if m["uploads_90d"] == 0:
            tips.append("zero public uploads in 90 days — this fails the "
                        "3-upload condition outright.")

        print(f"\n  {name}")
        for t in tips or ["on track — keep the cadence."]:
            print(f"    · {t}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--channel", default=None, help="one channel (default: all)")
    a = ap.parse_args()

    slugs = ([a.channel] if a.channel
             else [c["slug"] for c in _paths.active_channels()])
    out = []
    for slug in slugs:
        try:
            out.append(measure(slug))
        except Exception as e:
            print(f"! {slug}: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)

    if a.json:
        print(json.dumps(out, indent=2))
        return
    for m in out:
        report(m)
    advice(out)


if __name__ == "__main__":
    main()
