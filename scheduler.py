#!/usr/bin/env python3
"""
scheduler.py — make the system run by itself every morning.

Installs a macOS launchd agent that runs autopilot.py daily at 7:00 AM:
sync stats → prepare today's video → (Sundays) build the weekly long-form.
Your Mac must be awake/logged-in at that time; if it was asleep, just open
the dashboard and press the button as usual — nothing breaks.

  python3 scheduler.py install          # turn the morning autopilot ON
  python3 scheduler.py install --hour 6 --minute 30
  python3 scheduler.py uninstall        # turn it OFF
  python3 scheduler.py status           # is it on?

(Also available as the "Morning autopilot" toggle in the dashboard Settings.)
"""

import argparse
import os
import plistlib
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LABEL = "com.mindsetrefuel.autopilot"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
LOG = os.path.join(HERE, ".work", "autopilot.log")


def install(hour, minute):
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    plist = {
        "Label": LABEL,
        # sys.executable = the python that has all our libraries (miniconda) —
        # the same interpreter rule the whole app follows.
        "ProgramArguments": [sys.executable, os.path.join(HERE, "autopilot.py")],
        "WorkingDirectory": HERE,
        # two firings: morning = build today's video; 7:30 PM = "still unposted"
        # nudge (autopilot switches to reminder mode after 5 PM by itself)
        "StartCalendarInterval": [{"Hour": hour, "Minute": minute},
                                  {"Hour": 19, "Minute": 30}],
        "StandardOutPath": LOG,
        "StandardErrorPath": LOG,
        "RunAtLoad": False,
    }
    # reload cleanly if it already exists
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    with open(PLIST, "wb") as f:
        plistlib.dump(plist, f)
    r = subprocess.run(["launchctl", "load", PLIST], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"launchctl load failed: {r.stderr.strip()}")
    print(f"✓ Morning autopilot ON — every day at {hour:02d}:{minute:02d}. "
          f"Log: {os.path.relpath(LOG, HERE)}")


def uninstall():
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    if os.path.exists(PLIST):
        os.remove(PLIST)
    print("✓ Morning autopilot OFF.")


def status():
    installed = os.path.exists(PLIST)
    loaded = LABEL in subprocess.run(["launchctl", "list"], capture_output=True,
                                     text=True).stdout
    if installed and loaded:
        try:
            with open(PLIST, "rb") as f:
                cal = plistlib.load(f).get("StartCalendarInterval", {})
            if isinstance(cal, list):
                cal = cal[0] if cal else {}
            when = f"{cal.get('Hour', 7):02d}:{cal.get('Minute', 0):02d}"
        except Exception:
            when = "?"
        print(f"ON — runs daily at {when} (+ 7:30 PM post reminder)")
        return True
    print("OFF")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "uninstall", "status"])
    ap.add_argument("--hour", type=int, default=7)
    ap.add_argument("--minute", type=int, default=0)
    a = ap.parse_args()
    if a.action == "install":
        install(a.hour, a.minute)
    elif a.action == "uninstall":
        uninstall()
    else:
        status()


if __name__ == "__main__":
    main()
