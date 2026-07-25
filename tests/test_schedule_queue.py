#!/usr/bin/env python3
"""Tests for the posting calendar and the duplicate-content guards.

These cover the two failures that actually cost real uploads and real channel
health: pushing more videos than the shared YouTube quota allows, and shipping
two videos that open with the same line under the same headline.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_video
import schedule_queue as SQ
import script_composer as SC


class TestQuotaBudget(unittest.TestCase):
    """One project = 10,000 units/day, one upload = 1,600. Never exceed it."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self._orig, SQ.QUEUE = SQ.QUEUE, self.tmp.name

    def tearDown(self):
        SQ.QUEUE = self._orig
        os.unlink(self.tmp.name)

    def _queue(self, n):
        today = date.today().isoformat()
        SQ.save({"daily_budget": SQ.DAILY_BUDGET, "spent": {}, "items": [
            {"channel": "facts", "file": f"{i:02d}_x.mp4", "kind": "short",
             "title": f"t{i}", "description": "", "pin_comment": "",
             "publish_date": today, "status": "pending"} for i in range(n)]})

    def test_stops_at_daily_budget(self):
        """More due than the budget allows → upload only what fits."""
        self._queue(10)
        with mock.patch.object(SQ, "item_path", lambda i: __file__), \
             mock.patch("upload_youtube.set_channel"), \
             mock.patch("upload_youtube.publish_time", return_value=None), \
             mock.patch("upload_youtube.upload", return_value="VID"), \
             mock.patch.object(SQ, "mark_done"):
            posted = SQ.run()
        self.assertEqual(posted, SQ.DAILY_BUDGET // SQ.UPLOAD_UNITS)

    def test_dry_run_does_not_charge_quota(self):
        """A dry run must not spend budget the real run then can't use."""
        self._queue(3)
        with mock.patch.object(SQ, "item_path", lambda i: __file__):
            SQ.run(dry=True)
        q = SQ.load(SQ.QUEUE)
        self.assertEqual(q["spent"], {})
        self.assertTrue(all(i["status"] == "pending" for i in q["items"]))

    def test_failed_upload_still_costs_quota(self):
        """A rejected insert is charged by YouTube, so count it or we overrun."""
        self._queue(2)
        with mock.patch.object(SQ, "item_path", lambda i: __file__), \
             mock.patch("upload_youtube.set_channel"), \
             mock.patch("upload_youtube.publish_time", return_value=None), \
             mock.patch("upload_youtube.upload", side_effect=RuntimeError("boom")):
            SQ.run()
        q = SQ.load(SQ.QUEUE)
        self.assertEqual(q["spent"][date.today().isoformat()],
                         2 * SQ.UPLOAD_UNITS)
        self.assertTrue(all(i["status"] == "failed" for i in q["items"]))

    def test_not_yet_due_is_left_alone(self):
        """Videos further out than the lead time wait their turn."""
        far = (date.today() + timedelta(days=SQ.LEAD_DAYS + 3)).isoformat()
        SQ.save({"daily_budget": SQ.DAILY_BUDGET, "spent": {}, "items": [
            {"channel": "facts", "file": "x.mp4", "publish_date": far,
             "status": "pending"}]})
        self.assertEqual(SQ.due(SQ.load(SQ.QUEUE)), [])


class TestHookUniqueness(unittest.TestCase):
    """The first line is spoken first AND becomes the title — never reuse one."""

    def test_used_hook_is_excluded_from_the_pool(self):
        SC.set_channel("facts")
        combos = SC.remaining_combos(set())
        self.assertTrue(combos)
        theme, h = combos[0][0], combos[0][1]
        fewer = SC.remaining_combos(set(), {SC.hook_key(theme, h)})
        self.assertTrue(all(not (c[0] == theme and c[1] == h) for c in fewer))
        self.assertLess(len(fewer), len(combos))

    def test_hooks_backfilled_from_legacy_combo_ledger(self):
        """Hooks published before this rule existed must still count as used."""
        self.assertEqual(SC.hooks_from_combos(["biology:123", "space:021"]),
                         {"biology:h1", "space:h0"})

    def test_malformed_combo_keys_are_ignored(self):
        self.assertEqual(SC.hooks_from_combos(["nocolon", "x:ab", "y:1234"]),
                         set())

    def test_pick_items_skips_a_repeated_opening_line(self):
        """Legacy content.json can hold two scripts with the same hook."""
        content = {"items": [
            {"id": "c001", "lines": ["Same hook.", "a", "b"]},
            {"id": "c002", "lines": ["Same hook.", "c", "d"]},
            {"id": "c003", "lines": ["Different hook.", "e", "f"]},
        ]}
        picked = make_video.pick_items(content, {"used_ids": []}, 3)
        self.assertEqual([i["id"] for i in picked], ["c001", "c003"])

    def test_pick_items_skips_hooks_already_built(self):
        content = {"items": [
            {"id": "c001", "lines": ["Published hook.", "a", "b"]},
            {"id": "c002", "lines": ["Published hook.", "c", "d"]},
        ]}
        with self.assertRaises(SystemExit):
            make_video.pick_items(content, {"used_ids": ["c001"]}, 1)


class TestPerformanceFeedback(unittest.TestCase):
    """Themes that actually got views should be made more often — carefully."""

    def _lib(self, rows):
        """rows: (theme, views, days_ago) -> a library.json shaped dict."""
        return {"videos": {
            f"v{n}.mp4": {
                "status": "uploaded", "video_id": f"id{n}", "theme": t,
                "views": v,
                "uploaded_at": (date.today() - timedelta(days=d)).isoformat(),
            } for n, (t, v, d) in enumerate(rows)}}

    def _weights(self, rows, niche="motivation"):
        SC.set_channel(niche)
        with mock.patch.object(SC, "load", side_effect=lambda p, d=None: (
                self._lib(rows) if p == SC.LIBRARY else d)):
            return SC.performance_weights()

    def test_a_winning_theme_is_boosted_and_a_loser_damped(self):
        w = self._weights([("discipline", 400, 10), ("discipline", 300, 10),
                           ("doubt", 5, 10), ("doubt", 3, 10)])
        self.assertGreater(w["discipline"], 1.2)
        self.assertLess(w["doubt"], 1.0)

    def test_nothing_is_ever_killed_off(self):
        """A dead theme still gets tried — otherwise we can never re-learn it."""
        w = self._weights([("discipline", 9999, 10), ("doubt", 0, 10)])
        self.assertGreaterEqual(w["doubt"], SC.PERF_MIN_FLOOR)
        self.assertLessEqual(w["discipline"], SC.PERF_MAX_BOOST)

    def test_one_lucky_video_cannot_take_over(self):
        """Shrinkage: n=1 must move the weight far less than n=6 does."""
        one = self._weights([("discipline", 500, 10), ("doubt", 10, 10)])
        many = self._weights([("discipline", 500, 10)] * 6 + [("doubt", 10, 10)])
        self.assertLess(one["discipline"], many["discipline"])

    def test_brand_new_videos_are_not_scored(self):
        """0 views on a video posted today means nothing — ignore it."""
        self.assertEqual(self._weights([("discipline", 0, 0)]), {})

    def test_no_history_means_no_opinion(self):
        self.assertEqual(self._weights([]), {})

    def test_unsent_uploads_are_not_counted(self):
        """No video_id = it never actually reached YouTube (the old silent bug)."""
        SC.set_channel("motivation")
        lib = {"videos": {"a.mp4": {"status": "uploaded", "theme": "doubt",
                                    "views": 900, "uploaded_at": "2026-01-01"}}}
        with mock.patch.object(SC, "load", side_effect=lambda p, d=None: (
                lib if p == SC.LIBRARY else d)):
            self.assertEqual(SC.theme_rates(), {})

    def test_views_are_rated_per_day_not_totalled(self):
        """Otherwise 'best theme' just means 'oldest video'."""
        w = self._weights([("discipline", 100, 100), ("doubt", 90, 3)])
        self.assertGreater(w["doubt"], w["discipline"])


class TestLongform(unittest.TestCase):
    def test_short_longform_is_not_scheduled(self):
        """A 90-second 'long-form' earns no watch time — skip it."""
        lib = {"longform": {
            "tiny.mp4": {"status": "ready", "duration_sec": 91.9, "title": "t"},
            "real.mp4": {"status": "ready", "duration_sec": 403.9, "title": "r"},
        }}
        with mock.patch.object(SQ, "load", return_value=lib), \
             mock.patch("os.path.exists", return_value=True):
            names = [e["file"] for e in SQ.ready_longform("motivation")]
        self.assertEqual(names, ["real.mp4"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
