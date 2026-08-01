#!/usr/bin/env python3
"""Tests for how compose() picks scripts, and how it names them.

Two real bugs, both found while making Speak Fluent's flagship series actually
dominate its own upload schedule:

1. THE WEIGHT WAS SELF-DEFEATING. compose() made a single forward pass over a
   weight-sorted pool. The top theme therefore sat in one contiguous block at
   the head of the list, the "no 3 in a row" rule skipped the whole rest of
   that block after two picks, and the cursor never came back. The top theme
   was capped at 2 per batch no matter what — and weighting it HIGHER tightened
   the block, making it worse. Raising the bias from 6 to 14 changed nothing,
   which is what gave it away.

2. IDS COULD BE HANDED OUT TWICE. The sequence counter skipped taken ids once,
   before the loop, then incremented blindly. It also only knew about ids
   currently in content.json, not ids that published videos already own. A
   reused id silently points used_ids, the calendar and the library at the
   wrong video.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import script_composer as sc


def bank(n_themes=4, pairs=8, closers=8):
    """A synthetic bank: every theme identical, so only weights differ."""
    out = {}
    for t in range(n_themes):
        name = f"t{t}"
        out[name] = {
            "keywords": [name],
            "hooks": [[f"{name} hook {i} a", f"{name} hook {i} b"] for i in range(pairs)],
            "bodies": [[f"{name} body {i} a", f"{name} body {i} b", f"{name} body {i} c"]
                       for i in range(pairs)],
            "closers": [[f"{name} close {i}"] for i in range(closers)],
        }
    return out


class ComposeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.content = os.path.join(self.tmp, "content.json")
        self.state = os.path.join(self.tmp, "state.json")
        self.config = os.path.join(self.tmp, "config.json")

    def run_compose(self, n, items=None, used_ids=(), bias=None, themes=4):
        with open(self.content, "w") as f:
            json.dump({"items": list(items or [])}, f)
        with open(self.state, "w") as f:
            json.dump({"used_ids": list(used_ids)}, f)
        with open(self.config, "w") as f:
            json.dump({"theme_bias": bias} if bias else {}, f)

        b = bank(n_themes=themes)
        with mock.patch.object(sc, "BANK", b), \
             mock.patch.object(sc, "CONTENT", self.content), \
             mock.patch.object(sc, "STATE", self.state), \
             mock.patch.object(sc, "CONFIG", self.config), \
             mock.patch.object(sc, "TRENDS", os.path.join(self.tmp, "none.json")), \
             mock.patch.object(sc, "performance_weights", return_value={}), \
             mock.patch.object(sc, "ATOMIC_NICHES", set()), \
             mock.patch.object(sc, "_fit_runtime",
                               side_effect=lambda h, b_, c: list(h) + list(b_) + list(c)):
            return sc.compose(n)


class TestWeightingActuallyWorks(ComposeCase):
    def test_a_weighted_theme_is_not_capped_at_two(self):
        """The single-pass bug pinned the top theme to exactly 2 per batch."""
        added = self.run_compose(9, bias={"t0": 20.0})
        n_t0 = sum(1 for i in added if i["theme"] == "t0")
        self.assertEqual(len(added), 9)
        self.assertGreater(n_t0, 2,
                           f"weighted theme got only {n_t0} of 9 — capped again")

    def test_the_weighted_theme_is_the_majority(self):
        added = self.run_compose(9, bias={"t0": 20.0})
        n_t0 = sum(1 for i in added if i["theme"] == "t0")
        self.assertGreaterEqual(n_t0, 5, "a flagship series must dominate its own queue")

    def test_variety_survives_the_fix(self):
        """Dominant is not the same as exclusive — never 3 of a theme in a row."""
        added = self.run_compose(9, bias={"t0": 20.0})
        themes = [i["theme"] for i in added]
        for i in range(len(themes) - 2):
            self.assertFalse(themes[i] == themes[i + 1] == themes[i + 2],
                             f"3 in a row at {i}: {themes}")
        self.assertGreater(len({i["theme"] for i in added}), 1)

    def test_no_bias_still_spreads_across_themes(self):
        added = self.run_compose(8)
        self.assertGreaterEqual(len({i["theme"] for i in added}), 2)

    def test_it_stops_cleanly_when_the_pool_runs_dry(self):
        added = self.run_compose(500, themes=1)
        self.assertGreater(len(added), 0)
        self.assertLess(len(added), 500)


class TestIdAllocation(ComposeCase):
    def test_ids_within_a_batch_are_unique(self):
        added = self.run_compose(9)
        ids = [i["id"] for i in added]
        self.assertEqual(len(ids), len(set(ids)))

    def test_it_skips_past_ids_already_in_content(self):
        existing = [{"id": "c002", "theme": "t0", "lines": ["x"]}]
        added = self.run_compose(4, items=existing)
        self.assertNotIn("c002", [i["id"] for i in added])

    def test_it_skips_ids_owned_by_published_videos(self):
        """A published script pruned out of content.json still owns its id."""
        added = self.run_compose(4, used_ids=["c001", "c002", "c003"])
        got = [i["id"] for i in added]
        self.assertFalse({"c001", "c002", "c003"} & set(got),
                         f"reused a published id: {got}")

    def test_a_gap_in_the_middle_is_filled_not_skipped(self):
        added = self.run_compose(2, used_ids=["c001", "c003"])
        self.assertEqual([i["id"] for i in added], ["c002", "c004"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
