#!/usr/bin/env python3
"""Tests for the dated metrics series.

The series exists because two readings taken whenever someone happened to look
are not a trend, and treating them as one produced real errors — "73.4 -> 77.3
views/day" was reported as growth when it was noise on a tiny base.

So the properties that matter are: a day is recorded once no matter how many
times the snapshot runs, a failed API read writes nothing rather than a row of
nulls, and the report refuses to imply a trend it cannot support.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import growth

ROWS = [{"slug": "education", "subs": 1, "shorts_90d": 3777, "watch_hours": 3.8,
         "per_day": {"views": 126.3}, "avg_view_sec": 12.0, "uploads_90d": 18}]


class GrowthCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patch = mock.patch.object(
            growth, "SERIES", os.path.join(self.tmp, "growth.json"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def snap(self, rows=ROWS, when=None):
        with mock.patch.object(growth, "measure", return_value=rows):
            return growth.snapshot(when=when)


class TestSnapshot(GrowthCase):
    def test_it_records_the_metrics_that_matter(self):
        got = self.snap()
        self.assertEqual(got["education"]["subs"], 1)
        self.assertEqual(got["education"]["shorts_90d"], 3777)
        self.assertEqual(got["education"]["views_per_day"], 126.3)

    def test_running_twice_in_a_day_does_not_double_count(self):
        """The nightly run and a manual run must not create two rows."""
        self.snap()
        self.snap()
        data = growth.load()
        self.assertEqual(len(data["days"]), 1)

    def test_a_second_run_refreshes_that_day(self):
        self.snap()
        newer = [dict(ROWS[0], shorts_90d=3900)]
        self.snap(rows=newer)
        today = growth.load()["days"][date.today().isoformat()]
        self.assertEqual(today["education"]["shorts_90d"], 3900)

    def test_separate_days_accumulate(self):
        self.snap(when=date(2026, 8, 10))
        self.snap(when=date(2026, 8, 11))
        self.assertEqual(len(growth.load()["days"]), 2)

    def test_a_failed_read_writes_nothing(self):
        """Better no row than a row of nulls that looks like a real zero."""
        with mock.patch.object(growth, "measure", return_value=None):
            self.assertIsNone(growth.snapshot())
        self.assertEqual(growth.load()["days"], {})

    def test_a_missing_series_file_is_not_an_error(self):
        self.assertEqual(growth.load(), {"days": {}})


class TestReport(GrowthCase):
    def lines(self, days=7):
        out = []
        growth.report(days, out=out.append)
        return "\n".join(out)

    def test_it_says_so_when_there_is_nothing_recorded(self):
        self.assertIn("No snapshots recorded yet", self.lines())

    def test_one_day_is_not_presented_as_a_trend(self):
        self.snap()
        text = self.lines()
        self.assertIn("too few to read a trend", text)

    def test_it_shows_the_cumulative_delta_between_days(self):
        self.snap(when=date(2026, 8, 9))
        self.snap(rows=[dict(ROWS[0], shorts_90d=3900)], when=date(2026, 8, 10))
        self.assertIn("+123", self.lines())

    def test_it_warns_that_views_per_day_is_a_rolling_average(self):
        """The column most likely to be over-read needs the caveat attached."""
        for d in (9, 10, 11):
            self.snap(when=date(2026, 8, d))
        self.assertIn("rolling average", self.lines())


if __name__ == "__main__":
    unittest.main(verbosity=2)
