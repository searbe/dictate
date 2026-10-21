"""Real windows on a real (headless) KWin, reported by Dictate's own KWin script: does Dictate know where
the text is going? These cover what the other tests stand in for with a D-Bus call."""
import subprocess, sys, time
from pathlib import Path
import pytest
from conftest import needs_kwin
from harness.client import style

pytestmark = needs_kwin
HERE = Path(__file__).parent
STYLES = [style("Chat", "c", apps="whatsapp"), style("Mail", "m", apps="gmail")]


class Window:
    def __init__(self, cls, title):
        self.proc = subprocess.Popen([sys.executable, str(HERE / "harness/window.py"), cls, title],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.expect("focused")

    def expect(self, line):
        got = self.proc.stdout.readline().strip()
        assert got == line, f"window said {got!r}, expected {line!r}"

    def send(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def retitle(self, title):
        self.send(f"title {title}")
        self.expect("titled")
        time.sleep(0.3)  # KWin passes the new title on asynchronously

    def close(self):
        self.send("quit")
        self.proc.wait(5)


@pytest.fixture
def windows():
    opened = []

    def open_window(cls, title):
        w = Window(cls, title)
        opened.append(w)
        time.sleep(0.3)  # KWin reports the focus change asynchronously
        return w

    yield open_window
    for w in opened:
        if w.proc.poll() is None:
            w.close()


def test_dictating_into_a_window_uses_the_style_for_its_title(start, windows):
    app = start(styles=STYLES)
    windows("firefox", "Inbox - me@gmail.com - Gmail — Mozilla Firefox")

    app.dictate("dear sir")

    assert app.history()[-1]["style"] == "Mail"
    assert app.history()[-1]["title"] == "Inbox - me@gmail.com - Gmail — Mozilla Firefox"


def test_switching_browser_tab_changes_the_style_without_refocusing(start, windows):
    """The bug that styled a WhatsApp message as an email: the tab changed, the window didn't."""
    app = start(styles=STYLES)
    browser = windows("firefox", "Inbox - me@gmail.com - Gmail — Mozilla Firefox")
    app.dictate("dear sir")

    browser.retitle("WhatsApp — Mozilla Firefox")
    app.dictate("see you soon")

    assert [e["style"] for e in app.history()] == ["Mail", "Chat"]


def test_switching_to_another_window_switches_style(start, windows):
    app = start(styles=STYLES)
    windows("firefox", "WhatsApp — Mozilla Firefox")
    app.dictate("see you soon")

    windows("thunderbird", "Write: Gmail draft")
    app.dictate("dear sir")

    assert [e["style"] for e in app.history()] == ["Chat", "Mail"]


def test_dictate_ignores_its_own_windows_when_tracking_focus(start, windows):
    """Opening History mustn't make Dictate think the text is going into History."""
    app = start(styles=STYLES)
    windows("firefox", "WhatsApp — Mozilla Firefox")
    app.send("menu", path=["History"])
    app.wait_window("History")
    time.sleep(0.3)

    app.dictate("see you soon")

    assert app.history()[-1]["style"] == "Chat"
