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
from unittest import mock

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


class TestOrphanedRenders(unittest.TestCase):
    """A script whose video already exists must never be picked again.

    build_video() writes the file and only then appends to used_ids. A process
    killed between the two leaves the script looking unused while its video is
    on disk and on the calendar — which happened for real when a wedged
    pilot.py was killed after rendering 65_c031.mp4. The next render reused
    sequence 65 and was one pick away from shipping the same script twice,
    which YouTube reads as reused content.
    """

    def picked(self, content, rendered):
        with mock.patch.object(M, "rendered_ids", return_value=set(rendered)):
            return [i["id"] for i in M.pick_items(content, {"used_ids": []}, 10)]

    def test_a_rendered_script_is_not_picked_again(self):
        got = self.picked(content(("c031", 6), ("fresh", 6)), {"c031"})
        self.assertNotIn("c031", got)
        self.assertIn("fresh", got)

    def test_state_and_library_are_combined_not_replaced(self):
        """used_ids still counts even when the library knows nothing."""
        c = content(("a", 6), ("b", 6))
        with mock.patch.object(M, "rendered_ids", return_value=set()):
            got = [i["id"] for i in M.pick_items(c, {"used_ids": ["a"]}, 10)]
        self.assertEqual(got, ["b"])

    def test_an_unreadable_library_does_not_block_rendering(self):
        """Losing the library should degrade to the old behaviour, not stop work."""
        self.assertEqual(M.rendered_ids("no-such-channel"), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
