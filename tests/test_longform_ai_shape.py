#!/usr/bin/env python3
"""Tests for surviving a malformed AI script response.

A model is free to return whatever shape it likes. This one usually returns
"chapters" as a list of objects, but sometimes returns a list of LISTS — and
ch.get() then raises AttributeError and kills the whole build. That happened to
one long-form out of nine on 20 August and the retry succeeded, which is the
worst kind of failure: intermittent, and invisible until a month of unattended
runs has quietly skipped some of them.

A bad response must degrade to the hand-written bank, never raise.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_longform as ML


def reply(payload):
    """Patch ai_brain.llm to return this JSON, as the real one does."""
    return mock.patch("ai_brain.llm", return_value=(json.dumps(payload), None))


class TestMalformedChapters(unittest.TestCase):
    def test_chapters_as_lists_does_not_raise(self):
        """The exact shape that broke the 20 August build."""
        with reply({"chapters": [["a line", "another"], ["more", "lines"]]}):
            self.assertIsNone(ML.llm_script(5, None))

    def test_chapters_of_strings_does_not_raise(self):
        with reply({"chapters": ["just a string", "and another"]}):
            self.assertIsNone(ML.llm_script(5, None))

    def test_a_top_level_list_does_not_raise(self):
        """json.loads can return a list; .get() on it is the same crash."""
        with mock.patch("ai_brain.llm", return_value=('{"x": 1}', None)):
            self.assertIsNone(ML.llm_script(5, None))

    def test_mixed_good_and_bad_chapters_keeps_the_good_ones(self):
        good = {"title": "Real chapter",
                "lines": ["one", "two", "three", "four", "five"]}
        with reply({"chapters": [["junk"], good, good, good]}):
            out = ML.llm_script(5, None)
        self.assertIsNotNone(out, "usable chapters must survive a bad sibling")
        self.assertTrue(all(isinstance(c, dict) for c in out["chapters"]))

    def test_a_well_formed_response_still_works(self):
        good = {"title": "Chapter", "lines": ["a", "b", "c", "d", "e"]}
        with reply({"chapters": [good, good, good, good]}):
            out = ML.llm_script(5, None)
        self.assertIsNotNone(out)
        self.assertGreaterEqual(len(out["chapters"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
