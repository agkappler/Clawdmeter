#!/usr/bin/env python3
"""Unit tests for tools/install_session_hooks.py (session-status hooks installer).

Run: python -m pytest daemon/tests/test_install_session_hooks.py -q
"""
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "install_session_hooks.py"
_spec = importlib.util.spec_from_file_location("install_session_hooks", _PATH)
inst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inst)

EXISTING = {
    "model": "claude-opus-5-5",
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "lint.sh"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
    },
}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "is_wsl", lambda: False)
    monkeypatch.setattr(inst, "MANAGED_SETTINGS", {})
    (tmp_path / "settings.json").write_text(json.dumps(EXISTING))
    return tmp_path


def run(cfg, *args):
    return inst.main(["--config-dir", str(cfg), *args])


def settings(cfg):
    return json.loads((cfg / "settings.json").read_text())


def ours(s):
    return [(ev, h) for ev, groups in s.get("hooks", {}).items()
            for g in groups for h in g["hooks"] if inst.is_ours(h)]


def test_install_adds_one_http_hook_per_event_and_keeps_existing(cfg):
    assert run(cfg, "--host", "devbox", "--token", "tok") == 0
    s = settings(cfg)
    assert s["model"] == "claude-opus-5-5"
    assert s["hooks"]["PreToolUse"][0] == EXISTING["hooks"]["PreToolUse"][0]
    assert s["hooks"]["Stop"][0] == EXISTING["hooks"]["Stop"][0]
    found = ours(s)
    assert sorted(ev for ev, _ in found) == sorted(inst.EVENTS)
    hook = found[0][1]
    assert hook == {"type": "http", "url": "http://127.0.0.1:47123/hook/devbox", "timeout": 1,
                    "headers": {"X-Clawdmeter-Token": "tok"}}
    assert "SessionStart" not in s["hooks"]   # http hooks don't run there


def test_reinstall_replaces_rather_than_duplicates(cfg):
    run(cfg, "--host", "a", "--token", "old", "--port", "1111")
    run(cfg, "--host", "b", "--token", "new")
    found = ours(settings(cfg))
    assert len(found) == len(inst.EVENTS)
    assert {h["url"] for _, h in found} == {"http://127.0.0.1:47123/hook/b"}
    assert {h["headers"]["X-Clawdmeter-Token"] for _, h in found} == {"new"}


def test_uninstall_restores_original_hooks(cfg):
    run(cfg, "--host", "devbox", "--token", "tok")
    assert run(cfg, "--uninstall") == 0
    assert settings(cfg) == EXISTING


def test_uninstall_removes_empty_hooks_key(tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "MANAGED_SETTINGS", {})
    run(tmp_path, "--host", "x", "--token", "t")
    run(tmp_path, "--uninstall")
    assert settings(tmp_path) == {}


def test_creates_settings_file_and_backup(tmp_path, cfg):
    fresh = tmp_path / "fresh"
    assert run(fresh, "--host", "x", "--token", "t") == 0
    assert len(ours(settings(fresh))) == len(inst.EVENTS)
    run(cfg, "--host", "x", "--token", "t")
    assert json.loads((cfg / "settings.json.clawdmeter-backup").read_text()) == EXISTING


def test_dry_run_writes_nothing(cfg, capsys):
    run(cfg, "--host", "x", "--token", "t", "--dry-run")
    assert settings(cfg) == EXISTING
    assert "hook/x" in capsys.readouterr().out


def test_invalid_json_is_left_alone(cfg):
    (cfg / "settings.json").write_text('{"model": "x",}')
    assert run(cfg, "--host", "x", "--token", "t") == 1
    assert (cfg / "settings.json").read_text() == '{"model": "x",}'


def test_host_tag_matches_daemon_rule():
    from daemon.session_status import host_tag as daemon_tag
    for raw in ("devbox.local", "My Laptop!", "a-very-long-hostname", "wsl"):
        assert inst.host_tag(raw) == daemon_tag(raw)


def test_missing_token_fails_with_guidance(cfg, monkeypatch, capsys):
    monkeypatch.setattr(inst, "find_token", lambda: (None, None))
    assert run(cfg, "--host", "x") == 2
    assert "sessions = on" in capsys.readouterr().err
    assert settings(cfg) == EXISTING


def test_reads_local_token_file(cfg, tmp_path, monkeypatch):
    tok = tmp_path / "sessions-token"
    tok.write_text("abc123\n")
    monkeypatch.setattr(inst, "local_token_file", lambda: tok)
    assert run(cfg, "--host", "x") == 0
    assert {h["headers"]["X-Clawdmeter-Token"] for _, h in ours(settings(cfg))} == {"abc123"}


def test_allowlist_warning(cfg, capsys):
    s = settings(cfg)
    s["allowedHttpHookUrls"] = ["https://hooks.example.com/*"]
    (cfg / "settings.json").write_text(json.dumps(s))
    run(cfg, "--host", "x", "--token", "t")
    assert "allowedHttpHookUrls" in capsys.readouterr().out


def test_allowlist_with_matching_wildcard_is_quiet(cfg, capsys):
    s = settings(cfg)
    s["allowedHttpHookUrls"] = ["http://127.0.0.1:*"]
    (cfg / "settings.json").write_text(json.dumps(s))
    run(cfg, "--host", "x", "--token", "t")
    assert "allowedHttpHookUrls" not in capsys.readouterr().out


def test_remote_prints_forward_line(cfg, capsys):
    run(cfg, "--host", "x", "--token", "t", "--remote", "--port", "47200")
    assert "RemoteForward 47200 127.0.0.1:47200" in capsys.readouterr().out


def test_daemon_name_replaces_loopback_entries(cfg, capsys):
    run(cfg, "--host", "mini", "--token", "t")
    run(cfg, "--host", "mini", "--token", "t", "--daemon", "desk.tail.ts.net", "--remote")
    found = ours(settings(cfg))
    assert len(found) == len(inst.EVENTS)
    assert {h["url"] for _, h in found} == {"http://desk.tail.ts.net:47123/hook/mini"}
    assert "RemoteForward" not in capsys.readouterr().out


def test_wsl_nat_warning(cfg, monkeypatch, capsys):
    monkeypatch.setattr(inst, "is_wsl", lambda: True)
    monkeypatch.setattr(inst, "wsl_networking_mode", lambda: "nat")
    run(cfg, "--token", "t")
    out = capsys.readouterr().out
    assert "networkingMode=mirrored" in out
    assert "hook/wsl" in json.dumps(settings(cfg))   # default host tag inside WSL


def test_installed_hooks_are_accepted_by_the_real_receiver(cfg):
    """The header and URL the installer writes are exactly what the daemon checks."""
    from daemon import session_status as ss
    run(cfg, "--host", "devbox", "--token", "tok")
    hook = ours(settings(cfg))[0][1]
    path = hook["url"].split("47123", 1)[1]
    headers = {k.lower(): v for k, v in hook["headers"].items()}
    headers["content-type"] = "application/json"   # Claude Code sets this itself
    assert ss.check_request("POST", path, headers, "tok") == (204, "devbox")


def test_park_skill_parks_this_session_through_the_installed_hook(cfg):
    import asyncio
    import subprocess
    import sys
    from daemon import session_status as ss

    async def go():
        t = ss.SessionTracker(None, log=lambda m: None)
        t.handle_event("devbox", {"hook_event_name": "Stop", "session_id": "s1", "cwd": "/p/x"})
        rx = ss.Receiver(t, "tok", log=lambda m: None)
        assert await rx.start(0)
        port = rx.server.sockets[0].getsockname()[1]
        run(cfg, "--host", "devbox", "--token", "tok", "--port", str(port))
        script = inst.park_skill_dir(cfg) / "park.py"
        out = await asyncio.to_thread(subprocess.run, [sys.executable, str(script), "s1"],
                                      capture_output=True, text=True)
        rx.server.close()
        return t, out

    t, out = asyncio.run(go())
    assert out.returncode == 0, out.stderr
    assert t.rows() == []
    skill = (inst.park_skill_dir(cfg) / "SKILL.md").read_text()
    assert "${CLAUDE_SESSION_ID}" in skill and "disable-model-invocation: true" in skill


def test_uninstall_removes_park_skill(cfg):
    run(cfg, "--host", "a", "--token", "t")
    assert inst.park_skill_dir(cfg).exists()
    run(cfg, "--uninstall")
    assert not inst.park_skill_dir(cfg).exists()
