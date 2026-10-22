"""Real windows on a real (headless) KWin, reported by Dictate's own KWin script: does Dictate know where
the text is going? These cover what the other tests stand in for with a D-Bus call."""
import subprocess, sys, time
from pathlib import Path
import pytest
from conftest import needs_kwin
from harness.client import refinement

pytestmark = needs_kwin
HERE = Path(__file__).parent
REFINEMENTS = [refinement("Chat", "c", apps="whatsapp"), refinement("Mail", "m", apps="gmail")]


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


def test_dictating_into_a_window_uses_the_refinement_for_its_title(start, windows):
    app = start(refinements=REFINEMENTS)
    windows("firefox", "Inbox - me@gmail.com - Gmail — Mozilla Firefox")

    app.dictate("dear sir")

    assert app.dictations()[-1]["refinement"] == "Mail"
    assert app.dictations()[-1]["title"] == "Inbox - me@gmail.com - Gmail — Mozilla Firefox"


def test_switching_browser_tab_changes_the_refinement_without_refocusing(start, windows):
    """The bug that refined a WhatsApp message as an email: the tab changed, the window didn't."""
    app = start(refinements=REFINEMENTS)
    browser = windows("firefox", "Inbox - me@gmail.com - Gmail — Mozilla Firefox")
    app.dictate("dear sir")

    browser.retitle("WhatsApp — Mozilla Firefox")
    app.dictate("see you soon")

    assert [e["refinement"] for e in app.dictations()] == ["Mail", "Chat"]


def test_switching_to_another_window_switches_refinement(start, windows):
    app = start(refinements=REFINEMENTS)
    windows("firefox", "WhatsApp — Mozilla Firefox")
    app.dictate("see you soon")

    windows("thunderbird", "Write: Gmail draft")
    app.dictate("dear sir")

    assert [e["refinement"] for e in app.dictations()] == ["Chat", "Mail"]


def test_dictate_ignores_its_own_windows_when_tracking_focus(start, windows):
    """Opening Dictations mustn't make Dictate think the text is going into it."""
    app = start(refinements=REFINEMENTS)
    windows("firefox", "WhatsApp — Mozilla Firefox")
    app.send("menu", path=["Dictations"])
    app.wait_window("Dictations")
    time.sleep(0.3)

    app.dictate("see you soon")

    assert app.dictations()[-1]["refinement"] == "Chat"
