## 1. Verify assumptions (before writing code)

- [ ] 1.1 Capture real hook payloads for every event in Decision 2 (a temporary hook that `tee`s stdin to a file) on macOS/Linux; confirm field names, especially `notification_type` values for permission prompts, questions and idle. Save them as test fixtures under `daemon/tests/fixtures/hooks/`.
- [ ] 1.2 On native Windows: confirm which shell runs hook commands, and that `curl.exe ... --data-binary @-` forwards stdin intact. Confirm the desktop app's Code tab sessions fire the same `settings.json` hooks as the terminal CLI.
- [ ] 1.3 Confirm a failing hook command (daemon down) produces no visible noise in a session on each platform.

## 2. Daemon: session receiver (`daemon/session_status.py`)

- [ ] 2.1 Session table: event → state mapping, `(host, session_id)` keys, labels with `#N` de-dup, sort order, age expiry (30 min working → stale, 12 h → drop).
- [ ] 2.2 Asyncio HTTP receiver on `127.0.0.1:<port>`: `POST /hook?h=<tag>`, 64 KB cap, `204` reply, field whitelist on receipt, ASCII folding of labels.
- [ ] 2.3 Spool-dir drain for the WSL fallback.
- [ ] 2.4 `build_ss_payload(limit)`: cap 6 entries + `sn`, respect `write_limit()`.
- [ ] 2.5 Unit tests from the 1.1 fixtures: mapping, expiry, de-dup, payload size, prompt text never retained.

## 3. Daemon integration

- [ ] 3.1 Config keys `sessions = off|on`, `sessions_port = 47123` in both daemons and `config.example`.
- [ ] 3.2 Windows daemon: start receiver in its event loop; add a `sessions_changed` event to `_wait_first` so a change writes within the 250 ms debounce; send `ss` heartbeat each poll; port-in-use logs once and disables only this feature.
- [ ] 3.3 macOS daemon: same wiring.
- [ ] 3.4 Ensure usage writes never include `ss`, and the `qd` split logic is unaffected.

## 4. Hooks installer (`tools/install_session_hooks.py`)

- [ ] 4.1 Merge the hooks block into `~/.claude/settings.json` without disturbing existing hooks; idempotent; `--host`, `--port`, `--uninstall`.
- [ ] 4.2 Platform forms: bash `curl ... || true`, Windows `curl.exe`, WSL auto-detect (mirrored → standard hook; NAT → spool-file hook with the Windows path resolved at install time).
- [ ] 4.3 Print the `RemoteForward` line to add when run with `--remote`.

## 5. Firmware: data path

- [ ] 5.1 `data.h`: `SessionData { char host[9]; char name[21]; uint8_t state; }`, `MAX_SESSIONS 6`, count, total, last-update millis.
- [ ] 5.2 `parse_json()`: an `ss`-only write merges sessions without touching usage or its freshness stamp; `ss:[]` clears.
- [ ] 5.3 Hide list after 3 min without an `ss` write.

## 6. Firmware: UI (P4 first)

- [ ] 6.1 `BoardCaps.has_session_list`; true in P4 `caps.cpp` only.
- [ ] 6.2 Session list widget in `usage_container`, raised above pair/idle groups; replaces the center rotator band while non-empty, rotator returns when empty.
- [ ] 6.3 Attention cue: amber border pulse + chime on sound boards on a new "needs you"; tap to acknowledge.
- [ ] 6.4 Verify on P4 hardware (no `screenshot.sh` on this board — photo or eyeball).
- [ ] 6.5 Build every env to confirm boards without the flag are unchanged.

## 7. End-to-end and docs

- [ ] 7.1 End-to-end on Windows: sessions in native Windows, WSL and over SSH all appear with correct host tags; permission prompt → amber within ~1 s; approve → working; exit → removed.
- [ ] 7.2 `docs/session-status.md`: per-environment setup (Windows, WSL mirrored vs NAT, SSH `RemoteForward`, macOS), troubleshooting, privacy note.
- [ ] 7.3 Update `CLAUDE.md` with the wire field and placement decisions.

## 8. Later phases (separate changes)

- [ ] 8.1 Square boards: one-line strip under the combined panel.
- [ ] 8.2 Compact/round boards: badge.
- [ ] 8.3 Bash and Rust daemons.
