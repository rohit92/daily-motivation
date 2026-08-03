#!/usr/bin/env python3
"""Tests for cutting one long voice recording into per-line narration.

Both normalisation tests below are regressions, not hypotheticals — each one
rejected a perfectly good take during the first end-to-end run:

  * The scripts quote phrases: "Say: 'I'm Rohit.'". The word regex swallowed the
    quote marks, so the token was "'i'm" (never matching the contraction table)
    plus a stray "'" of its own. Best match 0.50 on a correct reading.
  * Whisper writes down what it hears, and a spoken "I'm" is transcribed "I am"
    about half the time. On a three-word line that alone scores 0.57.

A rejected good take costs the creator a re-record, which is the one thing this
workflow exists to avoid.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voiceover as V


def words(text, t0=0.0, step=0.4):
    """Fake transcript words with monotonic timings."""
    return [{"word": w, "start": t0 + i * step, "end": t0 + (i + 1) * step}
            for i, w in enumerate(V._norm(text))]


class TestNormalise(unittest.TestCase):
    def test_quote_marks_do_not_glue_onto_words(self):
        self.assertEqual(V._norm("Say: 'I'm Rohit.'"), ["say", "i", "am", "rohit"])

    def test_no_empty_token_from_a_bare_quote(self):
        self.assertNotIn("", V._norm("'my cousin'"))
        self.assertEqual(V._norm("'my cousin'"), ["my", "cousin"])

    def test_contractions_expand_to_match_whisper(self):
        """Whisper hears "I'm" and often writes "I am". Both must normalise same."""
        self.assertEqual(V._norm("I'm Rohit"), V._norm("I am Rohit"))
        self.assertEqual(V._norm("don't"), V._norm("do not"))
        self.assertEqual(V._norm("it's"), V._norm("it is"))

    def test_case_and_punctuation_are_ignored(self):
        self.assertEqual(V._norm("Only teachers give exams."),
                         V._norm("only  TEACHERS give exams"))

    def test_empty_input_is_harmless(self):
        self.assertEqual(V._norm(""), [])
        self.assertEqual(V._norm(None), [])


class TestAlign(unittest.TestCase):
    def test_a_clean_take_matches_every_line(self):
        items = [{"id": "c001", "lines": ["Only teachers give exams.",
                                          "Students take them."]}]
        w = words("Only teachers give exams Students take them")
        cuts = V.align(items, w)
        self.assertEqual(len(cuts), 2)
        self.assertTrue(all(c["score"] >= V.MATCH_MIN for c in cuts))
        self.assertEqual(cuts[0]["index"], 0)
        self.assertEqual(cuts[1]["index"], 1)

    def test_a_contraction_in_the_script_still_matches(self):
        items = [{"id": "c001", "lines": ["Say: 'I'm Rohit.'"]}]
        cuts = V.align(items, words("say I am Rohit"))
        self.assertEqual(len(cuts), 1)
        self.assertGreaterEqual(cuts[0]["score"], 0.9)

    def test_a_skipped_line_is_a_hard_error(self):
        """Silently cutting around a missing line puts the wrong audio under
        the wrong caption on a live upload."""
        items = [{"id": "c001", "lines": ["Only teachers give exams.",
                                          "Something never spoken at all."]}]
        with self.assertRaises(SystemExit) as ctx:
            V.align(items, words("Only teachers give exams"))
        self.assertIn("Nothing was written", str(ctx.exception))

    def test_the_error_names_the_line_it_could_not_find(self):
        items = [{"id": "c009", "lines": ["A line that was never read aloud."]}]
        with self.assertRaises(SystemExit) as ctx:
            V.align(items, words("completely different words here"))
        self.assertIn("c009", str(ctx.exception))

    def test_a_retake_wins_over_the_fluffed_first_attempt(self):
        """'Fluffed it? Just say the line again' is the promise on the sheet."""
        items = [{"id": "c001", "lines": ["Students take them."]}]
        w = words("Students take Students take them")
        cuts = V.align(items, w)
        self.assertEqual(len(cuts), 1)
        # the chosen span must start at the SECOND "students", not the first
        self.assertGreater(cuts[0]["start"], w[0]["start"])

    def test_lines_are_cut_in_order_and_do_not_overlap(self):
        items = [{"id": "c001", "lines": ["Only teachers give exams.",
                                          "Students take them."]}]
        cuts = V.align(items, words("Only teachers give exams Students take them"))
        self.assertLessEqual(cuts[0]["end"], cuts[1]["start"] + 1e-9)


class TestEndcapStaysInSync(unittest.TestCase):
    """The endcap sentence is built independently in two modules.

    voiceover.py puts it on the recording sheet; make_video.py is what actually
    gets narrated. If they ever drift, the creator records one sentence and the
    aligner hunts for a different one — the take fails for a reason that points
    nowhere near the cause.
    """

    def test_the_sheet_asks_for_exactly_what_gets_narrated(self):
        import paths
        import make_video as M
        for slug in ("education", "motivation", "facts"):
            meta = paths.channel_meta(slug)
            M._set_branding(meta.get("name"), meta.get("handle"),
                            meta.get("brand_color"))
            self.assertEqual(M.ENDCAP_LINE, V.endcap_line(slug),
                             f"endcap wording drifted apart for {slug}")


class TestNarrationGate(unittest.TestCase):
    """require_voice must hold the slot rather than ship the series in TTS.

    narrate() falls back to TTS per LINE, which is right when one line is
    missing from a take. But the nightly autopilot renders one script a day
    unattended, so without a gate it would quietly burn the entire flagship
    series in the synthetic voice the recording exists to replace — and a
    consumed script cannot be un-consumed. Holding a slot is recoverable.
    """

    def setUp(self):
        import make_video as M
        self.M = M

    def test_a_script_with_no_recording_reports_every_line(self):
        item = {"id": "no-such-script", "lines": ["a", "b", "c"]}
        self.assertEqual(self.M.missing_narration("education", item), [1, 2, 3])

    def test_line_numbers_are_1_based_for_humans(self):
        item = {"id": "no-such-script", "lines": ["only one"]}
        self.assertEqual(self.M.missing_narration("education", item), [1])

    def test_a_fully_recorded_script_reports_nothing(self):
        item = {"id": "rec", "lines": ["a", "b"]}
        with mock.patch("voiceover.line_wav", return_value="/tmp/x.wav"):
            self.assertEqual(self.M.missing_narration("education", item), [])

    def test_a_partly_recorded_script_names_only_the_gaps(self):
        item = {"id": "rec", "lines": ["a", "b", "c"]}
        with mock.patch("voiceover.line_wav",
                        side_effect=lambda c, i, n: "/tmp/x.wav" if n != 1 else None):
            self.assertEqual(self.M.missing_narration("education", item), [2])

    def test_an_empty_script_is_not_reported_as_missing(self):
        self.assertEqual(self.M.missing_narration("education",
                                                  {"id": "x", "lines": []}), [])


class TestLookup(unittest.TestCase):
    def test_a_missing_recording_reports_none(self):
        self.assertIsNone(V.line_wav("education", "does-not-exist", 0))

    def test_no_script_id_is_harmless(self):
        self.assertIsNone(V.line_wav("education", None, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
