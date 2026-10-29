#!/usr/bin/env python3
"""Replay captured Claude Code hook events into a running daemon's session receiver.

The P4 board has no screenshot and no serial input, so this is how to put
known session states on the device for UI work without running real sessions.
Events come from daemon/tests/fixtures/hooks/ (real, scrubbed captures).

  python3 tools/post_fixture_hooks.py demo      # 5 sessions across hosts, one blocked, one parked
  python3 tools/post_fixture_hooks.py many      # 8 more (round board: 4 rows + "+N more")
  python3 tools/post_fixture_hooks.py replay    # the captured interactive session, in real time
  python3 tools/post_fixture_hooks.py clear     # end every session this tool created

Needs `sessions = on` in the daemon config. The token is read from the
daemon's `sessions-token` file unless --token is given.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "daemon" / "tests" / "fixtures" / "hooks"
PARK_EVENT = "ClawdmeterPark"   # what the /park skill sends; no capture, since Claude Code never does
PREFIX = "fixture-"   # session ids this tool creates, so `clear` only ends its own


def default_token_file() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Clawdmeter"
    else:
        base = Path.home() / ".config" / "claude-usage-monitor"
    return base / "sessions-token"


def fixture(name: str, sid: str, cwd: str) -> dict:
    if name == PARK_EVENT:
        return {"hook_event_name": PARK_EVENT, "session_id": PREFIX + sid}
    d = json.loads((FIXTURES / f"{name}.json").read_text())
    d.update(session_id=PREFIX + sid, cwd=cwd)
    return d


def post(args, host: str, event: dict) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{args.port}/hook/{host}",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json", "X-Clawdmeter-Token": args.token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except OSError as e:
        sys.exit(f"Can't reach the receiver on port {args.port}: {e}. Is the daemon running with sessions = on?")
    if status != 204:
        sys.exit(f"Receiver answered {status} (403 usually means a wrong token)")
    print(f"  {host:8} {event['session_id'][len(PREFIX):]:10} {event['hook_event_name']}"
          f" {event.get('notification_type', '')}")


DEMO = [  # host, sid, folder, events in order (last one decides the state)
    ("win", "a", "C:\\src\\Clawdmeter", ["UserPromptSubmit", "PreToolUse"]),
    ("wsl", "b", "/home/user/api", ["UserPromptSubmit", "PreToolUse", "PermissionRequest"]),
    ("devbox", "c", "/srv/infra", ["UserPromptSubmit", "Stop"]),
    ("win", "d", "C:\\src\\Clawdmeter", ["UserPromptSubmit", "PreToolUse"]),
    ("mac", "e", "/srv/billing-service", ["UserPromptSubmit", "Stop", PARK_EVENT]),
]


def run_demo(args, sessions) -> None:
    for host, sid, cwd, events in sessions:
        for name in events:
            post(args, host, fixture(name, sid, cwd))


def run_replay(args) -> None:
    seq = json.loads((FIXTURES / "sequence-interactive.json").read_text())
    start = time.monotonic()
    for step in seq:
        delay = step["t"] / args.speed - (time.monotonic() - start)
        if delay > 0:
            time.sleep(delay)
        body = dict(step["body"], session_id=PREFIX + "replay")
        post(args, "replay", body)


def run_clear(args) -> None:
    ids = {sid for _, sid, _, _ in DEMO} | {f"m{i}" for i in range(8)} | {"replay"}
    hosts = {h for h, *_ in DEMO} | {"many", "replay"}
    for host in sorted(hosts):
        for sid in sorted(ids):
            post(args, host, fixture("SessionEnd", sid, "/"))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenario", choices=["demo", "many", "replay", "clear"])
    p.add_argument("--port", type=int, default=47123)
    p.add_argument("--token", help="defaults to the daemon's sessions-token file")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed-up factor")
    args = p.parse_args()
    if not args.token:
        try:
            args.token = default_token_file().read_text().strip()
        except OSError:
            sys.exit(f"No token at {default_token_file()}; start the daemon with sessions = on, or pass --token")

    if args.scenario == "demo":
        run_demo(args, DEMO)
    elif args.scenario == "many":
        run_demo(args, [("many", f"m{i}", f"/p/project-{i}", ["UserPromptSubmit", "PreToolUse"])
                        for i in range(8)])
    elif args.scenario == "replay":
        run_replay(args)
    else:
        run_clear(args)


if __name__ == "__main__":
    main()
