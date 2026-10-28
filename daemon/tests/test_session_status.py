#!/usr/bin/env python3
"""Unit tests for daemon/session_status.py (Claude Code session status).

Driven by real, scrubbed hook payloads captured from Claude Code 2.1.220 in
daemon/tests/fixtures/hooks/ (see openspec/changes/add-session-status/tasks.md 1.1/1.1b).

Run: python -m pytest daemon/tests/test_session_status.py -q
"""
import asyncio
import json
from pathlib import Path

import pytest

from daemon import session_status as ss
from daemon.session_status import NEEDS_YOU, STALE, WORKING, YOUR_TURN

FIXTURES = Path(__file__).parent / "fixtures" / "hooks"


def fx(name, **over):
    d = json.loads((FIXTURES / f"{name}.json").read_text())
    d.update(over)
    return d


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def tracker(tmp_path=None, clock=None):
    return ss.SessionTracker(tmp_path / "sessions.json" if tmp_path else None,
                             log=lambda m: None, clock=clock or Clock())


def states(t):
    return [r["s"] for r in t.rows()]


# -- event mapping (real captures) ----------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("UserPromptSubmit", WORKING),
    ("PreToolUse", WORKING),
    ("PostToolUse", WORKING),
    ("PostToolUseFailure", WORKING),          # is_interrupt false in the capture
    ("PermissionRequest", NEEDS_YOU),
    ("PermissionRequest-AskUserQuestion", NEEDS_YOU),
    ("Notification-permission_prompt", NEEDS_YOU),
    ("Notification-idle_prompt", YOUR_TURN),
    ("Stop", YOUR_TURN),
    ("SessionEnd", ss.REMOVE),
])
def test_state_for_captured_events(name, expected):
    assert ss.state_for(fx(name)) == expected


def test_interrupt_is_your_turn():
    assert ss.state_for(fx("PostToolUseFailure", is_interrupt=True)) == YOUR_TURN


def test_unknown_and_informational_notifications_are_ignored():
    for t in ("auth_success", "agent_completed", "quota_auto_resume_fired", "brand_new_type"):
        assert ss.state_for(fx("Notification-idle_prompt", notification_type=t)) is None


def test_untyped_notification_from_older_claude_code_is_needs_you():
    ev = fx("Notification-idle_prompt")
    del ev["notification_type"]
    assert ss.state_for(ev) == NEEDS_YOU


def test_unhooked_events_are_ignored():
    assert ss.state_for({"hook_event_name": "SubagentStop", "session_id": "x"}) is None


# -- the captured interactive session, replayed --------------------------------

def test_interactive_sequence_ends_removed_and_passes_through_needs_you():
    t = tracker()
    seen = []
    for step in json.loads((FIXTURES / "sequence-interactive.json").read_text()):
        t.handle_event("mac", step["body"])
        seen.append(states(t))
    assert [NEEDS_YOU] in seen and [YOUR_TURN] in seen and [WORKING] in seen
    assert seen[-1] == []   # SessionEnd


def test_permission_cycle():
    t = tracker()
    t.handle_event("win", fx("PreToolUse"))
    assert states(t) == [WORKING]
    t.handle_event("win", fx("PermissionRequest"))
    assert states(t) == [NEEDS_YOU]
    t.handle_event("win", fx("Notification-permission_prompt"))   # 6 s later: no change
    assert states(t) == [NEEDS_YOU]
    t.handle_event("win", fx("PostToolUse"))
    assert states(t) == [WORKING]


# -- privacy --------------------------------------------------------------------

def test_prompt_and_tool_fields_never_retained(tmp_path):
    t = tracker(tmp_path)
    secret = "SECRET-PROMPT-TEXT"
    t.handle_event("mac", fx("UserPromptSubmit", prompt=secret))
    t.handle_event("mac", fx("PostToolUse", tool_input={"command": secret},
                             tool_response={"stdout": secret}))
    t.save()
    stored = (tmp_path / "sessions.json").read_text()
    assert secret not in stored
    assert secret not in repr(t.__dict__)
    assert secret.encode() not in t.payload(500)


# -- labels, sorting, expiry ----------------------------------------------------

def test_label_prefers_session_title_and_remembers_it():
    t = tracker()
    t.handle_event("mac", fx("UserPromptSubmit-titled"))
    t.handle_event("mac", fx("PreToolUse"))          # no title on this event
    assert t.rows()[0]["n"] == "capture-test"


def test_label_falls_back_to_cwd_basename_including_windows_paths():
    t = tracker()
    t.handle_event("win", fx("PreToolUse", cwd="C:\\Users\\me\\src\\Clawdmeter"))
    assert t.rows()[0]["n"] == "Clawdmeter"


def test_same_folder_twice_is_deduplicated_per_host():
    c = Clock()
    t = tracker(clock=c)
    t.handle_event("mac", fx("PreToolUse", session_id="a"))
    c.t += 1
    t.handle_event("mac", fx("PreToolUse", session_id="b"))
    t.handle_event("wsl", fx("PreToolUse", session_id="c"))
    names = sorted((r["h"], r["n"]) for r in t.rows())
    assert names == [("mac", "api"), ("mac", "api#2"), ("wsl", "api")]


def test_labels_and_hosts_are_ascii_and_capped():
    t = tracker()
    t.handle_event("my-very-long-host!!", fx("PreToolUse", cwd="/x/caf\u00e9-\u201cproj\u201d-with-a-long-name"))
    r = t.rows()[0]
    assert r["h"] == "my-very-"
    assert r["n"].isascii() and len(r["n"]) <= ss.NAME_MAX
    assert r["n"].startswith("cafe-proj")


def test_sort_by_state_then_first_seen_is_stable_under_churn():
    c = Clock()
    t = tracker(clock=c)
    for sid in ("a", "b", "c"):
        t.handle_event("mac", fx("PreToolUse", session_id=sid, cwd=f"/p/{sid}"))
        c.t += 1
    t.handle_event("mac", fx("PermissionRequest", session_id="c", cwd="/p/c"))
    order = [r["n"] for r in t.rows()]
    assert order == ["c", "a", "b"]
    # Tool-call churn on "b" must not move it ahead of "a".
    for _ in range(5):
        c.t += 1
        t.handle_event("mac", fx("PostToolUse", session_id="b", cwd="/p/b"))
    assert [r["n"] for r in t.rows()] == order


def test_working_goes_stale_then_is_dropped():
    c = Clock()
    t = tracker(clock=c)
    t.handle_event("mac", fx("PreToolUse"))
    c.t += ss.STALE_WORKING + 1
    assert states(t) == [STALE]
    c.t += ss.DROP_AFTER
    assert states(t) == []


def test_your_turn_does_not_go_stale():
    c = Clock()
    t = tracker(clock=c)
    t.handle_event("mac", fx("Stop"))
    c.t += ss.STALE_WORKING + 1
    assert states(t) == [YOUR_TURN]


def test_at_most_six_rows():
    t = tracker()
    for i in range(10):
        t.handle_event("mac", fx("PreToolUse", session_id=str(i), cwd=f"/p/s{i}"))
    assert len(t.rows()) == ss.MAX_SESSIONS


# -- persistence -----------------------------------------------------------------

def test_blocked_session_survives_restart(tmp_path):
    c = Clock()
    t = tracker(tmp_path, c)
    t.handle_event("wsl", fx("PermissionRequest"))
    t2 = tracker(tmp_path, c)
    t2.load()
    assert t2.rows() == [{"h": "wsl", "n": "api", "s": NEEDS_YOU}]


def test_restart_applies_expiry(tmp_path):
    c = Clock()
    tracker(tmp_path, c).handle_event("wsl", fx("Stop"))
    c.t += ss.DROP_AFTER + 1
    t2 = tracker(tmp_path, c)
    t2.load()
    assert t2.rows() == []


def test_corrupt_file_is_ignored(tmp_path):
    (tmp_path / "sessions.json").write_text("{not json")
    t = tracker(tmp_path)
    t.load()
    assert t.rows() == []


# -- payload + pump ---------------------------------------------------------------

def test_payload_shape_and_truncation_by_whole_rows():
    t = tracker()
    for i in range(6):
        t.handle_event("mac", fx("PreToolUse", session_id=str(i), cwd=f"/p/session-{i}"))
    full = t.payload(500)
    assert json.loads(full)["ss"][0] == {"h": "mac", "n": "session-0", "s": 0}
    small = t.payload(80)
    assert len(small) <= 80 and json.loads(small)["ss"]   # valid JSON, fewer rows
    assert t.payload(5) == b'{"ss":[]}'


def test_empty_table_sends_explicit_empty_list():
    assert tracker().payload(100) == b'{"ss":[]}'


class Sink:
    def __init__(self, ok=True):
        self.writes, self.ok = [], ok

    async def __call__(self, data):
        self.writes.append(data)
        return self.ok


def test_pump_sends_on_change_only_then_heartbeats(monkeypatch):
    monkeypatch.setattr(ss, "DEBOUNCE", 0)
    c = Clock()
    t = tracker(clock=c)
    sink = Sink()
    run = lambda: asyncio.run(t.pump(sink, 200))

    assert run() is True and len(sink.writes) == 1          # first send after connect
    assert run() is None                                      # nothing changed
    t.handle_event("mac", fx("PreToolUse"))
    assert run() is True and len(sink.writes) == 2
    for _ in range(5):                                       # tool-call churn
        t.handle_event("mac", fx("PostToolUse"))
        t.handle_event("mac", fx("PreToolUse"))
        assert run() is None
    c.t += ss.HEARTBEAT
    assert run() is True and len(sink.writes) == 3          # heartbeat
    t.on_connect()
    assert run() is True and len(sink.writes) == 4          # new link: resend


def test_pump_retries_after_failed_write(monkeypatch):
    monkeypatch.setattr(ss, "DEBOUNCE", 0)
    t = tracker()
    bad = Sink(ok=False)
    assert asyncio.run(t.pump(bad, 200)) is False
    good = Sink()
    assert asyncio.run(t.pump(good, 200)) is True


def test_pump_notices_staleness_without_any_event(monkeypatch):
    monkeypatch.setattr(ss, "DEBOUNCE", 0)
    c = Clock()
    t = tracker(clock=c)
    sink = Sink()
    t.handle_event("mac", fx("PreToolUse"))
    asyncio.run(t.pump(sink, 200))
    c.t += ss.STALE_WORKING + 1
    assert asyncio.run(t.pump(sink, 200)) is True
    assert json.loads(sink.writes[-1])["ss"][0]["s"] == STALE


# -- request checks ------------------------------------------------------------------

GOOD = {"content-type": "application/json", ss.TOKEN_HEADER: "tok"}


@pytest.mark.parametrize("method,target,headers,expected", [
    ("POST", "/hook/wsl", GOOD, (204, "wsl")),
    ("POST", "/hook/wsl?x=1", GOOD, (204, "wsl")),
    ("GET", "/hook/wsl", GOOD, (405, None)),
    ("POST", "/other", GOOD, (404, None)),
    ("POST", "/hook/", GOOD, (404, None)),
    ("POST", "/hook/wsl", {**GOOD, "origin": "https://evil.example"}, (403, None)),
    ("POST", "/hook/wsl", {**GOOD, "content-type": "text/plain"}, (415, None)),
    ("POST", "/hook/wsl", {**GOOD, ss.TOKEN_HEADER: "wrong"}, (403, None)),
    ("POST", "/hook/wsl", {"content-type": "application/json"}, (403, None)),
])
def test_check_request(method, target, headers, expected):
    assert ss.check_request(method, target, headers, "tok") == expected


# -- receiver end to end ----------------------------------------------------------------

async def _post(port, path, body, headers):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    head = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    writer.write(f"POST {path} HTTP/1.1\r\nHost: x\r\n{head}Content-Length: {len(body)}\r\n\r\n".encode() + body)
    await writer.drain()
    resp = await reader.read()
    writer.close()
    return resp


def test_receiver_accepts_hook_and_rejects_forgery():
    async def go():
        t = tracker()
        rx = ss.Receiver(t, "tok", log=lambda m: None)
        assert await rx.start(0)
        port = rx.server.sockets[0].getsockname()[1]
        body = json.dumps(fx("PermissionRequest")).encode()
        ok = await _post(port, "/hook/devbox", body,
                         {"Content-Type": "application/json", "X-Clawdmeter-Token": "tok"})
        forged = await _post(port, "/hook/devbox", json.dumps(fx("Stop")).encode(),
                             {"Content-Type": "text/plain", "Origin": "https://evil.example"})
        huge = await _post(port, "/hook/devbox", b"x" * (ss.MAX_BODY + 1),
                           {"Content-Type": "application/json", "X-Clawdmeter-Token": "tok"})
        rx.server.close()
        return t, ok, forged, huge

    t, ok, forged, huge = asyncio.run(go())
    assert ok.startswith(b"HTTP/1.1 204") and ok.endswith(b"\r\n\r\n")   # never a body
    assert forged.startswith(b"HTTP/1.1 403")
    assert huge.startswith(b"HTTP/1.1 413")
    assert t.rows() == [{"h": "devbox", "n": "api", "s": NEEDS_YOU}]


def test_port_in_use_disables_only_sessions():
    async def go():
        a = ss.Receiver(tracker(), "tok", log=lambda m: None)
        await a.start(0)
        port = a.server.sockets[0].getsockname()[1]
        msgs = []
        b = ss.Receiver(tracker(), "tok", log=msgs.append)
        started = await b.start(port)
        a.server.close()
        return started, msgs

    started, msgs = asyncio.run(go())
    assert started is False and "disabled" in msgs[0]


# -- config glue ---------------------------------------------------------------------------

def test_start_from_config_off_by_default(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("chime = on\n")
    assert asyncio.run(ss.start_from_config(cfg, log=lambda m: None)) is None


def test_start_from_config_creates_private_token(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("sessions = on   # opt in\nsessions_port = 0\n")

    async def go():
        t = await ss.start_from_config(cfg, log=lambda m: None)
        t.receiver.server.close()
        return t

    assert asyncio.run(go()) is not None
    token_file = tmp_path / "sessions-token"
    assert len(token_file.read_text().strip()) == 32
    assert token_file.stat().st_mode & 0o077 == 0
    assert ss.load_or_create_token(token_file) == token_file.read_text().strip()


# -- daemon integration (Windows loop) ---------------------------------------------------

def _connected_client():
    from unittest.mock import AsyncMock, MagicMock
    client = AsyncMock()
    client.is_connected = True
    client.mtu_size = 247
    client.connect = AsyncMock()
    client.start_notify = AsyncMock()
    return client


def test_windows_loop_sends_session_list_then_drops_dead_link(monkeypatch):
    """No usage token at all, yet the session list still goes out; a failed
    session write trips the zombie break like a failed usage write does."""
    from unittest.mock import MagicMock, patch
    import daemon.claude_usage_daemon_windows as win

    monkeypatch.setattr(ss, "DEBOUNCE", 0)
    t = tracker()
    t.handle_event("wsl", fx("PermissionRequest"))
    client = _connected_client()
    sent = []

    async def write_gatt_char(_uuid, data, response=False):
        sent.append(data)
        if len(sent) > 1:
            raise OSError("peer gone")

    client.write_gatt_char = write_gatt_char

    async def go():
        stop = asyncio.Event()
        device = MagicMock(address="AA:BB")
        with patch.object(win, "BleakClient", return_value=client), \
             patch.object(win, "read_token", return_value=None), \
             patch.object(win, "TICK", 0):
            t.on_connect()
            first = asyncio.ensure_future(win.connect_and_run(device, stop, sessions=t))
            await asyncio.sleep(0.05)
            t.handle_event("wsl", fx("PostToolUse"))   # change → second write fails
            return await asyncio.wait_for(first, 2)

    asyncio.run(go())
    assert json.loads(sent[0]) == {"ss": [{"h": "wsl", "n": "api", "s": NEEDS_YOU}]}
    assert json.loads(sent[1])["ss"][0]["s"] == WORKING
    assert len(sent) == 2   # loop broke out after the failed write
