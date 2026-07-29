#!/usr/bin/env python3
"""
yt_auth.py — ONE shared Google/YouTube login for the whole system.

Every tool that acts on your channel (uploading, commenting, replying,
retention analytics, thumbnails, playlists) goes through here, so you
authorize ONCE and everything works.

ONE-TIME SETUP (free, ~5 min — the only human step):
  1. console.cloud.google.com → the same project as your API key.
  2. Enable BOTH:  "YouTube Data API v3"  and  "YouTube Analytics API".
  3. OAuth consent screen → External → add yourself as a Test user.
  4. Credentials → Create credentials → OAuth client ID → "Desktop app".
  5. Download the JSON → rename to  client_secret.json  → put it in ~/youtube/.

Then click "Connect YouTube" in the dashboard Settings (or run
`python3 yt_auth.py --connect`). A browser opens once to approve; the token
is cached in assets/yt_token.json and refreshes itself forever after.

  python3 yt_auth.py --status    # connected?
  python3 yt_auth.py --connect   # run the one-time browser approval
"""

import argparse
import os
import sys

import paths as _paths

HERE = os.path.dirname(os.path.abspath(__file__))
# client_secret.json is SHARED — one OAuth client authorizes all three channels.
CLIENT_SECRET = _paths.paths(None)["client_secret"]
# Each channel stores its OWN token. Defaults to motivation; set_channel() swaps it.
_CHANNEL = _paths.DEFAULT_CHANNEL
TOKEN = _paths.paths(None)["yt_token"]


def set_channel(channel):
    """Point the OAuth token path at `channel`'s own yt_token.json."""
    global TOKEN, _CHANNEL
    _CHANNEL = channel or _paths.DEFAULT_CHANNEL
    TOKEN = _paths.paths(_CHANNEL)["yt_token"]

# upload = videos.insert; force-ssl = comments/replies/thumbnails/updates;
# yt-analytics = retention & traffic reports. One consent covers all three.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


class NotConnected(Exception):
    """Raised when the one-time Google setup hasn't been done yet."""


def setup_state():
    """'connected' | 'authorize' (secret present, consent pending) | 'missing'."""
    if not os.path.exists(CLIENT_SECRET):
        return "missing"
    return "connected" if os.path.exists(TOKEN) else "authorize"


def use_network():
    """Point this process's HTTP stacks at the right route before we talk to Google.

    Every path to YouTube goes through this module, and until now none of them
    applied the proxy. The dashboard injected it into the env of the children it
    spawned, so clicking Upload worked on the college network — but the launchd
    autopilot calls schedule_queue in-process, inherits launchd's bare
    environment, and so tried to reach googleapis.com directly. On a campus
    network that is a dead end, which is why scheduled uploads only ever
    succeeded at home.

    Both stacks read the env we set here: httplib2 (the Data API and the
    resumable upload) defaults to proxy_info_from_environment, and requests
    (the OAuth token refresh) reads the same variables.
    """
    try:
        import netcfg
        netcfg.apply()
        return netcfg.proxy_url()
    except Exception:
        return ""          # never let a proxy-config problem block an upload


_NETWORK_WORDS = ("transport", "connection", "timed out", "timeout", "ssl",
                  "temporary failure", "name resolution", "unreachable",
                  "getaddrinfo", "connection refused", "network is down",
                  "max retries",
                  # exact phrasings seen in this project's own logs
                  "unable to find the server",      # httplib2 DNS failure
                  "nodename nor servname")          # macOS resolver


def _looks_like_network(msg):
    """Was the refresh blocked by the network rather than by Google saying no?

    google-auth wraps everything in TransportError/RefreshError, so the class
    alone doesn't separate 'the wifi is blocking us' from 'this token is dead'.
    An actually-rejected token comes back with invalid_grant.
    """
    low = (msg or "").lower()
    if "invalid_grant" in low or "invalid_client" in low:
        return False               # Google answered: the token really is dead
    return any(w in low for w in _NETWORK_WORDS)


def get_credentials(interactive=True):
    use_network()
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise NotConnected(
            "Missing libraries. Run: python3 -m pip install "
            "google-api-python-client google-auth-oauthlib google-auth-httplib2")

    if not os.path.exists(CLIENT_SECRET):
        raise NotConnected(
            "client_secret.json not found in ~/youtube/. Do the one-time setup "
            "shown in the dashboard Settings → YouTube connection.")

    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
        # authorized before a scope was added → one fresh consent needed
        if creds and not set(SCOPES).issubset(set(creds.scopes or [])):
            creds = None
    why = ""
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save it. This used to refresh in memory only, so the token on disk
            # stayed stale forever and EVERY run had to reach Google before it
            # could do anything — turning one flaky moment into a total failure.
            try:
                open(TOKEN, "w").write(creds.to_json())
            except OSError:
                pass                      # refreshed fine; just couldn't cache it
        except Exception as e:
            why = f"{type(e).__name__}: {e}"
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            # Distinguish "you never authorised" from "we couldn't reach Google
            # to renew". Reporting the second as the first sent you to reconnect
            # an account that was never disconnected — which is what the
            # autopilot log showed for three runs straight while the saved
            # token was perfectly good.
            if _looks_like_network(why):
                raise NotConnected(
                    f"Could not reach Google to renew the login ({why}). Your "
                    f"YouTube connection is fine — this is the network. On the "
                    f"college wifi run: python3 netcfg.py --check")
            raise NotConnected("Not connected to YouTube yet — click 'Connect "
                               "YouTube' in the dashboard Settings once."
                               + (f" ({why})" if why else ""))
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
        creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(TOKEN), exist_ok=True)
        open(TOKEN, "w").write(creds.to_json())
    return creds


def data_api(interactive=True):
    """YouTube Data API v3 service (upload, comments, updates, playlists)."""
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=get_credentials(interactive))


def analytics_api(interactive=True):
    """YouTube Analytics API v2 service (retention, traffic sources)."""
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=get_credentials(interactive))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--connect", action="store_true")
    _paths.add_channel_arg(ap)
    a = ap.parse_args()
    set_channel(a.channel)
    if a.connect:
        try:
            get_credentials(interactive=True)
            print("✓ Connected — the system can now manage your channel "
                  "(upload, comments, replies, retention analytics).")
        except NotConnected as e:
            sys.exit(f"✗ {e}")
    else:
        state = setup_state()
        print({"connected": "✓ Connected",
               "authorize": "🟡 client_secret.json found — run --connect once",
               "missing": "⬜ Not set up (client_secret.json missing)"}[state])


if __name__ == "__main__":
    main()
