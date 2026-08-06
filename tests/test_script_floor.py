#!/usr/bin/env python3
"""Tests for refusing to render a script too short to fill the format.

The AI-script path (since disabled) left entries like

    "Don't watch life pass you by" / "Motivation is key to success" /
    "Make it happen today"

in the motivation bank — three lines of nothing. One of them rendered a 10.9s
Short against a channel whose own trend data puts the median winner at 18s. It
is too short to teach anything, too generic to remember, and it still costs the
full 1,600 quota units to upload, which is one of only five uploads a day.

pick_items() is the last gate before a render, so the floor belongs there.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_video as M


def content(*specs):
    # First lines must differ: pick_items also dedupes by opening line, and a
    # shared hook would hide whether the LENGTH filter did the work.
    return {"items": [{"id": i, "lines": [f"{i} hook"] + [f"{i} line {n}"
                                                          for n in range(1, c)]}
                      for i, c in specs]}


class TestScriptFloor(unittest.TestCase):
    def setUp(self):
        # a real config so _load_cfg finds min_script_lines (or its default)
        M.CONFIG = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "channels", "motivation", "config.json")

    def picked(self, c, used=()):
        return [i["id"] for i in M.pick_items(c, {"used_ids": list(used)}, 10)]

    def test_a_three_line_script_is_not_rendered(self):
        self.assertNotIn("tiny", self.picked(content(("ok", 6), ("tiny", 3))))

    def test_full_length_scripts_still_pass(self):
        got = self.picked(content(("a", 6), ("b", 5), ("c", 4)))
        self.assertEqual(got, ["a", "b", "c"])

    def test_the_floor_is_inclusive_at_four(self):
        """Four lines is the shortest that still has a hook and a closer."""
        self.assertIn("four", self.picked(content(("four", 4))))

    def test_an_empty_script_is_rejected(self):
        self.assertNotIn("empty", self.picked(content(("empty", 0), ("ok", 6))))

    def test_a_missing_lines_key_does_not_crash(self):
        c = {"items": [{"id": "broken"}, {"id": "ok", "lines": ["a"] * 6}]}
        self.assertEqual(self.picked(c), ["ok"])

    def test_short_scripts_do_not_block_the_good_ones_behind_them(self):
        """The stunted entry must be skipped, not end the scan."""
        got = self.picked(content(("tiny", 2), ("good", 6)))
        self.assertIn("good", got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
