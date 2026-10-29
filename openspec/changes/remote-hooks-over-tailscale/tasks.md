## 1. Verify assumptions

- [ ] 1.1 (serve is running on `desktop-7r8re97` as of 2026-10-29; the from-the-mini check is still to do.) On the daemon machine, run `tailscale serve --bg --tcp 47123 tcp://127.0.0.1:47123`. From the mini, run `tools/post_fixture_hooks.py` against `desktop-7r8re97.taild6450e.ts.net:47123` (it needs a `--daemon` option too, see 2.3) and confirm the demo rows appear and a wrong token gets `403`.
- [ ] 1.2 With the daemon machine asleep or off the tailnet, time a hook from the mini (`claude -p "hi"` with the hooks installed, against a baseline with none). If each event costs ~1 s, set a shorter remote `timeout` in 2.1 and re-measure.
- [ ] 1.3 Confirm `tailscale serve` survives a reboot of the daemon machine and that the receiver still sees requests as coming from loopback.

## 2. Installer

- [x] 2.1 `tools/install_session_hooks.py --daemon <name>`: sets the host part of `hook_url()` (default `127.0.0.1`), plus a remote-only `timeout` if 1.2 calls for one (the timeout part waits on 1.2).
- [x] 2.2 Tests: the URL uses the given host; re-running with `--daemon` replaces loopback entries rather than adding a second set.
- [x] 2.3 `tools/post_fixture_hooks.py --daemon <name>` so 1.1 can be run from the remote.

## 3. Roll out to the mini

- [ ] 3.1 Tailscale admin console: access rule allowing the mini's tag → `desktop-7r8re97:47123` only.
- [ ] 3.2 On the mini: `python3 install_session_hooks.py --host mini --token <token> --daemon desktop-7r8re97.taild6450e.ts.net`.
- [ ] 3.3 Delete `RemoteForward 47123 127.0.0.1:47123` from `Host mac-mini` in the daemon machine's `~/.ssh/config`.
- [ ] 3.4 Check that a mini session shows on the device with no SSH connection open, and that a job-queue run appears and clears on exit.

## 4. Docs

- [ ] 4.1 `docs/session-status.md`: a "Remote over Tailscale" setup path (serve command, access rule, `--daemon`), with SSH `RemoteForward` kept as the fallback for remotes off the tailnet.
- [ ] 4.2 Privacy section: hook bodies cross the tailnet when this is used; the access rules are part of the boundary.
- [ ] 4.3 Troubleshooting: `tailscale serve status` and `tailscale ping desktop-7r8re97` from the remote.
