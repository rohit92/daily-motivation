"""
Starter tests for paths.py — the single source of truth for per-channel file
locations. These are pure/offline tests (no network, no API keys) and exercise
the real branching logic: legacy fallback, per-channel dirs, and the registry.

Run:  python3 -m pytest tests/ -q     (or:  python3 -m unittest -q)
"""
import json
import os
import sys
import unittest

# Make the project root importable when tests are run from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import paths  # noqa: E402


class TestPaths(unittest.TestCase):
    def test_default_channel_when_none(self):
        p = paths.paths(None)
        self.assertEqual(p["slug"], paths.DEFAULT_CHANNEL)

    def test_returns_absolute_paths(self):
        p = paths.paths("motivation")
        for key in ("output", "long_form", "content", "yt_token", "client_secret"):
            self.assertTrue(os.path.isabs(p[key]), f"{key} should be absolute")

    def test_shared_roots_are_channel_independent(self):
        a = paths.paths("motivation")
        b = paths.paths("facts")
        # SHARED entries (client_secret, backgrounds, music, voices) never differ.
        for key in paths.SHARED:
            self.assertEqual(a[key], b[key], f"{key} must be shared across channels")

    def test_per_channel_files_differ_between_channels(self):
        a = paths.paths("education")
        b = paths.paths("facts")
        # content.json lives under each channel's own dir, so the paths differ.
        self.assertNotEqual(a["content"], b["content"])

    def test_client_secret_points_at_root(self):
        p = paths.paths("motivation")
        self.assertEqual(p["client_secret"], os.path.join(paths.HERE, "client_secret.json"))

    def test_registry_falls_back_when_missing(self):
        # channel_meta always returns a usable dict even for an unknown slug.
        m = paths.channel_meta("does-not-exist")
        self.assertIn("slug", m)
        self.assertIn("voice", m)
        self.assertEqual(m["slug"], "does-not-exist")

    def test_brand_label_is_uppercase(self):
        label = paths.brand_label("motivation")
        self.assertEqual(label, label.upper())
        self.assertTrue(len(label) > 0)

    def test_active_channels_are_marked_active(self):
        for c in paths.active_channels():
            self.assertTrue(c.get("active", True))

    def test_registry_is_valid_json_if_present(self):
        if os.path.exists(paths.REGISTRY):
            with open(paths.REGISTRY) as f:
                data = json.load(f)  # raises if malformed
            self.assertIsInstance(data.get("channels", []), list)


if __name__ == "__main__":
    unittest.main()
