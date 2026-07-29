#!/usr/bin/env python3
"""Tests for the search metadata that every upload was missing.

Before this, upload_youtube.upload() sent a snippet with no `tags` key and a
categoryId hardcoded to "22". All 28 videos across the three channels went up
untagged, and the English-teaching channel and the science-facts channel were
both filed under "People & Blogs". Search was ~1% of all views.

These tests hold the fix in place at the only point that matters: the body
actually handed to videos().insert().
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seo
import upload_youtube as U


class FakeStatus:
    def __init__(self, p): self._p = p
    def progress(self): return self._p


class FakeRequest:
    def next_chunk(self):
        return FakeStatus(1.0), {"id": "VID123"}


def captured_body(channel, theme=None, longform=False, title="t"):
    """Run an upload and return the snippet dict sent to YouTube."""
    yt = mock.MagicMock()
    yt.videos.return_value.insert.return_value = FakeRequest()
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_seo.bin")
    with open(tmp, "wb") as f:
        f.write(b"0" * 512)
    try:
        U.set_channel(channel)
        with mock.patch.object(U, "get_service", return_value=yt), \
             mock.patch.object(U, "load", return_value={}), \
             mock.patch.object(U, "_check_accepted"), \
             mock.patch("googleapiclient.http.MediaFileUpload"):
            U.upload(tmp, title, "d", longform=longform, theme=theme)
    finally:
        os.remove(tmp)
    return yt.videos.return_value.insert.call_args.kwargs["body"]


class TestTagsReachYouTube(unittest.TestCase):
    def test_the_upload_body_actually_carries_tags(self):
        body = captured_body("education", theme="smalltalk")
        tags = body["snippet"].get("tags")
        self.assertTrue(tags, "upload sent no tags — the original bug")
        self.assertIn("small talk english", tags)

    def test_each_channel_gets_its_own_category(self):
        self.assertEqual(captured_body("education")["snippet"]["categoryId"], "27")
        self.assertEqual(captured_body("facts")["snippet"]["categoryId"], "27")
        self.assertEqual(captured_body("motivation")["snippet"]["categoryId"], "22")

    def test_a_broken_seo_module_never_blocks_an_upload(self):
        """Metadata is a nice-to-have; the video going out is not."""
        with mock.patch.object(seo, "tags_for", side_effect=RuntimeError("boom")), \
             mock.patch.object(seo, "category_id", side_effect=RuntimeError("boom")):
            body = captured_body("motivation", theme="focus")
        self.assertNotIn("tags", body["snippet"])
        self.assertEqual(body["snippet"]["categoryId"], "22")


class TestTagQuality(unittest.TestCase):
    def test_tags_stay_inside_youtubes_500_char_budget(self):
        for slug in ("motivation", "education", "facts"):
            for theme in list(seo.THEME_TERMS)[:6]:
                tags = seo.tags_for(slug, theme,
                                    title="A really long clickable title here #Shorts")
                cost = sum(len(t) + 1 + (2 if " " in t else 0) for t in tags)
                self.assertLessEqual(cost, 500, f"{slug}/{theme} = {cost} chars")

    def test_no_duplicate_tags(self):
        tags = seo.tags_for("motivation", "discipline", title="Discipline beats motivation")
        self.assertEqual(len(tags), len(set(tags)))

    def test_the_channel_name_is_searchable(self):
        self.assertIn("speak fluent", seo.tags_for("education", "grammar"))

    def test_the_random_handle_suffix_is_dropped(self):
        """@mind_blown-t2h — nobody types 't2h'. 'mind blown' is the search."""
        tags = seo.tags_for("facts", "ocean")
        self.assertIn("mind blown", tags)
        self.assertFalse([t for t in tags if "t2h" in t], tags)

    def test_every_bank_theme_has_search_terms(self):
        """A theme with no terms silently falls back to broad tags only."""
        import script_composer as sc
        missing = []
        for slug in ("motivation", "education", "facts"):
            sc.set_channel(slug)
            for theme in sc.BANK:
                if theme not in seo.THEME_TERMS:
                    missing.append(f"{slug}/{theme}")
        self.assertEqual(missing, [], f"themes with no search terms: {missing}")

    def test_shorts_and_longform_get_different_format_tags(self):
        short = seo.tags_for("motivation", "focus", longform=False)
        long = seo.tags_for("motivation", "focus", longform=True)
        self.assertIn("shorts", short)
        self.assertNotIn("shorts", long)


class TestThemeGuessing(unittest.TestCase):
    """The back catalogue has no theme recorded — it gets read off the title."""

    def test_it_reads_the_theme_from_the_words(self):
        cases = [
            ("motivation", "Doubt kills more dreams than failure", "doubt"),
            ("motivation", "Your focus is being stolen every single day", "focus"),
            ("motivation", "Comparison is the thief of joy", "comparison"),
            ("education", "You don't need perfect grammar", "grammar"),
            ("facts", "Your body may have a hidden organ", "biology"),
        ]
        for slug, title, want in cases:
            self.assertEqual(seo.guess_theme(slug, title), want, title)

    def test_trailing_hashtags_do_not_decide_the_theme(self):
        """metadata.py appends a rotating hashtag set unrelated to the theme.
        Counting those made half the catalogue guess 'discipline'."""
        bare = "Forty thousand people watched him fall"
        tagged = bare + " 🧠 #Shorts #motivation #discipline #mindset"
        self.assertEqual(seo.guess_theme("motivation", tagged),
                         seo.guess_theme("motivation", bare))

    def test_no_confident_match_returns_nothing(self):
        """A wrong theme is worse than none — it tags the video for the wrong
        search. Falling back to broad tags is the safe outcome."""
        self.assertEqual(seo.guess_theme("motivation", "Hello there friend"), "")

    def test_a_guess_is_always_a_real_theme_for_that_channel(self):
        import script_composer as sc
        for slug in ("motivation", "education", "facts"):
            sc.set_channel(slug)
            for title in ("Doubt and fear and focus", "grammar vocabulary ocean",
                          "sleep food history space"):
                g = seo.guess_theme(slug, title)
                if g:
                    self.assertIn(g, sc.BANK, f"{slug}: {g} is not a bank theme")


class TestChannelProfile(unittest.TestCase):
    def test_keywords_are_quoted_and_within_budget(self):
        for slug in ("motivation", "education", "facts"):
            kw = seo.channel_keywords(slug)
            self.assertLessEqual(len(kw), 500)
            self.assertIn('"', kw)          # multi-word phrases must be quoted

    def test_every_channel_has_a_real_about_text(self):
        for slug in ("motivation", "education", "facts"):
            about = seo.channel_about(slug)
            self.assertGreater(len(about), 150, slug)
            self.assertIn("Subscribe", about)


if __name__ == "__main__":
    unittest.main(verbosity=2)
