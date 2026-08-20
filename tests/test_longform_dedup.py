#!/usr/bin/env python3
"""Tests for never offering a long-form whose narration already shipped.

storyteller.py --make, run three times in a row on 20 August, produced three
byte-identical stories: 09, 10 and 11 all carried the same 17 chapters and the
same 113 lines. 09 was already live as BkKRswcd270 and the other two were
queued behind it, for 29 August and 5 September.

Nothing else caught it. The filenames differed, the durations matched to the
second, the library entries looked healthy. Only the words were the same, so
the words are what gets fingerprinted.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schedule_queue as SQ

STORY = {"chapters": [{"title": "One", "lines": ["a", "b", "c"]},
                      {"title": "Two", "lines": ["d", "e", "f"]}]}
OTHER = {"chapters": [{"title": "One", "lines": ["x", "y", "z"]},
                      {"title": "Two", "lines": ["p", "q", "r"]}]}


class TestLongformDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lf = os.path.join(self.tmp, "long_form")
        os.makedirs(self.lf)

    def build(self, spec):
        """spec: [(name, status, script_dict)] -> ready_longform file names."""
        lib = {"longform": {}}
        for name, status, script in spec:
            open(os.path.join(self.lf, name), "w").write("x")
            with open(os.path.join(self.lf, name.replace(".mp4", "_script.json")), "w") as f:
                json.dump(script, f)
            lib["longform"][name] = {"status": status, "duration_sec": 400,
                                     "created": "2026-08-20"}
        paths = {"long_form": self.lf, "library": os.path.join(self.tmp, "lib.json")}
        with open(paths["library"], "w") as f:
            json.dump(lib, f)
        with mock.patch.object(SQ._paths, "paths", return_value=paths), \
             mock.patch.object(SQ, "_entry", side_effect=lambda s, n, v, k: {"file": n}):
            return [e["file"] for e in SQ.ready_longform("motivation")]

    def test_a_ready_copy_of_a_live_story_is_not_offered(self):
        """The exact 20 August case: 10 duplicates the already-live 09."""
        got = self.build([("09.mp4", "uploaded", STORY),
                          ("10.mp4", "ready", STORY)])
        self.assertEqual(got, [], "a duplicate of a live video must not be queued")

    def test_two_ready_copies_yield_only_one(self):
        got = self.build([("10.mp4", "ready", STORY), ("11.mp4", "ready", STORY)])
        self.assertEqual(len(got), 1, "identical narration must be offered once")

    def test_genuinely_different_stories_both_survive(self):
        got = self.build([("10.mp4", "ready", STORY), ("12.mp4", "ready", OTHER)])
        self.assertEqual(len(got), 2)

    def test_a_missing_sidecar_does_not_block_a_video(self):
        """No script file means no fingerprint — degrade to the old behaviour."""
        lib = {"longform": {"20.mp4": {"status": "ready", "duration_sec": 400,
                                       "created": "2026-08-20"}}}
        open(os.path.join(self.lf, "20.mp4"), "w").write("x")
        paths = {"long_form": self.lf, "library": os.path.join(self.tmp, "lib.json")}
        with open(paths["library"], "w") as f:
            json.dump(lib, f)
        with mock.patch.object(SQ._paths, "paths", return_value=paths), \
             mock.patch.object(SQ, "_entry", side_effect=lambda s, n, v, k: {"file": n}):
            self.assertEqual(len(SQ.ready_longform("motivation")), 1)

    def test_an_empty_script_is_treated_as_no_fingerprint(self):
        got = self.build([("10.mp4", "ready", {"chapters": []}),
                          ("11.mp4", "ready", {"chapters": []})])
        self.assertEqual(len(got), 2, "unknown content must not be silently dropped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
