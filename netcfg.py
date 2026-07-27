#!/usr/bin/env python3
"""
netcfg.py — decides whether internet traffic goes DIRECT or through a proxy,
and can figure it out by itself.

config.json:
  "proxy":      "http://172.31.2.3:8080"   # your college proxy address
  "proxy_mode": "auto" | "on" | "off"       # auto = detect the network for you

AUTO detection: the college proxy lives on a private campus IP that is only
reachable when you're actually on the college network. So we just try to reach
it — if the proxy answers, you're on college → use it; if not, you're on your
hotspot/home → go direct. Result is cached briefly so we don't probe constantly.

Everything routes through netcfg so the whole app agrees:
  - urllib tools (YouTube API) use netcfg.opener() — obeys our decision and
    ignores the macOS system proxy either way.
  - edge-tts voice is handed netcfg.proxy_url().
  - Ollama is ALWAYS direct (handled in ai_brain) — localhost never proxied.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
# The proxy is a property of the NETWORK, not of a channel, so one setting drives
# everything. It lives in the channel configs (that's what the dashboard writes),
# so read the default channel's file and keep the old root config.json as an
# override. Reading only the root path was a silent no-op bug: config.json has not
# existed since the move to channels/<slug>/, so _cfg() always returned {} and the
# dashboard's proxy switch did nothing at all.
import paths as _paths

CONFIG = os.path.join(HERE, "config.json")
_CONFIG_FALLBACK = _paths.paths(None)["config"]

LOCAL = "localhost,127.0.0.1,::1,0.0.0.0"
_CACHE = {"t": 0.0, "v": None}       # memoized auto-detect result
_CACHE_TTL = 15                      # seconds — short so switching networks is picked up


def _cfg():
    for path in (CONFIG, _CONFIG_FALLBACK):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _mode(cfg):
    # explicit proxy_mode wins; fall back to the old use_proxy bool
    if "proxy_mode" in cfg:
        return cfg["proxy_mode"]
    return "on" if cfg.get("use_proxy") else "off"


def _reachable(addr, timeout=3, tries=2):
    """True if we can open a TCP connection to the proxy host:port.

    Retried, because a false negative is expensive: on campus the proxy is the
    only way out, so one slow probe at 7 AM would send the whole day's uploads
    down a direct route that cannot work — and a failed upload still costs 1,600
    quota units. A false positive is cheap by comparison.
    """
    p = urlparse(addr)
    host, port = p.hostname, p.port or 80
    for attempt in range(tries):
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except Exception:
            if attempt + 1 < tries:
                time.sleep(0.4)
    return False


def resolve():
    """Return the proxy URL to use right now, or '' for a direct connection."""
    cfg = _cfg()
    mode = _mode(cfg)
    addr = (cfg.get("proxy") or "").strip()
    if mode == "off" or not addr:
        return "" if mode != "on" else addr
    if mode == "on":
        return addr
    # auto: reachable proxy => on campus; unreachable => hotspot/home
    now = time.time()
    if _CACHE["v"] is not None and now - _CACHE["t"] < _CACHE_TTL:
        return _CACHE["v"]
    result = addr if _reachable(addr) else ""
    _CACHE.update(t=now, v=result)
    return result


def detected():
    """Human summary for the UI, e.g. 'Auto → college proxy (172.31.2.3:8080)'."""
    cfg = _cfg()
    mode = _mode(cfg)
    px = resolve()
    if mode == "on":
        return f"Forced ON → proxy {px}" if px else "Forced ON (no address set)"
    if mode == "off":
        return "Forced OFF → direct connection"
    return (f"Auto → college proxy detected ({px})" if px
            else "Auto → direct connection (personal / hotspot)")


def proxy_url():
    return resolve()


def opener():
    """A urllib opener that uses our resolved proxy (or forces DIRECT), ignoring
    whatever the macOS system proxy happens to be set to."""
    px = resolve()
    handler = urllib.request.ProxyHandler({"http": px, "https": px} if px else {})
    return urllib.request.build_opener(handler)


def proxy_env():
    """Env additions so child processes route the same way (localhost excluded)."""
    px = resolve()
    if not px:
        return {}
    return {"HTTP_PROXY": px, "HTTPS_PROXY": px, "http_proxy": px, "https_proxy": px,
            "NO_PROXY": LOCAL, "no_proxy": LOCAL}


def apply():
    os.environ.update(proxy_env())


def check():
    """Prove, from wherever you are right now, that uploads can reach YouTube.

    Run this ON the college wifi. It reports the route it picked and then
    actually calls Google over it, because "the proxy answers on port 8080" and
    "Google is reachable through it" are different claims — a proxy that wants a
    username answers the TCP probe and then returns 407 to everything.
    """
    cfg = _cfg()
    addr = (cfg.get("proxy") or "").strip()
    px = resolve()
    print(f"  proxy configured : {addr or '(none)'}")
    print(f"  mode             : {_mode(cfg)}")
    if addr:
        print(f"  proxy answers    : {'yes' if _reachable(addr) else 'no'}")
    print(f"  decision         : {detected()}")

    ok = True
    for name, url in (("googleapis.com", "https://www.googleapis.com/discovery/v1/apis"),
                      ("oauth2 token endpoint", "https://oauth2.googleapis.com/")):
        try:
            with opener().open(url, timeout=20) as r:
                print(f"  ✓ {name}: HTTP {r.status}")
        except urllib.error.HTTPError as e:
            # 4xx from the endpoint itself still proves we got there.
            if e.code == 407:
                print(f"  ✗ {name}: HTTP 407 — this proxy needs a username and "
                      f"password. Set proxy to http://USER:PASS@host:port")
                ok = False
            else:
                print(f"  ✓ {name}: reachable (HTTP {e.code})")
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            ok = False

    print("\n  " + ("Uploads can reach YouTube from this network. ✅"
                    if ok else
                    "Uploads CANNOT reach YouTube from this network. ❌"))
    return ok


if __name__ == "__main__":
    import argparse
    import urllib.error
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="test the real connection to YouTube from this network")
    if ap.parse_args().check:
        raise SystemExit(0 if check() else 1)
    print(detected())
