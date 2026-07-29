#!/usr/bin/env python3
"""Tests for network routing — the college-proxy path.

The failure these cover: uploads clicked from the dashboard worked on the campus
network while the 7:00/19:30 launchd runs silently didn't. The dashboard passed
the proxy to the children it spawned; the autopilot uploads in-process, inherits
launchd's bare environment, and so tried to reach googleapis.com directly.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import netcfg
import yt_auth

PROXY = "http://172.31.2.3:8080"
_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
         "NO_PROXY", "no_proxy")


class ProxyTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _VARS}
        for k in _VARS:
            os.environ.pop(k, None)
        netcfg._CACHE.update(t=0, v=None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        netcfg._CACHE.update(t=0, v=None)


class TestAuthAppliesProxy(ProxyTestCase):
    """yt_auth is the one door to Google — the route has to be set there."""

    def test_credentials_path_routes_through_the_proxy(self):
        with mock.patch.object(netcfg, "resolve", return_value=PROXY):
            self.assertEqual(yt_auth.use_network(), PROXY)
        self.assertEqual(os.environ.get("HTTPS_PROXY"), PROXY)
        self.assertEqual(os.environ.get("https_proxy"), PROXY)

    def test_httplib2_and_requests_both_pick_it_up(self):
        """The Data API + resumable upload use httplib2; OAuth refresh uses requests."""
        with mock.patch.object(netcfg, "resolve", return_value=PROXY):
            yt_auth.use_network()
        from httplib2 import proxy_info_from_environment
        info = proxy_info_from_environment("https")
        self.assertEqual((info.proxy_host, info.proxy_port), ("172.31.2.3", 8080))
        import requests
        self.assertEqual(
            requests.utils.get_environ_proxies("https://oauth2.googleapis.com")
            .get("https"), PROXY)

    def test_localhost_is_never_proxied(self):
        """Ollama runs on 127.0.0.1 — routing it through campus would break it."""
        with mock.patch.object(netcfg, "resolve", return_value=PROXY):
            yt_auth.use_network()
        self.assertIn("127.0.0.1", os.environ.get("NO_PROXY", ""))

    def test_direct_network_sets_nothing(self):
        with mock.patch.object(netcfg, "resolve", return_value=""):
            self.assertEqual(yt_auth.use_network(), "")
        self.assertIsNone(os.environ.get("HTTPS_PROXY"))

    def test_a_broken_proxy_config_never_blocks_an_upload(self):
        with mock.patch.object(netcfg, "apply", side_effect=RuntimeError("bad config")):
            self.assertEqual(yt_auth.use_network(), "")


class TestAutopilotRouting(ProxyTestCase):
    def test_children_inherit_the_proxy(self):
        """autopilot builds ENV at import; the proxy must be merged per run."""
        import autopilot
        with mock.patch.object(netcfg, "resolve", return_value=PROXY):
            env = autopilot._proxy_env()
        self.assertEqual(env.get("HTTPS_PROXY"), PROXY)

    def test_autopilot_logs_which_route_it_took(self):
        import autopilot
        with mock.patch.object(netcfg, "resolve", return_value=PROXY), \
             mock.patch.object(autopilot, "log") as logged:
            autopilot.use_network()
        self.assertTrue(any("network:" in str(c) for c in logged.call_args_list))


class TestDetection(ProxyTestCase):
    def test_a_slow_probe_is_retried_before_giving_up(self):
        """One timeout at 7 AM must not send the day's uploads down a dead route."""
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("timed out")
            return mock.MagicMock()

        with mock.patch("socket.create_connection", side_effect=flaky):
            self.assertTrue(netcfg._reachable(PROXY))
        self.assertEqual(len(calls), 2)

    def test_an_unreachable_proxy_still_means_direct(self):
        with mock.patch("socket.create_connection", side_effect=OSError("no route")):
            self.assertFalse(netcfg._reachable(PROXY))

    def test_auto_uses_the_proxy_when_it_answers(self):
        cfg = {"proxy": PROXY, "proxy_mode": "auto"}
        with mock.patch.object(netcfg, "_cfg", return_value=cfg), \
             mock.patch.object(netcfg, "_reachable", return_value=True):
            self.assertEqual(netcfg.resolve(), PROXY)

    def test_auto_goes_direct_at_home(self):
        cfg = {"proxy": PROXY, "proxy_mode": "auto"}
        with mock.patch.object(netcfg, "_cfg", return_value=cfg), \
             mock.patch.object(netcfg, "_reachable", return_value=False):
            self.assertEqual(netcfg.resolve(), "")

    def test_forced_off_ignores_a_reachable_proxy(self):
        cfg = {"proxy": PROXY, "proxy_mode": "off"}
        with mock.patch.object(netcfg, "_cfg", return_value=cfg), \
             mock.patch.object(netcfg, "_reachable", return_value=True):
            self.assertEqual(netcfg.resolve(), "")


class TestRefreshFailureIsDiagnosedHonestly(unittest.TestCase):
    """"Can't renew the login" and "you never connected" are different problems.

    Reporting the first as the second sent the owner to re-authorise an account
    that was never disconnected — three autopilot runs in a row said "click
    Connect YouTube" while the saved token was perfectly good and the real
    fault was the network.
    """

    def test_network_failures_are_named_as_network(self):
        for msg in ("TransportError: Failed to fetch token: Connection timed out",
                    "TransportError: [Errno 8] nodename nor servname provided",
                    "SSLError: handshake operation timed out",
                    "ServerNotFoundError: Unable to find the server at oauth2.googleapis.com",
                    "ConnectionError: Max retries exceeded with url"):
            self.assertTrue(yt_auth._looks_like_network(msg), msg)

    def test_a_genuinely_dead_token_is_not_blamed_on_the_network(self):
        for msg in ("RefreshError: ('invalid_grant: Token has been expired or revoked.')",
                    "RefreshError: invalid_client"):
            self.assertFalse(yt_auth._looks_like_network(msg), msg)

    def test_no_message_is_not_a_network_fault(self):
        self.assertFalse(yt_auth._looks_like_network(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
