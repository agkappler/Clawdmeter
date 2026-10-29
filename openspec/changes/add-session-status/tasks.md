## 1. Verify assumptions (before writing code)

- [x] 1.0 Read the hooks reference (code.claude.com/docs/en/hooks, 2026-10-28). Folded into design.md: built-in `http` hook type replaces `curl`; SessionStart can't use it; `PermissionRequest`, `PostToolUseFailure`, `StopFailure` exist; the full `notification_type` list; `Stop` skips user interrupts; SessionEnd reasons. `session_title` is *not* a documented input.
- [x] 1.1 Captured real payloads via throwaway `http` hooks + a local listener (`claude -p`, macOS, CLI 2.1.220): `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionEnd` arrive with the documented fields, a URL query string survives, and `SessionStart` never fires for an `http` hook. Saved scrubbed as `daemon/tests/fixtures/hooks/*.json`.
- [x] 1.1b Interactive capture (macOS, CLI 2.1.220, 25 events): `PermissionRequest` fires ~50 ms after `PreToolUse` and ~6 s before `Notification`/`permission_prompt`, and doesn't fire on auto-mode approvals; `AskUserQuestion` raises `PermissionRequest` + `permission_prompt` (not `elicitation_dialog`); `idle_prompt` arrives ~60 s after `Stop`; `PostToolUseFailure` carries `is_interrupt`; `session_title` appears on `UserPromptSubmit` after `/rename`. Fixtures replaced with real, scrubbed captures, plus `sequence-interactive.json` (full timed sequence, for 2.6's replay tool).
- [ ] 1.1c Capture an Esc interrupt during a running tool and confirm `PostToolUseFailure` arrives with `is_interrupt: true` (design §2). Also capture a *denied* permission to confirm the next event clears "needs you".
- [ ] 1.2 Confirm the desktop app's Code tab sessions fire the same `~/.claude/settings.json` hooks as the terminal CLI. The settings docs say the desktop app reads the same settings files as the CLI (and reloads hooks without a restart); still worth one live check. (A self-test from inside a desktop session was refused by the auto-mode safety check as self-modification; do it by hand: install the hooks, open a desktop Code session, send a prompt, and watch the device or the daemon's `Sending: {"ss":...}` log lines.)
- [x] 1.3 Measured with `claude -p` on macOS: dead daemon (connection refused) adds no time, but Claude Code prints one `SessionEnd hook ... failed` line at exit (other events silent); hung daemon (accepts, never replies) costs up to the timeout per hook, so the timeout dropped from 2 s to 1 s (fractional values are accepted too). Native Windows not re-checked; the http hook path is the same code.

## 2. Daemon: `daemon/session_status.py`

- [x] 2.1 Session table: event → state mapping, `(host, session_id)` keys, `session_title` (remembered per session) or `basename(cwd)` labels with `#N` de-dup, state-then-first-seen sort, expiry (30 min working → stale, 12 h → drop). Uses wall-clock time throughout (injectable for tests) rather than `time.monotonic()`, since the same timestamps are persisted; a clock jump at worst ages a session early or late.
- [x] 2.2 Persist to `sessions.json` beside the daemon config on each change (wall-clock stamps); reload with expiry applied at startup.
- [x] 2.3 Asyncio HTTP receiver on `127.0.0.1:<port>`: `POST /hook/<host>` only, 64 KB cap; reject missing `application/json`, any `Origin`, bad `X-Clawdmeter-Token`; `204` empty body; field whitelist on receipt; `_asciify` labels.
- [x] 2.4 `build_ss_payload(limit)`: ≤ 6 entries, whole-entry truncation to `write_limit()`; `changed()` compares the serialized `(h,n,s)` list with the last one sent.
- [x] 2.5 Unit tests from the fixtures: mapping (incl. unknown notification types ignored), expiry, persistence round-trip, de-dup, sort stability under tool-call churn, payload size, request rejection rules, prompt/tool fields never retained.
- [x] 2.6 `tools/post_fixture_hooks.py`: replay fixture sequences into a running receiver (blocked / approved / several hosts / >6 sessions) — the only practical way to drive the P4 UI, which has no screenshot and no serial input.

## 3. Daemon integration

- [x] 3.1 Config: `sessions = off|on`, `sessions_port` (generic `read_config_value` in the module), both in `config.example`. The token is **not** a config key: the daemon creates a private `sessions-token` file (mode 600) beside the config on first start, so it never has to be hand-copied into a file the user edits.
- [x] 3.2 Import `session_status` with the package/script fallback (tray imports the Windows daemon as `daemon.…`; launchd and `__main__` run it as a script).
- [x] 3.3 Windows daemon: start receiver + load table in `main()`; add a `sessions_changed` event to `_wait_first`; send `ss` on change (250 ms debounce), on its own 60 s timer, and right after connect; port-in-use logs once and disables only this feature.
- [x] 3.4 macOS daemon: same, including porting a `_wait_first` equivalent (it currently waits on `refresh_requested` only).
- [x] 3.5 Ensure usage writes never include `ss` and the `qd` split logic is unaffected.

## 4. Hooks installer: `tools/install_session_hooks.py`

- [x] 4.1 Merge the `http` hooks (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`) into `settings.json` without disturbing existing hooks; idempotent; `--host`, `--port`, `--token`, `--config-dir` (repeatable; defaults to `$CLAUDE_CONFIG_DIR` or `~/.claude`), `--uninstall`.
- [x] 4.2 Read the token from the local daemon's `sessions-token` file; `--token` passes it explicitly on remotes.
- [x] 4.3 Warn if `allowedHttpHookUrls` is defined and doesn't match. Inside WSL, detect NAT mode and print how to enable mirrored networking.
- [x] 4.4 `--remote` prints the `RemoteForward` line to add. Also: `--dry-run`, a `.clawdmeter-backup` copy before writing, refusal to touch an invalid `settings.json`, and stdlib-only / Python 3.8+ so it can be copied to a remote. Verified end to end: installer-written hooks in a scratch project + a real `claude -p` session produced the expected `ss` writes on a test receiver.

## 5. Firmware: data path

- [x] 5.1 P4 `ble.cpp`: replaced the single `rx_buf`/`data_ready` with the shared copy-out queue at `RX_QUEUE_DEPTH 4`. Shared `ble.cpp` raised from 3 to 4 too, since every board now gets usage + quote + session writes back to back.
- [x] 5.2 `data.h`: `SessionData { char host[9]; char name[21]; uint8_t state; }`, `MAX_SESSIONS 6`, count, last-`ss` millis.
- [x] 5.3 `parse_json()`: generic merge branch (no `s`/`ok` → merge `qd` and/or `ss`; `PARSE_ERROR` only if neither). Instead of a separate `PARSE_SESSIONS` result, a `parse_parts_t` out-param says which parts a write carried, since one write may carry both. `ss:[]` clears.
- [x] 5.4 `main.cpp`: merge writes call `ui_update_quote_of_day()` / `ui_update_sessions()`, never `ui_update()`. This fixes two existing bugs: a `qd`-only write marked stale usage as fresh, and re-anchored the clock to the last usage payload's epoch, so the clock jumped back.
- [x] 5.5 Sessions accepted before the first usage payload (not gated by `data->valid`); `ui_update_sessions()` records `sess_last_ms` for the 3-minute hide, which the list widget applies in 6.2.

## 6. Firmware: UI (P4 first)

- [x] 6.1 `BoardCaps.has_session_list` appended last in `board_caps.h`; true in P4 `caps.cpp`; update `template/caps.cpp` and `docs/porting/capability-flags.md`.
- [x] 6.2 Session list in `usage_container`, created after pair/idle so it's tappable on the idle screen; takes the whole center band (436–830 on the P4, 6 × 53px rows) and hides the rotator while non-empty and live (an `ss` write within 3 min). Rows are dot, host (dim), name, state word, as separate labels rather than one `host/project` string, since LVGL recolor syntax would misread the `#` in names like `api#2`.
- [x] 6.3 Title clock shown while the list replaces the rotator; list hidden in the pairing view; idle creature hidden while the list is non-empty.
- [x] 6.4 Attention cue: a 12px amber border on `lv_layer_top()` (not clickable), blinking at 600 ms, armed when a session newly enters "needs you"; stops on a tap on the list or when none is left in "needs you".
- [ ] 6.5 Verify on P4 hardware with `tools/post_fixture_hooks.py` driving it (photo/eyeball — no screenshot on this board).
- [x] 6.6 Build every env to confirm boards without the flag are unchanged. All 9 envs build.

## 6b. Round board (LCD-1.85B) — the user's actual board

- [x] 6b.1 `has_session_list` on `waveshare_lcd_185b`; `L.sess_round` picks the round style.
- [x] 6b.2 Badge in the ring's center status line (most urgent state's count in its color, plus `+N` others), circular bezel pulse, tap-to-open full-screen list (6 rows centered, auto-close after 10 s).
- [x] 6b.3 Verified on hardware by screenshot (badge, both pulse phases, 4- and 6-row lists, long-name truncation) using a temporary auto-open build, then the normal build.
- [x] 6b.4 A real finger tap opens and closes the list, and acknowledges the pulse (confirmed by the user on hardware, 2026-10-28).
- [x] 6b.5 User request: make the session screen the default on the round board. Replaced the tap-to-open list with a home screen (thin ring with Current/Weekly percentages top and bottom, 5 rows in the middle, "+N more" from a new `"sn"` total sent by the daemon); a tap peeks at the classic view for 10 s; no sessions means the classic view as before. Verified by screenshot for 0, 4, 5 and 13 sessions.
- [ ] 6b.6 A real finger tap on the home screen shows the classic view, and it returns after 10 s or another tap.

## 7. End-to-end and docs

- [ ] 7.1 End-to-end on Windows: sessions in native Windows, WSL (mirrored) and over SSH all appear with correct host tags; permission prompt → amber within ~1 s; approve → working; exit → removed; daemon restart keeps a blocked session visible.
- [x] 7.2 `docs/session-status.md`: per-environment setup (Windows, WSL mirrored, SSH `RemoteForward`, macOS), token handling, known limitations (Esc interrupt, SessionStart, >30 min tool calls, single BLE owner, detached remote sessions), privacy note.
- [x] 7.3 Update `CLAUDE.md`: wire field, merge-path/freshness fix, P4 RX queue, placement decisions.

## 8. Later phases (separate changes)

- [ ] 8.1 Square boards: one-line strip under the combined panel.
- [ ] 8.2 Compact/round boards: badge.
- [ ] 8.3 Bash and Rust daemons.
- [ ] 8.4 WSL NAT fallback, if mirrored networking proves to be a real obstacle.
