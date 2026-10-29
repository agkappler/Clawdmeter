"""Claude Code session status for the device.

Claude Code's built-in `http` hooks POST each lifecycle event (prompt submitted,
tool about to run, permission needed, turn finished, session ended, ...) to a
small receiver here. This module turns those events into a table of sessions —
working / needs you / your turn / stale — and builds the compact `"ss"` payload
the daemons send to the firmware as its own BLE write.

It is shared by the macOS/Linux and Windows daemons and has no BLE or platform
code of its own: the daemon hands `pump()` its write function and write limit.
See openspec/changes/add-session-status/design.md for the decisions behind it.

Privacy: hook bodies carry prompt text, tool inputs and tool output. Only the
fields in `_whitelist()` are ever kept; the rest is dropped on receipt and never
logged or persisted.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Awaitable, Callable

DEFAULT_PORT = 47123
MAX_SESSIONS = 6          # rows the firmware has room for
HOST_MAX = 8              # chars, matches SessionData.host on the device
NAME_MAX = 20             # chars, matches SessionData.name on the device
DEBOUNCE = 0.25           # s: coalesce bursts (PreToolUse + PermissionRequest)
HEARTBEAT = 60            # s: resend an unchanged list so the device knows we're alive
STALE_WORKING = 30 * 60   # s: "working" with no event this long reads as stale
DROP_AFTER = 12 * 3600    # s: forget a session with no event this long
PERSIST_EVERY = 60        # s: also persist timestamp-only changes this often
MAX_BODY = 64 * 1024      # bytes: hook bodies include tool output; cap it
READ_TIMEOUT = 5          # s: per request
TOKEN_HEADER = "x-clawdmeter-token"

# Wire values for "s". Order of the sort is by PRIORITY, not by these numbers.
WORKING, NEEDS_YOU, YOUR_TURN, STALE = 0, 1, 2, 3
PRIORITY = {NEEDS_YOU: 0, YOUR_TURN: 1, WORKING: 2, STALE: 3}
REMOVE = -1

# notification_type → state. Anything not listed is ignored: the list grows
# with Claude Code releases and most new types are informational.
_NOTIFICATION_STATES = {
    "permission_prompt": NEEDS_YOU,       # ~6 s after PermissionRequest: a backstop
    "elicitation_dialog": NEEDS_YOU,      # MCP elicitation
    "elicitation_url_dialog": NEEDS_YOU,
    "agent_needs_input": NEEDS_YOU,
    "elicitation_complete": WORKING,
    "elicitation_response": WORKING,
    "idle_prompt": YOUR_TURN,             # ~60 s after Stop
}
_EVENT_STATES = {
    "UserPromptSubmit": WORKING,
    "PreToolUse": WORKING,
    "PostToolUse": WORKING,
    # Fires as the permission dialog (or an AskUserQuestion) appears, and not
    # when auto mode or an allow rule approves — the primary "needs you" signal.
    "PermissionRequest": NEEDS_YOU,
    "Stop": YOUR_TURN,
    "StopFailure": YOUR_TURN,
    "SessionEnd": REMOVE,
}

_HOST_RE = re.compile(r"[^A-Za-z0-9_-]")

Log = Callable[[str], None]
Writer = Callable[[bytes], Awaitable[bool]]


def state_for(event: dict) -> int | None:
    """Map one hook event to a state, REMOVE, or None (ignore it)."""
    name = event.get("hook_event_name")
    if name == "Notification":
        ntype = event.get("notification_type")
        if ntype is None:
            return NEEDS_YOU   # older Claude Code without types: a false alarm beats a miss
        return _NOTIFICATION_STATES.get(ntype)
    if name == "PostToolUseFailure":
        # An Esc during a tool arrives here with is_interrupt true; the turn is
        # over and no Stop follows, so it's the user's turn.
        return YOUR_TURN if event.get("is_interrupt") else WORKING
    return _EVENT_STATES.get(name)


def ascii_fold(text: str, limit: int) -> str:
    """Fold to printable ASCII (the device fonts cover only 0x20-0x7E) and cap length."""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode()
    text = "".join(c for c in text if " " <= c <= "~").strip()
    return text[:limit]


def host_tag(raw: str) -> str:
    return _HOST_RE.sub("", raw)[:HOST_MAX] or "?"


def _basename(cwd: str) -> str:
    # Hook bodies come from Windows and POSIX alike; split on either separator.
    return re.split(r"[\\/]", str(cwd).rstrip("\\/"))[-1] if cwd else ""


def _whitelist(event: dict) -> dict:
    """The only hook fields this module ever keeps."""
    return {
        "session_id": str(event.get("session_id") or ""),
        "event": event.get("hook_event_name"),
        "cwd_name": _basename(event.get("cwd") or ""),
        "title": event.get("session_title"),
    }


@dataclass
class Entry:
    host: str
    sid: str
    cwd_name: str
    title: str | None
    state: int
    first_seen: float   # wall clock, so it survives a restart
    updated: float


class SessionTracker:
    """The session table, its persistence, and the "ss" payload."""

    def __init__(self, persist_path: Path | None = None, log: Log = print,
                 clock: Callable[[], float] = time.time) -> None:
        self._entries: dict[tuple[str, str], Entry] = {}
        self._path = persist_path
        self._log = log
        self._clock = clock
        self._last_visible: list | None = None
        self._last_change = 0.0
        self._last_persist = 0.0
        self._last_sent: bytes | None = None
        self._last_sent_at = 0.0
        self.changed = asyncio.Event()   # set when the visible list changed

    # -- table ---------------------------------------------------------------

    def handle_event(self, host: str, event: dict) -> bool:
        """Apply one hook event. Returns True if the visible list changed."""
        state = state_for(event)
        fields = _whitelist(event)
        sid = fields["session_id"]
        if state is None or not sid:
            return False
        key = (host_tag(host), sid)
        now = self._clock()
        if state == REMOVE:
            self._entries.pop(key, None)
        else:
            entry = self._entries.get(key)
            if entry is None:
                entry = Entry(key[0], sid, fields["cwd_name"], None, state, now, now)
                self._entries[key] = entry
            entry.state = state
            entry.updated = now
            if fields["cwd_name"]:
                entry.cwd_name = fields["cwd_name"]
            if fields["title"]:
                # Only prompt events carry the title, so remember the last one.
                entry.title = str(fields["title"])
        return self._after_mutation(now)

    def _after_mutation(self, now: float) -> bool:
        visible = self.rows()
        changed = visible != self._last_visible
        if changed:
            self._last_visible = visible
            self._last_change = now
            self.changed.set()
        if changed or now - self._last_persist >= PERSIST_EVERY:
            self.save()
        return changed

    def _prune(self, now: float) -> None:
        for key, e in list(self._entries.items()):
            if now - e.updated > DROP_AFTER:
                del self._entries[key]

    def rows(self) -> list[dict]:
        """Visible rows, sorted and labelled, at most MAX_SESSIONS."""
        now = self._clock()
        self._prune(now)

        def shown_state(e: Entry) -> int:
            if e.state == WORKING and now - e.updated > STALE_WORKING:
                return STALE
            return e.state

        # Labels are de-duplicated per host in first-seen order, so "api" and
        # "api#2" keep their names as other sessions come and go.
        labels: dict[tuple[str, str], str] = {}
        counts: dict[tuple[str, str], int] = {}
        for e in sorted(self._entries.values(), key=lambda e: e.first_seen):
            base = ascii_fold(e.title or e.cwd_name or "session", NAME_MAX) or "session"
            n = counts.get((e.host, base), 0) + 1
            counts[(e.host, base)] = n
            if n > 1:
                suffix = f"#{n}"
                base = base[: NAME_MAX - len(suffix)] + suffix
            labels[(e.host, e.sid)] = base

        ordered = sorted(self._entries.values(),
                         key=lambda e: (PRIORITY[shown_state(e)], e.first_seen))
        return [{"h": e.host, "n": labels[(e.host, e.sid)], "s": shown_state(e)}
                for e in ordered[:MAX_SESSIONS]]

    def total(self) -> int:
        """Live sessions, including any beyond the MAX_SESSIONS sent."""
        self._prune(self._clock())
        return len(self._entries)

    def payload(self, limit: int) -> bytes:
        """The "ss" write, dropping whole rows from the end until it fits.

        "sn" carries the real total when it's more than the rows sent, so the
        device can say "+9 more" rather than guess from the rows it has.
        """
        rows = self.rows()
        total = self.total()
        while True:
            msg = {"ss": rows}
            if total > len(rows):
                msg["sn"] = total
            data = json.dumps(msg, separators=(",", ":")).encode()
            if len(data) <= limit or not rows:
                return data
            rows = rows[:-1]

    # -- transport -----------------------------------------------------------

    def on_connect(self) -> None:
        """A new BLE link: the device needs the full list again."""
        self._last_sent = None

    async def pump(self, write: Writer, limit: int) -> bool | None:
        """Send the list if it changed, the link is new, or a heartbeat is due.

        Returns None when nothing was sent, else the write's result. Call it on
        every daemon loop tick and whenever `changed` fires.
        """
        if self.changed.is_set():
            wait = DEBOUNCE - (self._clock() - self._last_change)
            if wait > 0:
                await asyncio.sleep(wait)
            self.changed.clear()
        # Recompute even without an event: "working" ages into "stale" on its own.
        self._after_mutation(self._clock())
        self.changed.clear()
        data = self.payload(limit)
        now = self._clock()
        if data == self._last_sent and now - self._last_sent_at < HEARTBEAT:
            return None
        ok = await write(data)
        if ok:
            self._last_sent = data
            self._last_sent_at = now
        return ok

    # -- persistence ---------------------------------------------------------

    def save(self) -> None:
        if self._path is None:
            return
        self._last_persist = self._clock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(e) for e in self._entries.values()]))
            os.replace(tmp, self._path)
        except OSError as e:
            self._log(f"Sessions: could not save {self._path}: {e}")

    def load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            for raw in json.loads(self._path.read_text()):
                e = Entry(**raw)
                self._entries[(e.host, e.sid)] = e
        except (OSError, ValueError, TypeError) as e:
            self._log(f"Sessions: ignoring unreadable {self._path}: {e}")
            self._entries.clear()
        self._prune(self._clock())
        self._last_visible = self.rows()


# -- HTTP receiver -------------------------------------------------------------

def load_or_create_token(path: Path) -> str:
    """The shared secret hooks must send. Created on first run, private to the user."""
    try:
        token = path.read_text().strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_hex(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


async def _read_request(reader: asyncio.StreamReader):
    head = await reader.readuntil(b"\r\n\r\n")
    if len(head) > 16 * 1024:
        raise ValueError("headers too large")
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length") or 0)
    if length < 0 or length > MAX_BODY:
        raise OverflowError
    body = await reader.readexactly(length) if length else b""
    return method, target, headers, body


def check_request(method: str, target: str, headers: dict, token: str) -> tuple[int, str | None]:
    """Validate a request. Returns (status, host tag or None)."""
    if method != "POST":
        return 405, None
    path = target.split("?", 1)[0]
    if not path.startswith("/hook/") or len(path) <= len("/hook/"):
        return 404, None
    # Browsers always send Origin on cross-origin POSTs; Claude Code doesn't.
    if "origin" in headers:
        return 403, None
    # A non-"simple" content type forces a CORS preflight we never answer.
    if not headers.get("content-type", "").lower().startswith("application/json"):
        return 415, None
    if not hmac.compare_digest(headers.get(TOKEN_HEADER, ""), token):
        return 403, None
    return 204, path[len("/hook/"):]


_REASONS = {204: "No Content", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
            405: "Method Not Allowed", 413: "Payload Too Large", 415: "Unsupported Media Type"}


class Receiver:
    def __init__(self, tracker: SessionTracker, token: str, log: Log = print) -> None:
        self.tracker = tracker
        self.token = token
        self._log = log
        self.server: asyncio.base_events.Server | None = None

    async def start(self, port: int) -> bool:
        try:
            self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        except OSError as e:
            self._log(f"Sessions: can't listen on 127.0.0.1:{port} ({e}); session status disabled")
            return False
        self._log(f"Sessions: listening on 127.0.0.1:{port}")
        return True

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status = 400
        try:
            method, target, headers, body = await asyncio.wait_for(_read_request(reader), READ_TIMEOUT)
            status, host = check_request(method, target, headers, self.token)
            if status == 204:
                event = json.loads(body)
                if isinstance(event, dict):
                    self.tracker.handle_event(host, event)
                else:
                    status = 400
        except OverflowError:
            status = 413
        except (ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                asyncio.TimeoutError, UnicodeDecodeError):
            status = 400
        finally:
            # Always an empty body: a 2xx JSON body would be read by Claude Code
            # as a hook decision (e.g. an answer to PermissionRequest).
            try:
                writer.write(f"HTTP/1.1 {status} {_REASONS[status]}\r\n"
                             "Content-Length: 0\r\nConnection: close\r\n\r\n".encode())
                await writer.drain()
                writer.close()
            except (ConnectionError, OSError):
                pass


# -- daemon glue ----------------------------------------------------------------

def read_config_value(config_file: Path, key: str) -> str | None:
    """Raw value of `key = value` in the daemon config, or None."""
    try:
        for line in config_file.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                name, val = line.split("=", 1)
                if name.strip().lower() == key:
                    return val.strip()
    except OSError:
        pass
    return None


async def start_from_config(config_file: Path, log: Log = print) -> SessionTracker | None:
    """Start session status if `sessions = on`. Returns the tracker, or None.

    The receiver, the table and its file live for the daemon's whole run, not
    per BLE connection, so a reconnect loses nothing. The token and the table
    are kept next to the config file.
    """
    if (read_config_value(config_file, "sessions") or "off").lower() != "on":
        return None
    try:
        port = int(read_config_value(config_file, "sessions_port") or DEFAULT_PORT)
    except ValueError:
        log(f"Sessions: bad sessions_port; using {DEFAULT_PORT}")
        port = DEFAULT_PORT
    tracker = SessionTracker(config_file.parent / "sessions.json", log)
    tracker.load()
    token = load_or_create_token(config_file.parent / "sessions-token")
    receiver = Receiver(tracker, token, log)
    if not await receiver.start(port):
        return None
    tracker.receiver = receiver   # keep the server referenced for the daemon's lifetime
    return tracker


async def wait_first(*events: asyncio.Event, timeout: float) -> None:
    """Return when any of `events` is set, or after `timeout` seconds."""
    tasks = [asyncio.ensure_future(e.wait()) for e in events]
    try:
        await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
