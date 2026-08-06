#!/usr/bin/env python3
"""Tests for matching a library entry to the live video it already is.

This is the bug that put the same Short on the channel twice.

metadata.py renders a title as hook + a rotating emoji + a rotating set of
hashtags. Both rotate per render, so building the SAME script twice yields two
different title strings. reconcile.py bucketed live videos by the raw string,
so healthy_sibling() could not see that script 56_st006 was already live as
bX4yDoh_ivU — the live copy carried 🧠 and the entry carried 🔥. It concluded
the script had never been posted and re-queued it, and iPt5HrkFa5o went out as
a word-for-word duplicate of a video that had been public since 16 July.

YouTube reads near-identical uploads as reused content, which is the one thing
a channel chasing monetization cannot afford.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile as R

HOOK = "Forty thousand people watched him fall"


class TestTitleKey(unittest.TestCase):
    def test_the_rotating_emoji_does_not_hide_the_live_copy(self):
        """The exact pair that shipped the duplicate."""
        self.assertEqual(
            R.title_key(f"{HOOK} 🧠 #Shorts #motivation #discipline"),
            R.title_key(f"{HOOK} 🔥 #Shorts #motivation #hardwork"))

    def test_rotating_hashtags_alone_do_not_split_a_title(self):
        self.assertEqual(R.title_key(f"{HOOK} #Shorts #motivation"),
                         R.title_key(f"{HOOK} #shorts #nevergiveup #grind"))

    def test_case_and_punctuation_are_ignored(self):
        self.assertEqual(R.title_key("He Finished Last. The Stadium Stood Up!"),
                         R.title_key("he finished last the stadium stood up"))

    def test_genuinely_different_videos_stay_apart(self):
        self.assertNotEqual(R.title_key(f"{HOOK} 🧠 #Shorts"),
                            R.title_key("Comparison is the thief of joy 🧠 #Shorts"))

    def test_a_longform_title_survives_its_pipe(self):
        self.assertEqual(R.title_key("5 Minutes of Facts | Mind Blown"),
                         R.title_key("5 minutes of facts   mind blown"))

    def test_titles_that_are_only_decoration_do_not_all_collide(self):
        """Stripping everything would bucket these together and let one be
        adopted as the id for the other."""
        self.assertNotEqual(R.title_key("🧠 #Shorts"), R.title_key("🔥 #Shorts"))

    def test_empty_and_missing_titles_are_harmless(self):
        self.assertEqual(R.title_key(""), "")
        self.assertEqual(R.title_key(None), "")


class TestBucketing(unittest.TestCase):
    """What reconcile actually does with the key."""

    def test_two_renders_of_one_script_land_in_one_bucket(self):
        live = {"bX4yDoh_ivU": {"title": f"{HOOK} 🧠 #Shorts #motivation"},
                "iPt5HrkFa5o": {"title": f"{HOOK} 🔥 #Shorts #discipline"}}
        buckets = {}
        for vid, v in live.items():
            buckets.setdefault(R.title_key(v["title"]), []).append(vid)
        self.assertEqual(len(buckets), 1, "the duplicate pair must bucket together")
        self.assertEqual(len(next(iter(buckets.values()))), 2)

    def test_an_ambiguous_bucket_makes_adoption_decline(self):
        """Legacy id-adoption requires exactly one candidate, so a looser key
        cannot cause a wrong id to be claimed — it causes no claim at all."""
        live = {"a": {"title": f"{HOOK} 🧠"}, "b": {"title": f"{HOOK} 🔥"}}
        buckets = {}
        for vid, v in live.items():
            buckets.setdefault(R.title_key(v["title"]), []).append(vid)
        cands = buckets[R.title_key(f"{HOOK} ⚡")]
        self.assertNotEqual(len(cands), 1, "must be ambiguous, so adoption declines")


if __name__ == "__main__":
    unittest.main(verbosity=2)
