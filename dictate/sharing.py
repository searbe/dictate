"""Sharing transcripts with Claude Code, one request at a time, only as you choose (the meeting-notes skill).

A Claude Code session runs scripts/meeting_notes.py "<what it's looking for>", which connects to this Dictate
through a Unix socket in your runtime folder (XDG_RUNTIME_DIR: yours only; nothing goes over the network, and
a connection from another user is refused). Dictate asks you, in a window above the others, which transcripts
to give it, if any, each as its summary or as the whole transcript; nothing is ticked to begin with, and closing
it, Escape, or not answering within WAIT is refusing. Only then is what you chose sent back, and the script prints
it in that session, which sends it to Anthropic like anything else said there. Nothing is remembered: the next
request asks again. While "Let Claude Code ask for transcripts" is off in Settings (as it is to begin with),
every request is refused without asking. Every request is logged: when, from which folder, what for, and what
was shared.

A request: one JSON line, {"topic": "...", "from": "<the session's folder>"}. The answer: one JSON line,
{"shared": [{"title", "kind": "summary" | "transcript", "text"}]} or {"refused": "<why>"}."""
import hashlib
import json
import logging
import os
import socket
import struct
import threading
from pathlib import Path

from gi.repository import GLib

from . import DATA, transcript

log = logging.getLogger(__name__)

WAIT = 540  # seconds to choose before it counts as refusing (within the 10 min a Claude Code command may take)
LONGEST = 2000  # characters: what it's looking for, at most (shown in the window)


def address(data=DATA):
    """The socket a Dictate with this data folder listens on (per data folder: the tests' Dictates have their own)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dictate-{os.getuid()}"
    return Path(runtime) / f"dictate-{hashlib.sha1(str(Path(data).resolve()).encode()).hexdigest()[:10]}.sock"


def peer_uid(conn):
    """The user id of the process at the other end of a Unix socket (Linux: SO_PEERCRED)."""
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", creds)[1]


class Server:
    """Listens for requests while Dictate runs. allowed(): whether asking is turned on (Settings); ask(topic,
    where, answer): on the GTK thread, ask you, then answer(shared or None) (shared: [(path, kind)]); it returns
    something to close() if you don't answer in time."""

    def __init__(self, allowed, ask):
        self.allowed, self.ask, self.busy = allowed, ask, False
        self.path = address()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)  # (left by a Dictate that crashed: only one can run)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            self.sock.bind(str(self.path))  # (rw for you only)
        finally:
            os.umask(old)
        self.sock.listen(2)
        threading.Thread(target=self.serve, daemon=True, name="sharing").start()

    def close(self):
        self.sock.close()
        self.path.unlink(missing_ok=True)

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:  # closed
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        with conn:
            conn.settimeout(WAIT + 30)
            try:
                if peer_uid(conn) != os.getuid():
                    log.warning("sharing: refused a request from another user")
                    return self.reply(conn, {"refused": "Dictate only answers its own user."})
                request = json.loads(conn.makefile().readline() or "{}")
                topic = " ".join(str(request.get("topic", "")).split())[:LONGEST]
                where = str(request.get("from", ""))[:500]
            except (OSError, ValueError, AttributeError):
                return
            log.info("sharing: Claude Code (in %s) asked for transcripts about %r", where or "?", topic)
            if not self.allowed():
                log.info("sharing: refused (asking is turned off in Settings)")
                return self.reply(conn, {"refused": "Sharing transcripts with Claude Code is turned off in "
                                                    "Dictate's Settings (Let Claude Code ask for transcripts)."})
            if not topic:
                return self.reply(conn, {"refused": "The request didn't say what it's looking for."})
            if self.busy:
                log.info("sharing: refused (another request is being answered)")
                return self.reply(conn, {"refused": "Dictate is already asking about another request."})
            self.busy = True
            answered, chosen, asking = threading.Event(), [], []

            def answer(shared):
                chosen.append(shared)
                answered.set()
            GLib.idle_add(lambda: asking.append(self.ask(topic, where, answer)) and False)
            if not answered.wait(WAIT):
                GLib.idle_add(lambda: asking and asking[0].close() and False)  # (too late: refused)
            self.busy = False
            shared = chosen[0] if chosen else None
            if not shared:
                log.info("sharing: refused%s", "" if chosen else " (no answer in time)")
                return self.reply(conn, {"refused": "The user chose not to share any transcripts."})
            out = [part(path, kind) for path, kind in shared]
            log.info("sharing: shared %s", ", ".join(f"{p.stem} ({k})" for p, k in shared))
            self.reply(conn, {"shared": [o for o in out if o]})

    @staticmethod
    def reply(conn, answer):
        try:
            conn.sendall((json.dumps(answer) + "\n").encode())
        except OSError:
            pass


def part(path, kind):
    """What's shared of the transcript at path: its summary, or the whole transcript (its Markdown, which has its
    summary and topics too). Never its recordings or voiceprints."""
    item = transcript.read(path)
    if not item:
        return None
    title = f"Transcript, {item['started']:%A %-d %B %Y, %H:%M}" + (f" ({item['length']})" if item["length"] else "")
    if kind == "summary":
        found = transcript.read_summary(path)
        return {"title": title, "kind": "summary", "text": found.text if found else ""}
    return {"title": title, "kind": "transcript", "text": path.read_text()}
