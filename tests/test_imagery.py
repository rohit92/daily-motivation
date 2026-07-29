#!/usr/bin/env python3
"""Tests for subject-matched imagery and its licence safety.

Two defects these hold shut:

  * Every video rendered the same animated gradient, or drew from 20 shared
    stock photos at random. A fact about a shrimp's punch was illustrated with
    elephants, because selection was by THEME ("animals") rather than by what
    the script actually says.
  * Licence filtering has to be right the first time. A share-alike or
    non-commercial image on a monetized channel is a legal problem that is
    invisible until it isn't.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import imagery


class TestLicenceSafety(unittest.TestCase):
    def test_public_domain_and_cc0_need_no_permission(self):
        for lic in ("CC0", "Public domain", "PD", "CC-Zero", "No restrictions"):
            self.assertTrue(imagery._ok_license(lic), lic)

    def test_plain_cc_by_is_allowed_only_when_asked(self):
        self.assertFalse(imagery._ok_license("CC BY 4.0"))
        self.assertTrue(imagery._ok_license("CC BY 4.0", allow_by=True))

    def test_share_alike_is_refused(self):
        """Embedding SA arguably makes the whole video a derivative that must
        also be SA — not a commitment to make silently on someone's channel."""
        for lic in ("CC BY-SA 3.0", "CC BY-SA 4.0"):
            self.assertFalse(imagery._ok_license(lic, allow_by=True), lic)

    def test_noncommercial_and_noderivatives_are_refused(self):
        for lic in ("CC BY-NC 2.0", "CC BY-ND 4.0", "CC BY-NC-SA 3.0"):
            self.assertFalse(imagery._ok_license(lic, allow_by=True), lic)

    def test_an_unknown_licence_is_refused(self):
        for lic in ("", None, "All rights reserved", "Fair use"):
            self.assertFalse(imagery._ok_license(lic, allow_by=True), repr(lic))


class TestSubjectExtraction(unittest.TestCase):
    def test_it_finds_what_the_fact_is_about(self):
        cases = [
            (["A shrimp's punch", "can boil water"], "shrimp"),
            (["The last woolly mammoths were alive", "when the pyramids stood"], "woolly"),
            (["The Pacific Ocean is so wide", "it holds every continent"], "pacific"),
            (["An octopus has three hearts", "and blue blood"], "octopus"),
        ]
        for lines, want in cases:
            self.assertEqual(imagery.subject_terms(lines)[0], want, lines[0])

    def test_possessives_become_searchable_nouns(self):
        """'shrimp's' is not a noun anyone's photo is tagged with."""
        self.assertIn("shrimp", imagery.subject_terms(["A shrimp's punch"]))

    def test_quantifiers_are_not_mistaken_for_the_subject(self):
        """'last woolly mammoths' must not yield 'last'."""
        for lines in (["The last woolly mammoths"], ["A group of flamingos"],
                      ["There are more stars in the sky"]):
            first = imagery.subject_terms(lines)[0]
            self.assertNotIn(first, {"last", "group", "more", "three"}, lines[0])

    def test_a_contentless_line_yields_nothing(self):
        self.assertEqual(imagery.subject_terms(["It is what it is"]), [])


class TestRelevanceRanking(unittest.TestCase):
    def test_the_subject_in_the_title_ranks_first(self):
        named = {"title": "File:Stenopus hispidus shrimp.jpg"}
        other = {"title": "File:Sunset over the bay.jpg"}
        self.assertLess(imagery._relevance(named, "shrimp"),
                        imagery._relevance(other, "shrimp"))

    def test_wrong_context_is_pushed_down(self):
        """A shrimp BOAT matches the word and shows no shrimp."""
        animal = {"title": "File:Stenopus hispidus shrimp.jpg"}
        boat = {"title": "File:Shrimp Boat on Bayou Lafourche.jpg"}
        self.assertLess(imagery._relevance(animal, "shrimp"),
                        imagery._relevance(boat, "shrimp"))


class TestCredits(unittest.TestCase):
    def setUp(self):
        self._real = imagery.load_manifest
        imagery.load_manifest = lambda: {"images": {
            "ocean/ocean_001.jpg": {"license": "CC0", "artist": "A", "page": "p1"},
            "_x/sub_001.jpg": {"license": "CC BY 4.0", "artist": "Ryan Donnelly",
                               "page": "https://commons.wikimedia.org/x"},
        }}

    def tearDown(self):
        imagery.load_manifest = self._real

    def test_cc_by_images_are_credited(self):
        block = imagery.credit_block(["/a/_x/sub_001.jpg"])
        self.assertIn("Ryan Donnelly", block)
        self.assertIn("CC BY 4.0", block)

    def test_public_domain_needs_no_credit_line(self):
        """A wall of unnecessary credits buries the subscribe line."""
        self.assertEqual(imagery.credit_block(["/a/ocean/ocean_001.jpg"]), "")

    def test_no_images_means_no_block(self):
        self.assertEqual(imagery.credit_block([]), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
