"""So a transcript isn't left recording by mistake: closing the Transcripts window while it's recording (the
first time each day), or nothing being heard for a while, brings up a reminder beside the floating icon that
it's still transcribing, with every way to stop it, Stop now and Keep going; a desktop notification if the
icon isn't on screen."""
import time
from datetime import date, timedelta
from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
REMINDER = "Still transcribing"  # the reminder's window
WAYS = ["•  Stop, in the Transcripts window (click the icon to open it)", "•  Ctrl+Win, lift Win and press it again",
        "•  Stop transcribing, in the icon's menu"]


def recording(start, **kw):
    app = start(styles=[], **kw)
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def closed(app):
    app.send("close", window_title="Transcripts")
    eventually(lambda: "Transcripts" not in app.send("windows")["titles"])


def transcribing(app):
    return any(i["label"] == "Stop transcribing" for i in app.send("menu_items")["items"])


def test_closing_the_window_while_recording_says_it_carries_on_and_how_to_stop_it(start):
    app = recording(start)

    closed(app)

    app.wait_window(REMINDER)
    texts = app.read(REMINDER)
    assert "⚠  Still transcribing" in texts
    assert "Closing the window doesn't stop it: everything said through this computer's speakers and microphone " \
           "is still being written down." in texts
    assert "The blue ring around Dictate's icon means it's transcribing. Click the icon to see the transcript." in texts
    assert all(way in texts for way in WAYS)
    assert "Stop now" in texts and "Keep going" in texts


def test_stop_now_stops_it(start):
    app = recording(start)
    app.hear("That's everything, thanks.")
    closed(app)
    app.wait_window(REMINDER)

    app.click("Stop now", REMINDER)

    eventually(lambda: not transcribing(app))
    eventually(lambda: "That's everything, thanks." in (app.transcript_file() or ""))
    assert REMINDER not in app.send("windows")["titles"]


def test_keep_going_carries_on(start):
    app = recording(start)
    closed(app)
    app.wait_window(REMINDER)

    app.click("Keep going", REMINDER)

    eventually(lambda: REMINDER not in app.send("windows")["titles"])
    assert transcribing(app)


def test_it_is_said_once_a_day(start):
    app = recording(start)
    closed(app)
    app.wait_window(REMINDER)
    app.click("Keep going", REMINDER)
    app.send("click_icon")
    app.wait_window("Transcripts")

    closed(app)

    time.sleep(0.5)
    assert REMINDER not in app.send("windows")["titles"]


def test_it_is_said_again_the_next_day(start):
    app = recording(start, settings={"reminded_closed": (date.today() - timedelta(days=1)).isoformat()})

    closed(app)

    app.wait_window(REMINDER)


def test_closing_the_window_when_not_recording_says_nothing(start):
    app = start(styles=[])
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    closed(app)

    time.sleep(0.5)
    assert app.send("windows")["titles"] == []


def test_without_the_icon_on_screen_a_desktop_notification_says_it(start):
    app = recording(start)
    app.send("hide_icon")
    mark = app.mark()

    closed(app)

    note = app.wait_for("notified", after=mark)
    assert note["title"] == "⚠ Still transcribing"
    assert "To stop it:" in note["body"] and "Ctrl+Win, lift Win and press it again" in note["body"]
    assert note["actions"] == ["Stop now", "Show transcript"] and note["image"]  # a picture of the icon
    assert REMINDER not in app.send("windows")["titles"]
    app.send("notification", button="stop")
    eventually(lambda: not transcribing(app))


def test_after_a_while_with_nothing_heard_it_says_it_is_still_transcribing(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.hear("Right, that's the call done.")

    app.wait_window(REMINDER)

    texts = app.read(REMINDER)
    assert any(t.startswith("⚠  Nothing heard for") for t in texts)
    assert all(way in texts for way in WAYS)


def test_the_quiet_reminder_comes_again_only_after_something_is_heard(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.wait_window(REMINDER)
    app.click("Keep going", REMINDER)
    eventually(lambda: REMINDER not in app.send("windows")["titles"])

    time.sleep(1.5)
    assert REMINDER not in app.send("windows")["titles"]  # the same quiet: not again

    app.hear("Oh, one more thing.")
    app.wait_window(REMINDER, timeout=5)  # quiet again since
