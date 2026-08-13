#!/usr/bin/env python3
"""Tests for reading back which video an upload became.

make_longform.py and storyteller.py shell out to upload_youtube.py and used to
infer success from the exit code alone, recording status="uploaded" and nothing
else. Three long-forms went live on 13 August that way — TxvP4SExYC8,
H5BN2e0dsZE, tw39di7q1HQ — and none of them had a video_id in the library, so
reconcile could not match them to the channel and channel_stats could not
attribute their views. They were the most valuable uploads of the week and the
system could not see them.

The calendar path (schedule_queue.mark_done) always wrote both. This is the
other path catching up.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import upload_youtube as U


class TestUploadedId(unittest.TestCase):
    def test_it_reads_a_shorts_url(self):
        self.assertEqual(
            U.uploaded_id("✓ Uploaded: https://youtube.com/shorts/TxvP4SExYC8"),
            "TxvP4SExYC8")

    def test_it_reads_a_longform_watch_url(self):
        self.assertEqual(
            U.uploaded_id("✓ Uploaded: https://youtube.com/watch?v=H5BN2e0dsZE"),
            "H5BN2e0dsZE")

    def test_it_finds_the_line_among_other_output(self):
        noisy = ("Uploading 08_story.mp4 (76.0 MB)…\n"
                 "   … 100%\n"
                 "✓ Uploaded: https://youtube.com/watch?v=tw39di7q1HQ\n"
                 "✓ Thumbnail set\n")
        self.assertEqual(U.uploaded_id(noisy), "tw39di7q1HQ")

    def test_a_failure_notice_is_not_mistaken_for_success(self):
        """upload_youtube prints a watch URL when reporting a video is NOT live.
        Matching that would record an id for an upload that did not happen."""
        self.assertEqual(
            U.uploaded_id("The video is not live: "
                          "https://youtube.com/watch?v=AAAAAAAAAAA"), "")

    def test_www_is_tolerated(self):
        self.assertEqual(
            U.uploaded_id("✓ Uploaded: https://www.youtube.com/shorts/TxvP4SExYC8"),
            "TxvP4SExYC8")

    def test_no_match_returns_empty_not_none(self):
        """Callers write the id only when truthy, so "" must be the miss value."""
        self.assertEqual(U.uploaded_id("nothing useful here"), "")

    def test_empty_and_none_are_harmless(self):
        self.assertEqual(U.uploaded_id(""), "")
        self.assertEqual(U.uploaded_id(None), "")

    def test_an_id_of_the_wrong_shape_is_rejected(self):
        self.assertEqual(U.uploaded_id("✓ Uploaded: https://youtube.com/shorts/tooshort"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
