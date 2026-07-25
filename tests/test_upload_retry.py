#!/usr/bin/env python3
"""Tests for the resumable-upload retry loop in upload_youtube.py.

These guard the failure that silently cost real uploads: a dropped connection
mid-upload used to abort the whole video (chunksize=-1, no retry), leaving the
Short either missing or stuck in YouTube 'processing' at 0s duration.
"""
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import upload_youtube as U


class FakeStatus:
    def __init__(self, p): self._p = p
    def progress(self): return self._p


class FakeRequest:
    """next_chunk() raises the queued errors, then returns a finished response."""
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return FakeStatus(1.0), {"id": "VID123"}


def run_upload(errors, tmpfile):
    """Drive upload() with a fake YouTube service and a fake chunked request."""
    req = FakeRequest(errors)
    yt = mock.MagicMock()
    yt.videos.return_value.insert.return_value = req
    with mock.patch.object(U, "get_service", return_value=yt), \
         mock.patch.object(U, "load", return_value={}), \
         mock.patch.object(U, "_check_accepted"), \
         mock.patch("googleapiclient.http.MediaFileUpload"), \
         mock.patch.object(U.time, "sleep"):          # no real backoff waits
        vid = U.upload(tmpfile, "t", "d")
    return vid, req


class TestUploadRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "_tmp_upload.bin")
        with open(cls.tmp, "wb") as f:
            f.write(b"0" * 2048)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.tmp):
            os.remove(cls.tmp)

    def test_succeeds_with_no_errors(self):
        vid, req = run_upload([], self.tmp)
        self.assertEqual(vid, "VID123")
        self.assertEqual(req.calls, 1)

    def test_retries_urlerror_then_succeeds(self):
        """The exact error from the autopilot log (DNS/socket failure)."""
        errs = [urllib.error.URLError("nodename nor servname provided")] * 3
        vid, req = run_upload(errs, self.tmp)
        self.assertEqual(vid, "VID123")
        self.assertEqual(req.calls, 4)          # 3 failures + 1 success

    def test_gives_up_after_max_retries(self):
        errs = [urllib.error.URLError("down")] * (U.MAX_RETRIES + 1)
        with self.assertRaises(RuntimeError) as ctx:
            run_upload(errs, self.tmp)
        self.assertIn("after", str(ctx.exception))

    def test_transient_5xx_is_retried(self):
        from googleapiclient.errors import HttpError
        resp = mock.Mock(status=503, reason="Service Unavailable")
        vid, req = run_upload([HttpError(resp, b"{}")], self.tmp)
        self.assertEqual(vid, "VID123")
        self.assertEqual(req.calls, 2)

    def test_permanent_4xx_is_not_retried(self):
        """Quota/auth errors must fail fast, not burn 6 retries."""
        from googleapiclient.errors import HttpError
        resp = mock.Mock(status=403, reason="quotaExceeded")
        with self.assertRaises(HttpError):
            run_upload([HttpError(resp, b"{}")], self.tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
