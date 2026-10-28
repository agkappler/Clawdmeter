## Why

The device sits on the desk next to the machines running Claude Code, but today it only shows plan usage. The thing that actually costs time is a session sitting blocked on a permission prompt or a question while you're looking at a different window — or a different machine. Sessions are often spread across native Windows, WSL, and an SSH box at once, so no single terminal shows them all. A glanceable "which sessions are working, which are waiting on me" list on the device, with an attention cue when one gets blocked, fills that gap using the BLE link and daemon that already exist.

## What Changes

- **Claude Code hooks report state.** Each machine's `~/.claude/settings.json` gets Claude Code's built-in `http` hooks (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`) that POST the event JSON straight to the daemon with a shared-secret header. No script, no `curl`, no shell differences between platforms.
- **The daemon gains a session receiver.** A small HTTP listener on `127.0.0.1` (default port 47123) accepts those posts, reduces each to `{session id, host tag, project label, state, last update}`, keeps a session table with age-based expiry that survives daemon restarts, and pushes changes to the device immediately (not on the 60s usage poll). Lives in a new shared module `daemon/session_status.py` used by both Python daemons (Windows and macOS).
- **Reaching the receiver from every place a session runs:**
  - Native Windows / macOS: localhost.
  - WSL: localhost, which requires WSL's mirrored networking mode (NAT mode is out of scope for v1).
  - SSH remote: `RemoteForward 47123 127.0.0.1:47123` in `~/.ssh/config`, so the remote's localhost tunnels back to the daemon.
- **New optional wire field `"ss"`.** Sent as its own BLE write, only when the visible list changes plus a 60s heartbeat, and applied by the firmware without touching usage data or its freshness stamp. Older firmware rejects it harmlessly; older daemons never send it.
- **Firmware shows a session list** with a colored state per row (working / needs you / your turn / stale), plus an attention cue when any session newly enters "needs you". Rendered outside `usage_group` so it stays visible when usage data is stale. Gated by a new `BoardCaps.has_session_list` flag; first board is the P4 (720×1280), others follow in later phases.
- **Two existing firmware bugs fixed on the way:** merge-only writes (today's `qd` supplement) refresh the usage freshness stamp, and the P4 has a single RX buffer, so back-to-back writes overwrite each other. Both would break this feature.
- **Installer** `tools/install_session_hooks.py` merges the hooks into `settings.json` idempotently (`--host`, `--token`, `--config-dir`, `--uninstall`), runnable on each machine including the remote.

## Capabilities

### New Capabilities
- `session-status`: hook-driven session state collection across local, WSL and SSH machines, the daemon receiver and `"ss"` wire field, and the on-device session list with attention cue.

### Modified Capabilities
(none — no capability specs exist yet)

## Impact

- **Host, new**: `daemon/session_status.py` (receiver + session table, pure and unit-testable), `tools/install_session_hooks.py`, `tools/post_fixture_hooks.py` (replays captured hook payloads for testing), `docs/session-status.md`, `daemon/tests/test_session_status.py`, `daemon/tests/fixtures/hooks/`.
- **Host, modified**: `claude_usage_daemon_windows.py` and `claude_usage_daemon.py` start the receiver and add a "sessions changed" wake-up to their poll loop; `config.example` gains `sessions`, `sessions_port` and `sessions_token`.
- **Firmware, shared**: `data.h` (session array), `main.cpp` (generic merge path, new `PARSE_SESSIONS`), `ui.cpp` (session list, attention cue, `ui_update_sessions()`), `hal/board_caps.h` (new flag), `template/caps.cpp`, `docs/porting/capability-flags.md`.
- **Firmware, board-local**: P4 `caps.cpp` sets the flag; P4 `ble.cpp` gets an RX queue.
- **Not touched**: the Bash Linux daemon and the Rust daemon (they never send `ss`; firmware simply shows no list), every board without the flag.
- **Upstream-friendly**: fully opt-in on both ends (config flag + hooks you install), so this can be offered back to mbonig/Clawdmeter as a PR.
