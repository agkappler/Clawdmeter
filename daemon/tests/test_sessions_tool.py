#!/usr/bin/env python3
"""Unit tests for tools/sessions.py (list and end daemon sessions).

Run: python -m pytest daemon/tests/test_sessions_tool.py -q
"""
import asyncio
import importlib.util
import json
import time
from pathlib import Path

import pytest

from daemon import session_status as ss

_PATH = Path(__file__).resolve().parents[2] / "tools" / "sessions.py"
_spec = importlib.util.spec_from_file_location("sessions_tool", _PATH)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def _entry(host, sid, state=ss.YOUR_TURN, offset=0.0):
    t = time.time() - 100 + offset
    return ss.Entry(host, sid, "proj", None, state, t, t)


@pytest.fixture
def base(tmp_path):
    entries = [_entry("win", "aaaa1111"), _entry("mini", "bbbb2222", offset=1),
               _entry("wsl", "aaaa3333", ss.NEEDS_YOU, offset=2)]
    (tmp_path / "sessions.json").write_text(json.dumps([e.__dict__ for e in entries]))
    return tmp_path


def test_lists_in_device_order(base):
    sessions = tool.load_sessions(base)
    assert [(e.host, s) for e, _, s in sessions] == [
        ("wsl", ss.NEEDS_YOU), ("win", ss.YOUR_TURN), ("mini", ss.YOUR_TURN)]


def test_resolve_by_row_number_or_unique_id_prefix(base):
    sessions = tool.load_sessions(base)
    assert tool.resolve(sessions, "1")[0].sid == "aaaa3333"
    assert tool.resolve(sessions, "bbbb")[0].sid == "bbbb2222"
    with pytest.raises(ValueError, match="more than one"):
        tool.resolve(sessions, "aaaa")
    with pytest.raises(ValueError, match="no session"):
        tool.resolve(sessions, "9")


def test_end_removes_the_session_from_a_live_receiver():
    async def run():
        t = ss.SessionTracker(None, log=lambda m: None)
        t.handle_event("mini", {"hook_event_name": "Stop", "session_id": "s1", "cwd": "/p/x"})
        receiver = ss.Receiver(t, "tok", log=lambda m: None)
        assert await receiver.start(0)
        port = receiver.server.sockets[0].getsockname()[1]
        await asyncio.to_thread(tool.end_session, port, "tok", "mini", "s1")
        receiver.server.close()
        return t.rows()

    assert asyncio.run(run()) == []
