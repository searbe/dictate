"""So a transcript isn't left recording by mistake: closing the Dictate window while it's recording (the first
time each day) brings up a reminder beside the capsule that it's still transcribing, with every way to stop it,
Stop now and Keep going; nothing being heard for a while pauses it and says so, with Resume and Stop now. Desktop
notifications if the capsule isn't on screen."""
import time
from datetime import date, timedelta

from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
REMINDER = "Still transcribing"  # the reminder's window
PAUSED = "Transcript paused"  # the window saying it's been paused for being quiet
WAYS = ["•  Stop, in Transcripts (click the capsule to open it)", "•  Ctrl+Win, lift Win and press it again",
        "•  Stop transcribing, in the capsule's menu"]


def recording(start, **kw):
    app = start(refinements=[], **kw)
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
    assert "Still transcribing" in texts
    assert "Closing the window doesn't stop it: everything said through this computer's speakers and microphone " \
           "is still being written down." in texts
    assert "This capsule means it's transcribing. Click it to see the transcript." in texts
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
    app = start(refinements=[])
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


def test_after_a_while_with_nothing_heard_it_is_paused_and_says_so(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.hear("Right, that's the call done.")

    app.wait_window(PAUSED)

    assert any(t.startswith("Nothing has been transcribed for") and "so the transcript has been paused" in t
               for t in app.read(PAUSED))
    assert "Paused" in app.read("Transcripts")
    app.hear("Said while paused.")
    time.sleep(0.5)
    assert "Said while paused." not in (app.transcript_file() or "")


def test_resume_carries_on_and_it_is_paused_again_only_after_another_while(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "2"})
    app.wait_window(PAUSED, timeout=5)

    app.click("Resume", PAUSED)

    eventually(lambda: PAUSED not in app.send("windows")["titles"])
    time.sleep(0.5)  # (what began while it was paused is left out)
    app.hear("Oh, one more thing.")
    eventually(lambda: "Oh, one more thing." in (app.transcript_file() or ""))
    time.sleep(1)
    assert PAUSED not in app.send("windows")["titles"]  # quiet from when it was resumed, not from the start
    app.wait_window(PAUSED, timeout=5)


def test_stop_now_on_the_paused_alert_stops_it(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.hear("That's everything, thanks.")
    app.wait_window(PAUSED)

    app.click("Stop now", PAUSED)

    eventually(lambda: not transcribing(app))
    eventually(lambda: "That's everything, thanks." in (app.transcript_file() or ""))


def test_paused_without_the_icon_on_screen_the_alert_is_still_shown(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.send("hide_icon")

    app.wait_window(PAUSED)


def test_while_paused_nothing_heard_is_saved_and_once_resumed_it_is(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    assert app.send("sound", source="mic")["hushed"] is False
    app.wait_window(PAUSED)

    assert app.send("sound", source="mic")["hushed"] is True  # saved as silence, and not transcribed
    assert app.send("sound", source="speakers")["hushed"] is True

    app.click("Resume", PAUSED)
    assert app.send("sound", source="mic")["hushed"] is False


def test_a_sound_while_paused_flashes_the_icon(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.wait_window(PAUSED)
    assert not app.send("flashing")["flashing"]

    app.send("sound", source="mic", loud=False)
    assert not app.send("flashing")["flashing"]  # (near silence isn't a sound)

    app.send("sound", source="speakers")
    assert app.send("flashing")["flashing"]


def test_the_paused_alert_closes_only_with_resume_or_stop_now(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.wait_window(PAUSED)

    app.send("press", key="Escape", window_title=PAUSED)
    app.send("close", window_title=PAUSED)  # as the window manager's close would
    time.sleep(0.3)

    assert PAUSED in app.send("windows")["titles"]
    assert transcribing(app)


def test_the_paused_alert_closed_some_other_way_stops_it(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.hear("That's everything, thanks.")
    app.wait_window(PAUSED)

    app.send("destroy", window_title=PAUSED)

    eventually(lambda: not transcribing(app))
    eventually(lambda: "That's everything, thanks." in (app.transcript_file() or ""))


def test_ctrl_win_while_the_paused_alert_waits_does_not_dictate_but_points_to_the_alert(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.wait_window(PAUSED)
    mark = app.mark()

    app.send("keys", down=["ctrl", "meta"])
    app.send("keys", up=["meta", "ctrl"])

    assert "You pressed Ctrl+Win to dictate. Resume or stop this transcript first." in app.read(PAUSED)
    assert app.send("flashing")["flashing"]
    assert not app.happened("recording", after=mark)


def test_clicking_the_capsule_while_the_paused_alert_waits_brings_it_up_and_flashes(start):
    app = recording(start, env={"DICTATE_TEST_QUIET": "1"})
    app.wait_window(PAUSED)

    app.send("click_icon")

    assert app.send("flashing")["flashing"]
    assert "You pressed Ctrl+Win" not in " ".join(app.read(PAUSED))
