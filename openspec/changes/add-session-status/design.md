## Context

Claude Code runs hook commands at lifecycle points and passes a JSON object on stdin containing at least `session_id`, `cwd`, and `hook_event_name` (plus event-specific fields such as `notification_type` / `message` on `Notification`). Hooks run on whatever machine the session runs on, so for a user with sessions in native Windows, WSL and over SSH, the state originates on three different machines while only one (the Windows host) holds the BLE link to the device.

The Python daemons already send optional, independently-versioned payload fields (`q`, `qd`, `te`/`tu`) and already split oversize payloads into supplementary writes that `parse_json()` merges without touching usage freshness. This change reuses both patterns.

## Goals / Non-Goals

**Goals**
- Show every live Claude Code session from native Windows/macOS, WSL and SSH remotes on one device, with state: working, needs you, your turn, stale.
- "Needs you" (blocked on permission or a question) appears on the device within ~1s of the prompt showing.
- Nothing to install on a machine beyond a hooks block in `settings.json` (and an SSH config line for remotes). No per-machine script, no Python requirement on remotes.
- A broken or absent daemon never slows down or disturbs a Claude Code session.
- Opt-in on every side; zero change for anyone who doesn't enable it.

**Non-Goals**
- Acting on sessions from the device (approving prompts, focusing a window). Display only.
- Sessions in claude.ai cloud environments (they don't run local hooks).
- Bash Linux daemon and Rust daemon support in this change.
- Session titles/summaries — the label is the project folder name.
- Detecting that an SSH tunnel dropped while a detached (tmux) remote session keeps running; such sessions age into "stale".

## Decisions

### 1. Hook command is a bare `curl` forwarding stdin
```
curl -s -m 1 --data-binary @- "http://127.0.0.1:47123/hook?h=<host>" || true
```
(`curl.exe` and no `|| true` on native Windows, where `curl` may be a PowerShell alias.) The daemon parses Claude Code's raw hook JSON itself. This means the hook "script" is identical on every machine except the host tag, and works without Python on remotes.

`-m 1` caps any stall at one second; `|| true` keeps a down daemon from producing a non-zero exit. Exit code 2 is the only code Claude Code treats as blocking, and `curl` never returns it on its own, but swallowing errors avoids noise either way.

**Privacy:** raw hook JSON can include prompt text and tool inputs. It only travels to localhost (or through the user's own SSH tunnel), and the daemon keeps only `session_id`, `cwd` basename, event name and notification type — everything else is dropped on receipt and never logged.

**Alternative considered:** a per-machine hook script that sends only the fields needed. Rejected for v1: three platforms × a script to install and update, versus one-line commands. Revisit if the payload size or privacy posture becomes a concern.

### 2. Event → state mapping
| Event | State |
|---|---|
| `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | working |
| `Notification` with `notification_type` = `permission_prompt` or `elicitation_dialog` | **needs you** |
| `Stop`, `Notification` with `idle_prompt` | your turn |
| `SessionEnd` | removed |
| (no update for 30 min while working, 12 h otherwise) | stale → dropped after 12 h |

`PostToolUse` is what clears "needs you" after the user approves a permission prompt (sequence: `PreToolUse` → prompt → approve → tool runs → `PostToolUse`). If the user denies, the next `PreToolUse` or `Stop` clears it. If `notification_type` is missing (older Claude Code), any `Notification` maps to "needs you" — a false "needs you" is a better failure than a missed one.

### 3. Receiver: stdlib asyncio, localhost only
A ~100-line HTTP handler on `asyncio.start_server`, bound to `127.0.0.1`, inside the daemon's existing event loop. No new dependency (no aiohttp). Accepts `POST /hook` only, body ≤ 64 KB, returns `204` immediately. Port from config `sessions_port` (default 47123). If the port is taken, log once and continue without sessions — the usage display must never depend on this feature.

### 4. WSL: mirrored networking, file-drop fallback
With WSL's `networkingMode=mirrored`, WSL's localhost is the Windows host's and the standard hook works unchanged. Under default NAT, the installer (run inside WSL) instead writes a hook that appends the JSON to a spool directory on the Windows filesystem (`/mnt/c/Users/<user>/AppData/Local/Clawdmeter/sessions-spool/`), resolved once at install time. The Windows daemon drains that directory each tick (≤5s latency, acceptable for the fallback).

### 5. SSH: reverse port forward
`RemoteForward 47123 127.0.0.1:47123` under the remote's `Host` entry. The remote's hook posts to its own localhost and arrives at the Windows daemon. Requires the remote's sshd to allow TCP forwarding (default yes). If several SSH connections to the same remote are open, only the first binds the port; the rest warn and are harmless. Documented, not automated — the installer prints the line to add.

### 6. Session table and wire format
The daemon keys sessions by `(host, session_id)`, labels them `basename(cwd)` (suffixing `#2`, `#3` for duplicates on the same host), and sorts: needs you → your turn → working → stale, then most recent first. It sends at most `MAX_SESSIONS` (6):

```json
{"ss":[{"h":"wsl","n":"api","s":1},{"h":"win","n":"Clawdmeter","s":0}]}
```
`s`: 0 working, 1 needs you, 2 your turn, 3 stale. `h` ≤ 8 chars, `n` ≤ 20 chars, ASCII only (all bundled fonts are 0x20–0x7E). Plus `"sn":N`, the total count, when more than 6 exist.

- Sent as **its own write**, on every change (debounced 250 ms) and as a heartbeat every usage poll. Usage writes never carry `ss`.
- `"ss":[]` clears the list. Absence means "no news".
- Firmware hides the list when the last `ss` is older than 3 minutes (daemon gone or feature turned off), so a dead daemon can't leave a frozen "working" list on screen.
- Worst-case size ≈ 6 × 40 B ≈ 250 B, well under the P4's negotiated MTU; `write_limit()` is still checked and the list truncated by count, never by mid-entry cut.

### 7. Firmware placement and attention cue
- New `BoardCaps.has_session_list`, true only on P4 in phase 1 — same reasoning as `has_media_controls`: explicit opt-in rather than a geometry guess, because the list competes with the center rotator, the pomodoro timer, etc.
- On the P4, the list takes over the center rotator's band whenever at least one session exists; the rotator returns when the list is empty. Each row: state dot, `host · project`, state word.
- The list lives in `usage_container`, **not** `usage_group`, so it stays up when usage data is stale (same reason as the media bar), and is raised with `lv_obj_move_foreground()` after the pair/idle groups are built.
- **Attention cue:** when any session newly enters "needs you", the screen border pulses amber (not red — red is the pomodoro's) and boards with sound play the existing chime. A tap on the list acknowledges and stops the pulse until the next new "needs you" transition. The cue never fires for "your turn".

## Risks / Trade-offs

- **Hook field names drift between Claude Code versions** (`notification_type` in particular). Mitigated by the conservative fallback in Decision 2 and by unit tests built from captured real payloads.
- **Native Windows hook shell is unverified.** If hooks run under Git Bash, the bash form works there too; if under cmd/PowerShell, `curl.exe` is needed. Task 1.2 checks this before the installer is written.
- **Hook spawn cost.** `PreToolUse`/`PostToolUse` fire on every tool call; one `curl` process is ~10–30 ms and off the critical path for the model. Acceptable; revisit only if noticeable.
- **Port collision** with another local service: configurable port, and failure disables only this feature.

## Open Questions

1. Which boards beyond the P4, and in what form? Proposed phase 2: square boards (AMOLED-2.16 / LCD-4) show a one-line strip under the combined panel ("1 needs you · 2 working"); phase 3: compact/round boards show a badge. Depends on which hardware you have to test on.
2. Should "your turn" also trigger a (softer) cue, or stay silent? Proposed: silent.
3. Host tags: auto (`hostname`, truncated) or always set explicitly at install? Proposed: installer default `hostname`, overridable with `--host`.
