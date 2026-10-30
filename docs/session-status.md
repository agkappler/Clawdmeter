# Claude Code session status

Shows your Claude Code sessions on the device: which are **working**, which
**need you** (a permission prompt or a question is waiting), which are waiting
for your next prompt (**your turn**), which have gone quiet (**stale**), and
which you've set aside with `/park` (**parked**). Colors: **red** needs you,
**gold** your turn, **teal** working, gray stale, dark gray parked.
A session that just finished its turn also shows as **needs you** for its first
2 minutes, then drops to your turn: a finished turn often means there's
something for you to look at.
When a session newly needs you, the screen border blinks red until you tap
the list or answer the prompt.

It covers sessions on the machine running the daemon, in WSL, and on SSH
remotes, all on one screen. The machine each one runs on is shown next to its
name.

> **Boards:**
> - **Round LCD-1.85B:** while any session exists, the session screen becomes
>   the main view. A thin ring shows usage (Current on top, Weekly on the
>   bottom), with each percentage and reset time just inside it, and up to 5
>   sessions in the middle ("+N more" when there are more). Tap to see the
>   classic usage screen for 10 seconds; its center line then reads, for
>   example, "1 needs you +3". With no sessions, the classic screen is the
>   default as before. The attention pulse is a ring around the bezel.
> - **ESP32-P4 Touch LCD-5:** the list fills the band between the usage panels
>   and the media buttons.
> - Other boards ignore the data for now.
>
> **Daemons:** the Python daemons (Windows tray, macOS/Linux). The Bash and Rust
> daemons don't support it.

## How it works

```
Claude Code session ──http hook──▶ daemon receiver (127.0.0.1:47123) ──BLE "ss" write──▶ device
   (any machine)                    session table, saved to disk
```

- Claude Code's built-in `http` hooks POST each session event (prompt sent,
  tool running, permission needed, turn finished, session ended) to the daemon.
  No script runs, so the hooks are identical on every OS.
- The daemon keeps a small table of sessions and sends the device a compact
  list when it changes, plus every 60 seconds.
- WSL reaches the Windows daemon through mirrored networking. An SSH remote
  reaches it through a reverse tunnel (`RemoteForward`).

## Setup

### 1. Turn it on in the daemon

Add this to the daemon config, then restart the daemon:

| OS | Config file | Restart |
|---|---|---|
| Windows | `%LOCALAPPDATA%\Clawdmeter\config` | Quit from the tray icon and start it again |
| macOS | `~/.config/claude-usage-monitor/config` | `launchctl kickstart -k gui/$(id -u)/com.user.claude-usage-daemon` |
| Linux (Python daemon) | `~/.config/claude-usage-monitor/config` | restart however you run it |

```ini
sessions = on
# sessions_port = 47123   # only if something else uses this port
# your_turn_alert = 2     # minutes a finished turn shows as "needs you"; 0 turns it off
```

On start the daemon logs `Sessions: listening on 127.0.0.1:47123` and creates
a **`sessions-token`** file next to the config. Hooks must send that secret;
the installer reads it for you on this machine.

### 2. Install the hooks on every machine you use Claude Code on

Use `tools/install_session_hooks.py`. It needs only Python 3.8+ and the
standard library, so you can copy that single file to any machine.

**On the daemon machine** (native Windows or macOS):

```bash
python3 tools/install_session_hooks.py
```

**In WSL** (with the daemon on Windows). This needs WSL's mirrored networking:
add `networkingMode=mirrored` under `[wsl2]` in `%UserProfile%\.wslconfig`,
then run `wsl --shutdown`. Then, inside WSL:

```bash
python3 tools/install_session_hooks.py
```

It finds the Windows daemon's token by itself, tags sessions `wsl`, and warns
if networking isn't mirrored.

**On an SSH remote.** Copy the installer over, then run it there with the token
from the daemon machine's `sessions-token` file:

```bash
python3 install_session_hooks.py --host devbox --token <token> --remote
```

Then, on the daemon machine, add the line it prints under that remote's `Host`
entry in `~/.ssh/config` and reconnect:

```
Host devbox
    RemoteForward 47123 127.0.0.1:47123
```

The tunnel is the only route. Claude Code refuses `http` hooks to any address
other than loopback (a LAN or Tailscale `100.x` address is "blocked: private
address"), and listing the URL in `allowedHttpHookUrls` doesn't lift that. So a
remote can't post straight to the daemon machine's address, even on the same
tailnet. If you SSH over Tailscale, the tunnel already runs inside it.

Useful options:

- `--host` sets the short machine tag (8 characters at most).
- `--config-dir` installs into another Claude config dir; it can be repeated.
  The default is `$CLAUDE_CONFIG_DIR` or `~/.claude`.
- `--dry-run` shows the result without writing anything.
- `--uninstall` removes the hooks.
- The installer saves `settings.json.clawdmeter-backup` before it writes, and
  leaves your other hooks alone.

Claude Code picks up the new hooks without a restart.

<details>
<summary>Installing by hand</summary>

Add one entry like this to `settings.json` for each of these events:
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PermissionRequest`, `Notification`, `Stop`, `StopFailure`, `SessionEnd`.

```json
{
  "hooks": {
    "PermissionRequest": [
      { "hooks": [ { "type": "http", "url": "http://127.0.0.1:47123/hook/devbox", "timeout": 1,
                     "headers": { "X-Clawdmeter-Token": "<token>" } } ] }
    ]
  }
}
```

Don't add `SessionStart`: it doesn't support `http` hooks. Never set
`onFailure: "block"`.
</details>

### 3. Check it

Start a Claude Code session and send a prompt; it should appear on the device
within a second or two. To test the device without real sessions, replay
captured events:

```bash
python3 tools/post_fixture_hooks.py demo    # 5 sessions across hosts, one needing you
python3 tools/post_fixture_hooks.py clear   # remove them
```

## Removing a session from the list

Exiting a session with `/exit` or Ctrl+D removes its row. To remove rows
yourself, run this on the daemon machine:

```bash
python tools/sessions.py              # numbered list, in the device's order
python tools/sessions.py end 2        # remove row 2 (several numbers work too)
python tools/sessions.py end 626bc8c5 # or by session id prefix
```

Use it for rows left behind by a restart or a closed window. It only removes
the row: the session's next event adds it back, and that includes Claude Code's
idle reminder about a minute after a turn ends.

To step away from a live session, type `/park` in it instead. The installer
adds this skill alongside the hooks on every machine. The session's row turns
dark gray, reads "parked" and moves below the active sessions (only stale
ones sort after it), so it drops off early when there are more sessions than
fit. It stays that way
until your next prompt there; the events in between (the `/park` turn itself,
the idle reminder) are ignored. It runs one short command, so it costs one
quick turn. Firmware from before 2026-10-29 doesn't know this state and leaves
parked rows out.

## Troubleshooting

**Nothing appears**
- Check that the daemon log has `Sessions: listening on 127.0.0.1:47123`. If it
  says `can't listen ... session status disabled`, another program has the
  port: set `sessions_port` to a free one and re-run the installer with
  `--port`.
- On Windows, Hyper-V, WSL or Docker can reserve whole port ranges. List them
  with `netsh interface ipv4 show excludedportrange protocol=tcp` and pick a
  port outside them.
- `tools/post_fixture_hooks.py demo` answering `403` means a wrong token.
  Re-run the installer, since the daemon makes a new token if its file was
  deleted.
- If the installer warned about `allowedHttpHookUrls`, an organization or user
  setting is blocking these hooks.

**One machine's sessions are missing**
- **WSL:** check that mirrored networking is on (`wslinfo --networking-mode`).
- **SSH:** look for `Warning: remote port forwarding failed for listen port
  47123` when you connect. That means something on the remote already uses the
  port, or another SSH connection to that machine already holds the tunnel,
  which is fine. Without the tunnel, that remote's hooks go nowhere.

**"SessionEnd hook … failed: connect ECONNREFUSED" when a session exits.**
The daemon isn't running or isn't listening (or the SSH tunnel is down). It's
harmless: hook failures never block Claude Code.

**Desktop app sessions.** The desktop app reads the same `settings.json` as
the CLI, so its sessions should appear too. If they don't, check that you
installed into the config dir the app uses.

## Known limitations

- A session first appears on its first prompt, not when it starts, because
  `SessionStart` can't use `http` hooks.
- **Esc while Claude is generating** (no tool running) sends no event. The
  session shows "working" until its next event, or reads "stale" after 30
  minutes. Esc during a tool is reported and shows as "your turn".
- A single tool call longer than 30 minutes also reads "stale" until it finishes.
- A remote session that keeps running after you disconnect (in tmux, say)
  can't report back. It reads "stale", then disappears after 12 hours.
- Only one daemon can own the device's Bluetooth link. Point every machine's
  hooks at that daemon, using SSH or WSL as above; sessions sent to a second
  daemon never reach the device.
- The device shows up to 6 sessions, the ones that need you first, then your turn, working, parked and stale.
- The session list on/off setting and the port are read once, when the daemon starts.

## Privacy and security

- Hook events include your prompt text and tool inputs and outputs. They only
  go to `127.0.0.1`, or through your own SSH tunnel. The daemon keeps only the
  session id, session title, folder name, event name and notification type,
  and drops everything else as it arrives. Nothing else is logged or saved.
- The receiver listens on `127.0.0.1` only. It accepts only JSON requests with
  the right `X-Clawdmeter-Token`, and rejects anything a web page sends (any
  request with an `Origin` header).
- It always answers with an empty `204`, so it can never answer a permission
  prompt on your behalf.
