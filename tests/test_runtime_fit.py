#!/usr/bin/env python3
"""Tests for Short runtime trimming.

Scripts were hooks(2) + bodies(3) + closers(2) = 7 lines, rendering at ~25s.
The channels' own trend scan puts the median winning Short at 18s. A Short that
outlasts its audience gets swiped out of, which reads worse to the algorithm
than a shorter one watched to the end.

What gets cut matters as much as how much, and that is what these hold:
the hook is the first two seconds and is never touched, and one closer line
survives because conversion (4.1 subs per 1,000 views) is already the weak
spot — buying runtime by deleting the call to action trades the wrong thing.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import script_composer as sc

HOOKS = ["A shrimp's punch", "can boil the water around it."]
BODIES = ["The mantis shrimp strikes so fast",
          "it creates a tiny collapsing bubble,",
          "flashing heat and light for an instant."]
CLOSERS = ["Comment the weirdest animal you know.", "Let's compare."]


def fit(budget):
    with mock.patch.object(sc, "load", return_value={"short_max_lines": budget}):
        return sc._fit_runtime(HOOKS, BODIES, CLOSERS)


class TestRuntimeFit(unittest.TestCase):
    def test_default_budget_yields_five_lines(self):
        self.assertEqual(len(fit(5)), 5)

    def test_the_hook_is_never_cut(self):
        """The first two seconds decide whether anyone stays."""
        for budget in (4, 5, 6):
            self.assertEqual(fit(budget)[:2], HOOKS, f"budget={budget}")

    def test_one_closer_always_survives(self):
        """The engagement ask is the thing that converts a view to a sub."""
        for budget in (4, 5, 6):
            self.assertEqual(fit(budget)[-1], CLOSERS[0], f"budget={budget}")

    def test_the_body_is_what_gives_up_lines(self):
        out = fit(5)
        kept_body = [l for l in out if l in BODIES]
        self.assertEqual(len(kept_body), 2)
        self.assertEqual(kept_body, BODIES[:2], "body should trim from the end")

    def test_zero_disables_trimming(self):
        self.assertEqual(fit(0), HOOKS + BODIES + CLOSERS)

    def test_a_budget_above_the_script_length_changes_nothing(self):
        self.assertEqual(fit(99), HOOKS + BODIES + CLOSERS)

    def test_no_line_is_duplicated_or_invented(self):
        out = fit(5)
        self.assertEqual(len(out), len(set(out)))
        for line in out:
            self.assertIn(line, HOOKS + BODIES + CLOSERS)

    def test_order_is_preserved(self):
        """Hook, then body, then closer — a shuffled script reads as nonsense."""
        out = fit(5)
        original = HOOKS + BODIES + CLOSERS
        self.assertEqual(out, sorted(out, key=original.index))

    def test_a_tiny_budget_still_returns_something_speakable(self):
        out = fit(2)
        self.assertGreaterEqual(len(out), 2)
        self.assertEqual(out[0], HOOKS[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
