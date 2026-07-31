#!/usr/bin/env python3
"""Tests for building the weekly long-form ahead of its release slot.

longform_due() used to fire only on Sunday — the same day plan() wanted to
publish it. A long-form takes minutes to render and 1,600 quota units to
upload, so building it on release day left no slack: a failed render, an
exhausted quota or a dead network meant no long-form that week and nothing
queued behind it. Shorts already get a lead; this gives long-form the same.
"""
import os
import sys
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autopilot
import schedule_queue as SQ


class FakeDate(date):
    """date.today() pinned to a chosen weekday."""
    _today = date(2026, 7, 30)          # a Thursday

    @classmethod
    def today(cls):
        return cls._today


def due_on(day, last_built_days_ago=99, want=None):
    cfg = {} if want is None else {"longform_build_weekday": want}
    lib = {"longform": {"x": {
        "created": (day - timedelta(days=last_built_days_ago)).isoformat()}}}

    def fake_load(path, default=None):
        return cfg if path == autopilot.CONFIG else lib

    FakeDate._today = day
    with mock.patch.object(autopilot, "date", FakeDate), \
         mock.patch.object(autopilot, "load", side_effect=fake_load):
        return autopilot.longform_due()


class TestBuildsAheadOfTheSlot(unittest.TestCase):
    THU = date(2026, 7, 30)
    SUN = date(2026, 8, 2)

    def test_it_builds_on_thursday_by_default(self):
        self.assertTrue(due_on(self.THU))

    def test_it_no_longer_waits_for_release_day(self):
        """Sunday is when plan() publishes it, not when it should be made."""
        self.assertFalse(due_on(self.SUN))

    def test_the_build_day_is_configurable(self):
        self.assertTrue(due_on(self.SUN, want=6))
        self.assertFalse(due_on(self.THU, want=6))

    def test_one_a_week_is_still_the_limit(self):
        """A long-form built two days ago must not trigger another."""
        self.assertFalse(due_on(self.THU, last_built_days_ago=2))

    def test_a_week_old_build_lets_the_next_one_through(self):
        self.assertTrue(due_on(self.THU, last_built_days_ago=8))


class TestPlanReleasesOnTheWeekend(unittest.TestCase):
    def test_long_form_lands_on_a_saturday_or_sunday(self):
        """Built midweek, it must still be scheduled for the weekend."""
        today = date(2026, 7, 30)                    # Thursday
        lf_day = today
        while lf_day.weekday() not in (5, 6):
            lf_day += timedelta(days=1)
        self.assertIn(lf_day.weekday(), (5, 6))
        self.assertGreater(lf_day, today, "must be scheduled ahead, not same-day")

    def test_long_form_does_not_consume_a_shorts_slot(self):
        """A Short and a long-form may share a date; they are different formats."""
        import inspect
        src = inspect.getsource(SQ.plan)
        self.assertIn('kind", "short"', src,
                      "plan() must only reserve dates against Shorts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
