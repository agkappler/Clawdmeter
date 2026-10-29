## Context

Claude Code runs hooks at lifecycle points and hands each one a JSON object with at least `session_id`, `cwd` and `hook_event_name`, plus event-specific fields such as `notification_type` on `Notification`. Hooks run on whatever machine the session runs on. For a user with sessions in native Windows, WSL and over SSH, state therefore originates on three machines, while only one (the Windows host) holds the BLE link to the device.

The Python daemons already send optional, independently-versioned payload fields (`q`, `qd`, `te`/`tu`) and already split an oversize quote into a supplementary write. This change reuses that pattern, but fixes two latent problems in it along the way (Decision 6): merge writes currently refresh the usage freshness stamp, and the P4 has no RX queue.

## Goals / Non-Goals

**Goals**
- Show every live Claude Code session from native Windows/macOS, WSL and SSH remotes on one device, with state: working, needs you, your turn, stale.
- "Needs you" (blocked on a permission or a question) reaches the device within ~1 s.
- Nothing to install on a machine beyond a hooks block in `settings.json` (plus an SSH config line for remotes). No script, no `curl`, no Python on remotes.
- A broken or absent daemon never slows down or disturbs a Claude Code session.
- Opt-in on every side; zero change for anyone who doesn't enable it.

**Non-Goals**
- Acting on sessions from the device (approving prompts, focusing a window). Display only.
- Sessions in claude.ai cloud environments (they don't run local hooks).
- The Bash Linux daemon and the Rust daemon in this change.
- WSL under default NAT networking in v1 (see Decision 4).
- Detecting that an SSH tunnel dropped while a detached (tmux) remote session keeps running; such sessions age into "stale".

## Decisions

### 1. Hooks are Claude Code's built-in `http` hook type
```json
{ "type": "http", "url": "http://127.0.0.1:47123/hook/<host>", "timeout": 1,
  "headers": { "X-Clawdmeter-Token": "<token>" } }
```
Claude Code itself POSTs the event JSON (`Content-Type: application/json`). No process is spawned, there is no shell involved, and the config is identical on Windows, WSL, Linux, macOS and SSH remotes except for the host tag in the path. The host tag goes in the **path**, not a query string: the capture in task 1.1 showed a query string survives, but the path form doesn't depend on that.

**Failure posture** (hooks docs): non-2xx, connection refused and timeout are all non-blocking unless `onFailure: "block"` is set, which we never set. The default `http` timeout is 600 s, so `timeout: 1` bounds a hung (not dead) daemon (measured, task 1.3: a dead daemon costs nothing; a hung one costs up to the timeout per hook). With the daemon down, Claude Code prints one `SessionEnd hook ... failed: connect ECONNREFUSED` line when a session exits; the other events fail silently. The receiver always answers **`204` with an empty body**, never JSON: a 2xx JSON body is read as a hook decision, which matters for `PermissionRequest` in particular.

**SessionStart can't use `http` hooks** (only `command` and `mcp_tool`), which the capture confirmed. A session first appears on its first `UserPromptSubmit`. That's acceptable: a session nobody has typed into has nothing to show.

**Managed allowlists:** if any settings level defines `allowedHttpHookUrls`, the hook only runs when its URL matches. The installer detects that and warns; it never edits managed policy.

**Privacy:** hook JSON includes prompt text, tool inputs and tool responses. It only travels to localhost or through the user's own SSH tunnel. The receiver keeps only `session_id`, `session_title`, `cwd` basename, event name, `notification_type` and `is_interrupt`, and drops everything else on receipt without logging it.

**Alternatives considered:** a `curl` command hook (needs `curl.exe` for PowerShell, `|| true`, and per-platform shell handling); a per-machine filtering script (installs and updates on three platforms). Both are strictly worse.

### 2. Event → state mapping
| Event | State |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure` (`is_interrupt` false) | working |
| `PostToolUseFailure` with `is_interrupt` true | your turn (unverified, see below) |
| `PermissionRequest` | **needs you** |
| `Notification` type `permission_prompt`, `elicitation_dialog`, `elicitation_url_dialog`, `agent_needs_input` | **needs you** |
| `Notification` type `elicitation_complete`, `elicitation_response` | working |
| `Stop`, `StopFailure`, `Notification` type `idle_prompt` | your turn |
| `SessionEnd` (any `reason`; `clear`/`resume` start a new session id) | removed |
| `Notification` types `auth_success`, `agent_completed`, `quota_*`, `plugin_notification`, any unknown type | ignored |
| no event for 30 min while working, 12 h otherwise | stale; dropped after 12 h |

- **`PermissionRequest` is the primary "needs you" signal** (measured in task 1.1b, CLI 2.1.220):
  - It fires within ~50 ms of `PreToolUse`, at the moment the dialog appears. `Notification`/`permission_prompt` follows a consistent **~6 s later**, as a "still waiting" nudge.
  - It does **not** fire in auto mode when the classifier approves, so it gives no false alarm there.
  - It also covers questions: `AskUserQuestion` raised `PermissionRequest` (with `tool_name: "AskUserQuestion"`) plus a `permission_prompt` notification, not `elicitation_dialog`. `elicitation_*` remains for MCP elicitation, which wasn't exercised.
  - `permission_prompt` stays hooked as a cheap backstop. It's idempotent, since the session is already "needs you" by then.
- **Clearing "needs you":** `PostToolUse` clears it after approval. If the approved tool fails, no `PostToolUse` is sent, so `PostToolUseFailure` covers that case. After a denial, the next `PreToolUse` or `Stop` clears it.
- **Unknown notification types are ignored:** the list already has 13 values and grows, and most new ones are informational. Only a `Notification` with no `notification_type` at all (older Claude Code) maps to "needs you".
- **Interrupts:** `Stop` doesn't fire when the user presses Esc. `PostToolUseFailure` carries an `is_interrupt` field (seen `false` in the capture), so an Esc *during a tool call* probably arrives as `is_interrupt: true` and can map to "your turn"; that's untested. An Esc while the model is generating, with no tool running, has no hook, so the session shows "working" until its next event or the 30-minute stale timeout. Accepted, because the user is at that terminal at that moment. A single tool call longer than 30 minutes also reads "stale"; same acceptance.
- **Subagents:** events inside a subagent carry `agent_id` but the parent's `session_id`, so they fold into the parent session.
- **Label:** `session_title` when present, else `basename(cwd)`. The field isn't in the docs, but task 1.1b captured it on `UserPromptSubmit` after `/rename`. It only arrives on prompt events, so the table remembers the last title seen per session.

### 3. Receiver: stdlib asyncio, localhost only, in `main()`
- **About 100 lines on `asyncio.start_server`**, bound to `127.0.0.1`. No new dependency. Accepts only `POST /hook/<host>` with a body ≤ 64 KB, and replies `204` immediately.
- **Request checks**, all of which fail with a bare `403`/`415`:
  - `Content-Type: application/json` is required, which forces a CORS preflight the receiver never answers. That stops web pages from posting "simple" `text/plain` requests to localhost.
  - Any request carrying an `Origin` header is rejected.
  - `X-Clawdmeter-Token` must match the daemon's token. The daemon creates it on first start in a private `sessions-token` file beside its config; the installer copies it into the hook's `headers` as a literal value, so no `allowedEnvVars` is needed. This matters most over `RemoteForward`, where every user on a shared remote can reach the forwarded port.
- **Lifetime:** started from `main()`, not `connect_and_run()`, so the receiver and the session table outlive BLE reconnects. Port comes from config `sessions_port` (default 47123). If the port is taken, the daemon logs once and runs without sessions.
- **Persistence:** the table is written to `sessions.json` next to the daemon config on each change and reloaded at startup with the expiry rules applied. Without this, a daemon restart while a session is blocked hides it until that session's next event, which is the worst possible miss. Expiry uses wall-clock timestamps, the same ones that are persisted.
- **Shared module:** `daemon/session_status.py`, imported with `try: from daemon import session_status` / `except ImportError: import session_status`, because the tray imports the Windows daemon as a package while launchd and `__main__` run each daemon as a script.

### 4. WSL: mirrored networking only in v1
With `networkingMode=mirrored` in `.wslconfig`, WSL's localhost is the Windows host's, and the standard hook works unchanged. Under default NAT it doesn't reach the daemon. v1 requires mirrored mode; the installer detects NAT inside WSL and tells the user how to switch rather than adding a fallback path. A spool-directory fallback was considered and cut as over-engineering for v1. If added later, it must write a temp file and rename it into place so the daemon never reads half-written JSON.

### 5. SSH: reverse port forward
`RemoteForward 47123 127.0.0.1:47123` under the remote's `Host` entry: the remote's hook posts to its own localhost and arrives at the Windows daemon. This needs `AllowTcpForwarding` on the remote (the default). With several SSH connections to one remote open, only the first binds the port and the rest warn harmlessly. It's documented rather than automated; the installer prints the line to add.

### 6. Wire format and transport
**Session table:** keyed by `(host, session_id)`, labelled `session_title` or `basename(cwd)` with `#2`, `#3` for same-host duplicates. Sort order is by state (needs you → your turn → working → stale), then by **first-seen** time, so rows don't reshuffle on every tool call. At most `MAX_SESSIONS` (6) are sent:
```json
{"ss":[{"h":"wsl","n":"api","s":1},{"h":"win","n":"Clawdmeter","s":0}]}
```
`s` is 0 working, 1 needs you, 2 your turn, 3 stale. `h` is at most 8 characters and `n` at most 20, both ASCII-folded with `_asciify` (bundled fonts cover only 0x20–0x7E). `"sn"` carries the real total only when more sessions exist than rows sent (or fit), so the round board's last row can say "+9 more" rather than guess from 6 rows.

**When it's sent:**
- As its own write, and **only when the serialized `(h, n, s)` list differs from the last one sent**, debounced 250 ms. A `PreToolUse`/`PostToolUse` pair on a session that's already working changes nothing on the wire.
- As a heartbeat on its own 60 s timer, independent of the usage poll. Windows skips the usage write when `payload is None` (no token, API outage), and a heartbeat tied to that would let the firmware's timeout hide a live list.
- Immediately after every BLE (re)connect.
- Never inside a usage write. `"ss":[]` clears the list; absence means "no news".
- Truncated by whole entries to fit `write_limit()`. Windows falls back to an MTU of 180 B when negotiation fails, which can hold fewer than 6 rows.

**Firmware merge path (fixes two existing bugs):**
- `parse_json()` gains a generic merge branch: a write without `s`/`ok` merges whichever of `qd` or `ss` it carries and returns `PARSE_ERROR` only if it has neither. The new `PARSE_SESSIONS` result calls a new `ui_update_sessions()`, **never** `ui_update()`.
- `ui_update()` sets `last_data_ms` unconditionally, so today's `qd`-only `PARSE_MERGE` already refreshes usage freshness. With `ss` heartbeats every minute, an expired token would never reach the idle screen. `PARSE_MERGE` for `qd` should stop calling the freshness path too.
- Sessions are stored even before the first usage payload: `ui_update()`'s `if (!data->valid) return;` must not gate them.
- Firmware built before this change returns `PARSE_ERROR` and a nack for an `ss` write. That's harmless, because the daemon doesn't subscribe to TX, but it is a rejection, not a silent ignore.

**P4 RX queue:** the P4's board-local `ble.cpp` has a single `rx_buf` plus a `data_ready` flag, and `ble_get_data()` returns `rx_buf` itself. Back-to-back writes (usage, then `qd`, then `ss`) in one connection event lose all but the last, and `onWrite` can overwrite the buffer mid-parse. Port the shared `ble.cpp` copy-out queue to the P4 at **depth 4**: usage + `qd` + `ss` already fills 3, and the shared drop-oldest policy at depth 3 would drop the usage write first.

**Staleness on the device:** the list hides when no `ss` write has arrived for 3 minutes (the daemon is gone or the feature is off).

### 7. Firmware placement and attention cue
- **Flag:** a new `BoardCaps.has_session_list`, true only on the P4 in phase 1. It's appended last in `board_caps.h`, since all `caps.cpp` files use designated initializers, and also goes into `template/caps.cpp` and `docs/porting/capability-flags.md`. It's an explicit opt-in rather than a geometry guess, the same reasoning as `has_media_controls`.
- **Placement on the P4:** the list takes over the center rotator band whenever at least one session exists, and the rotator returns when the list empties. Each row shows a state dot, `host/project` and a state word. The separator is ASCII `/`, because `·` renders blank.
- **Title clock:** with a rotator present the title clock is suppressed (`!ticker_panel`), so the list would hide the clock most of the time. While the list is showing, the title clock comes back.
- **Views:** the list lives in `usage_container`, not `usage_group`, so it stays visible when usage data is stale, and it's raised with `lv_obj_move_foreground()` after the pair and idle groups are built.
  - Pairing view: the list is hidden, as the media bar is.
  - Idle view: the sleeping creature is hidden while the list is non-empty, since the list sits where the creature is centered.
- **Attention cue:** when a session newly enters "needs you", the screen border pulses amber. It stops on a tap on the list (acknowledged until the next new "needs you" transition) or when no session is in "needs you" any more. "Your turn" never triggers it. The P4 has no pomodoro and no working sound (`sound.cpp` is a no-op), so the cue there is visual only; the color is still amber rather than red so it won't collide with the pomodoro's red flash when square boards get the list in phase 2.

## Risks / Trade-offs

- **Hook field drift between Claude Code versions**, especially `notification_type`. Mitigated by ignoring unknown types and by fixture-based tests.
- **Desktop app sessions are unverified**: the docs don't say whether the desktop app's Code tab loads `~/.claude/settings.json` hooks like the CLI does (task 1.2).
- **Per-tool-call latency:** `PreToolUse`/`PostToolUse` are synchronous round-trips. On localhost that's sub-millisecond, or an instant refusal when the daemon is down. Over an SSH tunnel each one adds a round-trip to the Windows host: fine on a LAN, worth measuring on a slow link.
- **Single BLE owner:** a second daemon (say on a Mac) can't hold the device link because of the firmware's single-owner lock. Sessions it receives are lost unless its hooks point at the owning daemon instead (over SSH or the LAN). Documented, not solved.
- **Port collision:** the port is configurable, and a failure disables only this feature.

## Open Questions

1. Boards after the P4. Proposed phase 2: square boards (AMOLED-2.16 / LCD-4) show a one-line strip under the combined panel ("1 needs you - 2 working"). Phase 3: compact and round boards get a badge.
2. Should "your turn" get a softer cue? Proposed: no.
3. Host tags: the installer defaults to a truncated `hostname`, overridable with `--host`.
