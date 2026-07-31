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


class TestRefitUnused(unittest.TestCase):
    """The budget must reach scripts composed before it existed.

    _fit_runtime only runs at compose time, so ~20 scripts already sitting in
    content.json kept their seven lines and would have kept rendering at ~25s
    for weeks. But a script whose video is already built and published must not
    be touched — re-cutting it would make the library disagree with YouTube.
    """

    def _bank(self):
        return {"t": {"hooks": [HOOKS], "bodies": [BODIES], "closers": [CLOSERS]}}

    def _run(self, items, used_ids):
        saved = {}

        def fake_load(path, default=None):
            if path == sc.CONTENT:
                return {"items": items}
            return {"used_ids": used_ids}

        with mock.patch.object(sc, "BANK", self._bank()), \
             mock.patch.object(sc, "load", side_effect=fake_load), \
             mock.patch.object(sc, "save",
                               side_effect=lambda p, d: saved.update({p: d})), \
             mock.patch.object(sc, "_fit_runtime",
                               side_effect=lambda h, b, c: list(h) + list(b)[:2] + list(c)[:1]):
            n = sc.refit_unused()
        return n, items

    def test_an_unused_script_is_shortened(self):
        items = [{"id": "c001", "theme": "t", "lines": HOOKS + BODIES + CLOSERS}]
        n, items = self._run(items, used_ids=[])
        self.assertEqual(n, 1)
        self.assertEqual(len(items[0]["lines"]), 5)

    def test_an_already_built_script_is_never_touched(self):
        original = HOOKS + BODIES + CLOSERS
        items = [{"id": "c001", "theme": "t", "lines": list(original)}]
        n, items = self._run(items, used_ids=["c001"])
        self.assertEqual(n, 0)
        self.assertEqual(items[0]["lines"], original)

    def test_an_unrecognised_shape_is_left_alone(self):
        """Story scripts and hand-edited ones don't match the bank; skip them."""
        odd = ["something", "entirely", "different"]
        items = [{"id": "c001", "theme": "t", "lines": list(odd)}]
        n, items = self._run(items, used_ids=[])
        self.assertEqual(n, 0)
        self.assertEqual(items[0]["lines"], odd)

    def test_an_unknown_theme_is_left_alone(self):
        items = [{"id": "c001", "theme": "nope", "lines": HOOKS + BODIES + CLOSERS}]
        n, _ = self._run(items, used_ids=[])
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
