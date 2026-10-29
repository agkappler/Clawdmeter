## Why

A remote machine (today, the Mac mini) reaches the session receiver through `RemoteForward 47123 127.0.0.1:47123` in the daemon machine's `~/.ssh/config`. That tunnel exists only while an SSH connection from the daemon machine is open, which causes two problems:

- **Missed sessions.** Sessions on the mini that run without an open SSH connection (job-queue runs, anything left in tmux after disconnecting) never reach the daemon. They are missing, or read "stale" and then drop.
- **Port squatting.** While the tunnel is down, the mini's hooks still post to its own `127.0.0.1:47123`. Any process there that binds the port first receives full hook bodies (prompt text, tool input and output) plus the token. SSH only warns (`remote port forwarding failed`) and carries on.

Every machine involved is already on the tailnet (`taild6450e.ts.net`), so the mini can post straight to the daemon machine.

## What Changes

- **Daemon machine exposes the receiver to the tailnet with `tailscale serve`**, not by changing the receiver. `tailscale serve --bg --tcp 47123 tcp://127.0.0.1:47123` relays tailnet TCP to the loopback listener. The receiver keeps binding `127.0.0.1` only, so nothing on the LAN can reach it, and its token, `Origin` and content-type checks are unchanged. It doesn't check the `Host` header, so relayed requests are accepted as they are. No Funnel: the port must never be reachable from the internet.
- **Tailscale access rules allow only remote → daemon machine on TCP 47123.** The mini is a tagged device, so the rule names its tag as the source and the daemon machine (`desktop-7r8re97`) as the only destination.
- **The installer can point hooks at another machine.** `tools/install_session_hooks.py` gains `--daemon <name>` (a MagicDNS name, default `127.0.0.1`), which sets the hook URL host. `is_ours()` already matches entries by their token header, so re-running the installer replaces the old loopback entries cleanly.
- **The SSH `RemoteForward` line is retired** for remotes on the tailnet. It stays documented for remotes that aren't.
- **Docs** (`docs/session-status.md`): a Tailscale section, and a revised privacy note that says hook bodies cross the tailnet (WireGuard-encrypted) rather than an SSH tunnel.

## Risks and trade-offs

- **An offline daemon machine may cost the hook timeout per event.** A refused loopback connection fails instantly; a sleeping peer on the tailnet may just not answer, so every hook on the mini waits its full 1 s `timeout`, on every tool call. Measure this before relying on it (task 1.2). If it's real, the fallback is a short `timeout` (fractional values are accepted, e.g. 0.3) for remote installs only.
- **Wider reach than loopback.** Any tailnet device the access rules allow can reach the port. The token is still required, but the access rules become part of the security boundary and need to stay narrow.
- **More rows on the device.** Job-queue sessions on the mini will now appear. This is mostly the point, but the device shows at most 6 rows. If it gets noisy, the remote can be installed into a separate `--config-dir` that excludes the job runner's config, or the job runner's config can be left without the hooks.
- **The daemon machine's tailnet name has to stay put.** Hooks hardcode `desktop-7r8re97.taild6450e.ts.net`. Renaming the machine, or moving the daemon to another machine, means re-running the installer on every remote.

## Impact

- **Host, modified:** `tools/install_session_hooks.py` (`--daemon`), its tests, `docs/session-status.md`.
- **No daemon or firmware changes.**
- **Ops, one-time:** the `tailscale serve` command on the daemon machine (persists across reboots with `--bg`), one access-rule edit in the Tailscale admin console, re-running the installer on the mini, and deleting the `RemoteForward` line.
