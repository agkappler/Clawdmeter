#!/usr/bin/env python3
"""Install (or remove) the Claude Code hooks that feed Clawdmeter's session list.

Run it on every machine you use Claude Code on: native Windows, macOS, Linux,
inside WSL, and on SSH remotes. It adds Claude Code's built-in `http` hooks to
`settings.json`, which POST each session event to the Clawdmeter daemon's
receiver on 127.0.0.1. Other hooks in the file are left alone, and running it
again just refreshes its own entries.

  # On the machine running the daemon (after `sessions = on` + a daemon restart):
  python3 tools/install_session_hooks.py

  # In WSL (needs mirrored networking) or on an SSH remote, pass the token
  # from the daemon machine's `sessions-token` file:
  python3 install_session_hooks.py --host devbox --token <token> --remote

  python3 tools/install_session_hooks.py --uninstall

Python 3.8+, standard library only, so it can be copied to a remote as-is.
See docs/session-status.md and openspec/changes/add-session-status/.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_PORT = 47123
TOKEN_HEADER = "X-Clawdmeter-Token"
TIMEOUT = 1   # seconds; Claude Code's default for http hooks is 600. A hung (not dead) daemon costs this per hook.

# Events that move a session between working / needs you / your turn / gone.
# SessionStart is absent on purpose: it doesn't support `http` hooks.
EVENTS = [
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "Notification",
    "Stop",
    "StopFailure",
    "SessionEnd",
]

# Where an organization's managed settings may live; only read, to warn about
# an `allowedHttpHookUrls` list that would block these hooks.
MANAGED_SETTINGS = {
    "darwin": [Path("/Library/Application Support/ClaudeCode/managed-settings.json")],
    "linux": [Path("/etc/claude-code/managed-settings.json")],
    "win32": [Path(r"C:\Program Files\ClaudeCode\managed-settings.json"),
              Path(r"C:\ProgramData\ClaudeCode\managed-settings.json")],
}


# -- environment ------------------------------------------------------------------

def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def wsl_networking_mode() -> str | None:
    """"mirrored", "nat", ... or None when it can't be told (older WSL)."""
    try:
        out = subprocess.run(["wslinfo", "--networking-mode"], capture_output=True,
                             text=True, timeout=5)
        mode = out.stdout.strip().lower()
        return mode or None
    except (OSError, subprocess.SubprocessError):
        return None


def default_host() -> str:
    if is_wsl():
        return "wsl"
    return socket.gethostname().split(".")[0]


def host_tag(raw: str) -> str:
    """Same rule as the daemon: letters, digits, - and _, at most 8 chars."""
    return re.sub(r"[^A-Za-z0-9_-]", "", raw)[:8]


def local_token_file() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Clawdmeter"
    else:
        base = Path.home() / ".config" / "claude-usage-monitor"
    return base / "sessions-token"


def wsl_windows_token_file() -> Path | None:
    """Inside WSL, the Windows daemon's token file, if it can be located."""
    try:
        out = subprocess.run(["cmd.exe", "/c", "echo %LOCALAPPDATA%"], capture_output=True,
                             text=True, timeout=10)
        win = out.stdout.strip().splitlines()[-1].strip()
        if not win or "%" in win:
            return None
        unix = subprocess.run(["wslpath", "-u", win], capture_output=True, text=True,
                              timeout=5).stdout.strip()
        return Path(unix) / "Clawdmeter" / "sessions-token" if unix else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def find_token() -> tuple[str | None, Path | None]:
    candidates = [local_token_file()]
    if is_wsl():
        win = wsl_windows_token_file()
        if win:
            candidates.insert(0, win)
    for path in candidates:
        try:
            token = path.read_text().strip()
            if token:
                return token, path
        except OSError:
            continue
    return None, None


def default_config_dirs() -> list[Path]:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return [Path(env).expanduser()] if env else [Path.home() / ".claude"]


# -- settings.json -----------------------------------------------------------------

def hook_url(port: int, host: str) -> str:
    return f"http://127.0.0.1:{port}/hook/{host}"


def our_hook(port: int, host: str, token: str) -> dict:
    return {
        "type": "http",
        "url": hook_url(port, host),
        "timeout": TIMEOUT,
        "headers": {TOKEN_HEADER: token},
    }


def is_ours(hook: dict) -> bool:
    """Recognise our entries by their header, whatever port/host/token they had."""
    return (isinstance(hook, dict) and hook.get("type") == "http"
            and TOKEN_HEADER in (hook.get("headers") or {}))


def strip_ours(settings: dict) -> int:
    """Remove every Clawdmeter hook, dropping groups and events left empty."""
    removed = 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept_groups.append(group)
                continue
            kept = [h for h in inner if not is_ours(h)]
            removed += len(inner) - len(kept)
            if kept:
                kept_groups.append(dict(group, hooks=kept))
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del settings["hooks"]
    return removed


def add_ours(settings: dict, port: int, host: str, token: str) -> None:
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        hooks.setdefault(event, []).append({"hooks": [our_hook(port, host, token)]})


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)   # strict JSON, as Claude Code requires
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def write_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".clawdmeter-backup"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# -- checks ------------------------------------------------------------------------

def allowlist_blocks(url: str, files: list[Path]) -> list[Path]:
    """Settings files whose allowedHttpHookUrls list doesn't admit `url`."""
    blocking = []
    for f in files:
        try:
            allowed = load_settings(f).get("allowedHttpHookUrls")
        except (OSError, ValueError):
            continue
        if isinstance(allowed, list) and not any(
                isinstance(p, str) and (fnmatch.fnmatchcase(url, p) or url.startswith(p))
                for p in allowed):
            blocking.append(f)
    return blocking


# -- main --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", help="short machine tag shown on the device (default: hostname, or 'wsl')")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--token", help="the daemon's sessions-token (default: read it from this machine)")
    p.add_argument("--config-dir", action="append", type=Path,
                   help="Claude config dir to install into; repeatable "
                        "(default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    p.add_argument("--remote", action="store_true",
                   help="this is an SSH remote: print the RemoteForward line to add on your machine")
    p.add_argument("--uninstall", action="store_true", help="remove the Clawdmeter hooks")
    p.add_argument("--dry-run", action="store_true", help="print the result instead of writing it")
    args = p.parse_args(argv)

    config_dirs = args.config_dir or default_config_dirs()
    host = host_tag(args.host or default_host())
    if not args.uninstall and not host:
        print("error: --host must contain letters or digits", file=sys.stderr)
        return 2

    token = args.token
    if not args.uninstall and not token:
        token, source = find_token()
        if not token:
            print(f"error: no token found (looked for {local_token_file()}).\n"
                  "  On the daemon machine: set `sessions = on` in the daemon config and restart\n"
                  "  the daemon, which creates it. Elsewhere: pass --token <contents of that file>.",
                  file=sys.stderr)
            return 2
        print(f"Using the token from {source}")

    url = hook_url(args.port, host)
    for config_dir in config_dirs:
        path = config_dir / "settings.json"
        try:
            settings = load_settings(path)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"error: {path} isn't valid JSON ({e}); fix it first, nothing written", file=sys.stderr)
            return 1
        removed = strip_ours(settings)
        if not args.uninstall:
            add_ours(settings, args.port, host, token)
        if args.dry_run:
            print(f"--- {path}")
            print(json.dumps(settings, indent=2))
            continue
        if args.uninstall and not removed:
            print(f"{path}: no Clawdmeter hooks to remove")
            continue
        write_settings(path, settings)
        if args.uninstall:
            print(f"{path}: removed {removed} Clawdmeter hook(s)")
        else:
            print(f"{path}: installed {len(EVENTS)} hooks -> {url}")

    if args.uninstall:
        return 0

    # Warnings that would otherwise fail silently.
    checked = [d / "settings.json" for d in config_dirs] + MANAGED_SETTINGS.get(sys.platform, [])
    for f in allowlist_blocks(url, checked):
        print(f"warning: {f} sets allowedHttpHookUrls without {url}; Claude Code won't run these hooks")
    if is_wsl():
        mode = wsl_networking_mode()
        if mode and mode != "mirrored":
            print(f"warning: WSL networking mode is '{mode}'. These hooks reach the Windows daemon only\n"
                  "  with mirrored networking: add `networkingMode=mirrored` under [wsl2] in\n"
                  "  %UserProfile%\\.wslconfig, then run `wsl --shutdown`.")
        elif mode is None:
            print("note: couldn't tell WSL's networking mode; these hooks need mirrored networking.")
    if args.remote:
        print("\nOn the machine running the daemon, add this under this remote's `Host` entry in\n"
              f"~/.ssh/config, then reconnect:\n\n    RemoteForward {args.port} 127.0.0.1:{args.port}\n")
    print("Claude Code picks up settings changes without a restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
