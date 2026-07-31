#!/usr/bin/env python3
"""Tests for the duplicate guard on story-derived Shorts.

derive_shorts() gave every cut a fresh id but never checked whether the beat
had already been published. Stories are regenerated weekly from the same source
material, so beats recur — and "Forty thousand people watched him fall" was cut
a THIRD time, word for word, under a new id. Two of those reached YouTube.

YouTube reads that as reused content, which is the one thing a channel chasing
monetization cannot afford.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storyteller as st

HOOK = "Forty thousand people watched him fall."


class TestHookKey(unittest.TestCase):
    def test_the_rotating_emoji_does_not_make_it_a_new_hook(self):
        """The same script ships with a different emoji each time, so the
        rendered titles differ while the video is identical."""
        self.assertEqual(st._hook_key(HOOK + " 🧠"), st._hook_key(HOOK + " 🔥"))

    def test_punctuation_and_case_are_ignored(self):
        self.assertEqual(st._hook_key("Forty Thousand People Watched Him Fall!"),
                         st._hook_key(HOOK))

    def test_different_hooks_stay_different(self):
        self.assertNotEqual(st._hook_key(HOOK),
                            st._hook_key("Comparison is the thief of joy."))

    def test_empty_input_is_harmless(self):
        self.assertEqual(st._hook_key(""), "")
        self.assertEqual(st._hook_key(None), "")


class TestAlreadyPublished(unittest.TestCase):
    def _published(self, items, videos):
        with mock.patch.object(st, "load", return_value={"videos": videos}):
            return st._already_published({"items": items})

    def test_a_hook_from_a_previous_script_is_found(self):
        pub = self._published([{"id": "st002", "lines": [HOOK, "b", "c"]}], {})
        self.assertIn(st._hook_key(HOOK), pub)

    def test_a_hook_from_a_library_title_is_found(self):
        """The library stores the rendered title: hook + emoji + hashtags."""
        pub = self._published([], {"35_st002.mp4": {
            "title": HOOK + " 🧠 #Shorts #motivation #discipline"}})
        self.assertIn(st._hook_key(HOOK), pub)

    def test_an_unseen_hook_is_not_reported_as_published(self):
        pub = self._published([{"id": "st001", "lines": ["Something else"]}], {})
        self.assertNotIn(st._hook_key(HOOK), pub)

    def test_missing_data_does_not_crash(self):
        self.assertEqual(self._published([], {}), set())
        self.assertIsInstance(self._published([{"id": "x"}], {"a.mp4": {}}), set)


if __name__ == "__main__":
    unittest.main(verbosity=2)
