#!/usr/bin/env python3
"""List the sessions the daemon is tracking, and end ones you're done with.

  python tools/sessions.py              # numbered list, in the device's order
  python tools/sessions.py end 3        # remove row 3
  python tools/sessions.py end 3 5      # several at once
  python tools/sessions.py end 626bc8c5 # or by session id (any unique prefix)

Ending a row only removes it from the daemon and the device; the Claude Code
session itself is untouched, and its next event (your next prompt, say) brings
it back. Useful for sessions left behind by a restart or a closed window, and
for parking one that's waiting on you while you step away.

Run it on the daemon machine, with the daemon running and `sessions = on`.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from daemon.session_status import (  # noqa: E402
    DEFAULT_PORT, NEEDS_YOU, PARKED, STALE, TOKEN_HEADER, WORKING, YOUR_TURN,
    SessionTracker, read_config_value, your_turn_alert_from_config,
)

STATE_NAMES = {WORKING: "working", NEEDS_YOU: "needs you", YOUR_TURN: "your turn", STALE: "stale",
               PARKED: "parked"}
IDLE_PROMPT_DELAY = 70   # s: Claude Code's idle_prompt lands ~60 s after Stop and re-adds the row


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Clawdmeter"
    return Path.home() / ".config" / "claude-usage-monitor"


def load_sessions(base: Path) -> list:
    quiet = lambda m: None
    tracker = SessionTracker(base / "sessions.json", log=quiet,
                             your_turn_alert=your_turn_alert_from_config(base / "config", quiet))
    tracker.load()
    return tracker.listing()


def age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def print_list(sessions: list) -> None:
    if not sessions:
        print("No sessions.")
        return
    now = time.time()
    for i, (e, label, state) in enumerate(sessions, 1):
        print(f"{i:>2}  {e.host:8} {label:20} {STATE_NAMES[state]:9}  {age(now - e.updated):>6} ago  {e.sid[:8]}")


def resolve(sessions: list, ref: str):
    if ref.isdigit() and 1 <= int(ref) <= len(sessions):
        return sessions[int(ref) - 1]
    matches = [s for s in sessions if s[0].sid.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"{ref!r} matches {'no session' if not matches else 'more than one session'}")


def end_session(port: int, token: str, host: str, sid: str) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/hook/{host}",
        data=json.dumps({"hook_event_name": "SessionEnd", "session_id": sid, "reason": "other"}).encode(),
        headers={"Content-Type": "application/json", TOKEN_HEADER: token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except OSError as e:
        sys.exit(f"Can't reach the daemon on port {port}: {e}. Is it running with sessions = on?")
    if status != 204:
        sys.exit(f"Daemon answered {status} (403 usually means a wrong token)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", nargs="?", choices=["list", "end"], default="list")
    p.add_argument("refs", nargs="*", help="row numbers from the list, or session id prefixes")
    args = p.parse_args()

    base = config_dir()
    sessions = load_sessions(base)
    if args.action == "list":
        print_list(sessions)
        return
    if not args.refs:
        p.error("end needs at least one row number or session id")

    try:
        targets = [resolve(sessions, ref) for ref in args.refs]
    except ValueError as e:
        print_list(sessions)
        sys.exit(f"\n{e}")
    try:
        token = (base / "sessions-token").read_text().strip()
    except OSError:
        sys.exit(f"No token at {base / 'sessions-token'}; start the daemon with sessions = on")
    try:
        port = int(read_config_value(base / "config", "sessions_port") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT

    now = time.time()
    for e, label, state in targets:
        end_session(port, token, e.host, e.sid)
        print(f"Ended {e.host} {label} ({e.sid[:8]})")
        if e.state == YOUR_TURN and now - e.updated < IDLE_PROMPT_DELAY:
            print("  It finished under a minute ago, so Claude Code's idle reminder may bring it back; "
                  "end it again after that.")


if __name__ == "__main__":
    main()
