"""The test's side of harness/app.py: starts Dictate in its own process and talks to it like a user would."""
import json, os, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).parent


class Dictate:
    def __init__(self, home, data, llama, env=None):
        self.home, self.data, self.events, self.logs, self.next_id, self.ended = home, data, [], [], 0, False
        self.changed = threading.Condition()
        self.proc = subprocess.Popen([sys.executable, str(HERE / "app.py")], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     env={**os.environ, "HOME": str(home), "DICTATE_DATA": str(data),
                                          "DICTATE_TEST_LLAMA": str(llama), **(env or {})})
        threading.Thread(target=self._read, daemon=True).start()
        self.wait_for("ready", timeout=30)

    def _read(self):
        for line in self.proc.stdout:
            with self.changed:
                if line.startswith("EVENT "):
                    self.events.append(json.loads(line[6:]))
                else:
                    self.logs.append(line.rstrip("\n"))
                self.changed.notify_all()
        with self.changed:
            self.ended = True  # the app has exited: nothing more will happen
            self.changed.notify_all()

    # --- low level ---
    def mark(self):
        """A point in time: wait_for(..., after=mark) only looks at what happened since."""
        return len(self.events)

    def wait_for(self, kind, timeout=10, after=0, **match):
        deadline = time.monotonic() + timeout
        with self.changed:
            while True:
                for ev in self.events[after:]:
                    if ev["type"] == kind and all(ev.get(k) == v for k, v in match.items()):
                        return ev
                left = deadline - time.monotonic()
                if left <= 0 or self.ended:
                    raise AssertionError(f"no {kind} {match or ''} within {timeout}s; events: "
                                         f"{self.events[after:]}\nlog:\n" + "\n".join(self.logs[-30:]))
                self.changed.wait(min(left, 0.2))

    def happened(self, kind, after=0, **match):
        with self.changed:
            return any(ev["type"] == kind and all(ev.get(k) == v for k, v in match.items()) for ev in self.events[after:])

    def send(self, cmd, **args):
        self.next_id += 1
        mark = self.mark()
        self.proc.stdin.write(json.dumps({"cmd": cmd, "id": self.next_id, **args}) + "\n")
        self.proc.stdin.flush()
        reply = self.wait_for("done", after=mark, id=self.next_id)
        if "error" in reply:
            raise AssertionError(f"{cmd}: {reply['error']}")
        return reply

    # --- what a user does ---
    def dictate(self, speech, alt=False, letter=None, wait=True, timeout=15):
        """Hold Ctrl+Win, say speech (None: say nothing), optionally tap Alt (+ a letter), release.
        With wait, returns once the icon is idle again: what was pasted or typed, or None."""
        mark = self.mark()
        self.send("say", text=speech)
        self.send("keys", down=["ctrl", "meta"])
        self.wait_for("recording", after=mark, timeout=timeout)
        if alt:
            self.send("keys", down=["alt"] + ([letter] if letter else []))
            self.send("keys", up=([letter] if letter else []) + ["alt"])
        self.send("keys", up=["meta", "ctrl"])
        if not wait:
            return mark
        return self.result(mark, timeout)

    def ctrl_win_win(self):
        """Hold Ctrl+Win, lift Win, press it again, let go: starts or stops transcribe mode."""
        self.send("keys", down=["ctrl", "meta"])
        self.send("keys", up=["meta"])
        self.send("keys", down=["meta"])
        self.send("keys", up=["meta", "ctrl"])

    def hear(self, text, source="speakers", length=0.2):
        """Someone says text through the speakers (or "mic": into the microphone), ending now."""
        self.send("hear", text=text, source=source, length=length)

    def transcript(self):
        """What the Transcripts window shows of the selected transcript."""
        return self.send("field", name="text", window_title="Transcripts")["text"]

    def stopped(self):
        """Whether transcribe mode is off: the Transcripts window no longer shows a recording."""
        texts = self.read("Transcripts")
        return "Recording now" not in texts and "Paused" not in texts

    def transcript_file(self):
        """The saved transcript (the newest, if there are several)."""
        files = sorted((self.data / "transcripts").glob("*.md"))
        return files[-1].read_text() if files else None

    def result(self, mark, timeout=15):
        """What came out of the dictation that started at mark, once the icon is idle again."""
        self.wait_for("icon", after=mark + 1, state="idle", timeout=timeout)
        time.sleep(0.6)  # pasting waits a moment for the clipboard to settle; let it happen
        with self.changed:
            out = [ev for ev in self.events[mark:] if ev["type"] in ("pasted", "typed")]
        return out[-1] if out else None

    def wait_window(self, title, timeout=10):
        """Wait for a window to open; title None waits for a dialog (e.g. a confirmation)."""
        deadline = time.monotonic() + timeout
        while not self._open(title):
            if time.monotonic() > deadline:
                raise AssertionError(f"window {title!r} never opened; open: {self.send('windows')['titles']}")
            time.sleep(0.1)

    def _open(self, title):
        if title is not None:
            return title in self.send("windows")["titles"]
        try:
            return self.read(None)
        except AssertionError:
            return False

    def read(self, window=None):
        return self.send("read", window_title=window)["texts"]

    def click(self, label, window=None, nth=0):
        self.send("click", label=label, window_title=window, nth=nth)

    def history(self):
        path = self.data / "history.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def focus(self, cls, title, switched=True):
        """Tell Dictate which window has focus, exactly as the KWin script does over D-Bus."""
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync("local.dictate", "/", "local.dictate", "Active",
                      GLib.Variant("(ssib)", (cls, title, 1, switched)), None, 0, 5000, None)

    def stop(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(10)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait()


def style(name, key, apps="", default=False):
    """A test style whose prompt is just a marker, so the fake model can be told what to do with it."""
    return {"name": name, "key": key, "apps": apps, "prompt": f"STYLE:{name}", "default": default}


def eventually(check, timeout=5):
    """For outcomes that follow a moment after the action (e.g. once a dialog has closed): wait for check()."""
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "never happened"
        time.sleep(0.05)
