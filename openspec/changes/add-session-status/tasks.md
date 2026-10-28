## 1. Verify assumptions (before writing code)

- [x] 1.0 Read the hooks reference (code.claude.com/docs/en/hooks, 2026-10-28). Folded into design.md: built-in `http` hook type replaces `curl`; SessionStart can't use it; `PermissionRequest`, `PostToolUseFailure`, `StopFailure` exist; the full `notification_type` list; `Stop` skips user interrupts; SessionEnd reasons. `session_title` is *not* a documented input.
- [x] 1.1 Captured real payloads via throwaway `http` hooks + a local listener (`claude -p`, macOS, CLI 2.1.220): `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionEnd` arrive with the documented fields, a URL query string survives, and `SessionStart` never fires for an `http` hook. Saved scrubbed as `daemon/tests/fixtures/hooks/*.json`.
- [ ] 1.1b In an **interactive** session (`claude -p` can't produce these), capture `PermissionRequest`, `Notification` (`permission_prompt`, `idle_prompt`, `elicitation_dialog`) and `PostToolUseFailure`. Record which of `PermissionRequest` / `permission_prompt` fires first, and whether `PermissionRequest` fires in auto/acceptEdits modes when no dialog appears (a false alarm). Check a titled session for a `session_title` field. Replace the docs-derived `Notification-*.json` fixtures.
- [ ] 1.2 Confirm the desktop app's Code tab sessions fire the same `~/.claude/settings.json` hooks as the terminal CLI.
- [ ] 1.3 Confirm a dead daemon (connection refused) and a hung one (accepts, never replies) produce no visible noise and at most a `timeout`-long stall, on macOS and native Windows.

## 2. Daemon: `daemon/session_status.py`

- [ ] 2.1 Session table: event → state mapping, `(host, session_id)` keys, `basename(cwd)` labels with `#N` de-dup, state-then-first-seen sort, expiry (30 min working → stale, 12 h → drop) on `time.monotonic()`.
- [ ] 2.2 Persist to `sessions.json` beside the daemon config on each change (wall-clock stamps); reload with expiry applied at startup.
- [ ] 2.3 Asyncio HTTP receiver on `127.0.0.1:<port>`: `POST /hook/<host>` only, 64 KB cap; reject missing `application/json`, any `Origin`, bad `X-Clawdmeter-Token`; `204` empty body; field whitelist on receipt; `_asciify` labels.
- [ ] 2.4 `build_ss_payload(limit)`: ≤ 6 entries, whole-entry truncation to `write_limit()`; `changed()` compares the serialized `(h,n,s)` list with the last one sent.
- [ ] 2.5 Unit tests from the fixtures: mapping (incl. unknown notification types ignored), expiry, persistence round-trip, de-dup, sort stability under tool-call churn, payload size, request rejection rules, prompt/tool fields never retained.
- [ ] 2.6 `tools/post_fixture_hooks.py`: replay fixture sequences into a running receiver (blocked / approved / several hosts / >6 sessions) — the only practical way to drive the P4 UI, which has no screenshot and no serial input.

## 3. Daemon integration

- [ ] 3.1 Config: `sessions = off|on`, `sessions_port` (needs an integer reader; `read_config_flag` only does on/off), `sessions_token`; add all three to `config.example`.
- [ ] 3.2 Import `session_status` with the package/script fallback (tray imports the Windows daemon as `daemon.…`; launchd and `__main__` run it as a script).
- [ ] 3.3 Windows daemon: start receiver + load table in `main()`; add a `sessions_changed` event to `_wait_first`; send `ss` on change (250 ms debounce), on its own 60 s timer, and right after connect; port-in-use logs once and disables only this feature.
- [ ] 3.4 macOS daemon: same, including porting a `_wait_first` equivalent (it currently waits on `refresh_requested` only).
- [ ] 3.5 Ensure usage writes never include `ss` and the `qd` split logic is unaffected.

## 4. Hooks installer: `tools/install_session_hooks.py`

- [ ] 4.1 Merge the `http` hooks (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`) into `settings.json` without disturbing existing hooks; idempotent; `--host`, `--port`, `--token`, `--config-dir` (repeatable; defaults to `$CLAUDE_CONFIG_DIR` or `~/.claude`), `--uninstall`.
- [ ] 4.2 Generate the token on first local install and write it to the daemon config; `--token` reuses it on remotes.
- [ ] 4.3 Warn if `allowedHttpHookUrls` is defined and doesn't match. Inside WSL, detect NAT mode and print how to enable mirrored networking.
- [ ] 4.4 `--remote` prints the `RemoteForward` line to add.

## 5. Firmware: data path

- [ ] 5.1 P4 `ble.cpp`: replace the single `rx_buf`/`data_ready` with the shared copy-out queue, `RX_QUEUE_DEPTH 4`.
- [ ] 5.2 `data.h`: `SessionData { char host[9]; char name[21]; uint8_t state; }`, `MAX_SESSIONS 6`, count, last-`ss` millis.
- [ ] 5.3 `parse_json()`: generic merge branch (no `s`/`ok` → merge `qd` and/or `ss`; `PARSE_ERROR` only if neither); new `PARSE_SESSIONS` result. `ss:[]` clears.
- [ ] 5.4 `main.cpp`: `PARSE_SESSIONS` → `ui_update_sessions()`, never `ui_update()`. Also stop `qd`-only `PARSE_MERGE` from refreshing `last_data_ms` (existing latent bug).
- [ ] 5.5 Sessions accepted before the first usage payload (not gated by `data->valid`); list hidden after 3 min without an `ss` write.

## 6. Firmware: UI (P4 first)

- [ ] 6.1 `BoardCaps.has_session_list` appended last in `board_caps.h`; true in P4 `caps.cpp`; update `template/caps.cpp` and `docs/porting/capability-flags.md`.
- [ ] 6.2 Session list in `usage_container`, raised above pair/idle groups; replaces the rotator band while non-empty; rows `dot host/project state` (ASCII only).
- [ ] 6.3 Title clock shown while the list replaces the rotator; list hidden in the pairing view; idle creature hidden while the list is non-empty.
- [ ] 6.4 Attention cue: amber border pulse on a new "needs you"; stops on tap or when no session is in "needs you".
- [ ] 6.5 Verify on P4 hardware with `tools/post_fixture_hooks.py` driving it (photo/eyeball — no screenshot on this board).
- [ ] 6.6 Build every env to confirm boards without the flag are unchanged.

## 7. End-to-end and docs

- [ ] 7.1 End-to-end on Windows: sessions in native Windows, WSL (mirrored) and over SSH all appear with correct host tags; permission prompt → amber within ~1 s; approve → working; exit → removed; daemon restart keeps a blocked session visible.
- [ ] 7.2 `docs/session-status.md`: per-environment setup (Windows, WSL mirrored, SSH `RemoteForward`, macOS), token handling, known limitations (Esc interrupt, SessionStart, >30 min tool calls, single BLE owner, detached remote sessions), privacy note.
- [ ] 7.3 Update `CLAUDE.md`: wire field, merge-path/freshness fix, P4 RX queue, placement decisions.

## 8. Later phases (separate changes)

- [ ] 8.1 Square boards: one-line strip under the combined panel.
- [ ] 8.2 Compact/round boards: badge.
- [ ] 8.3 Bash and Rust daemons.
- [ ] 8.4 WSL NAT fallback, if mirrored networking proves to be a real obstacle.
