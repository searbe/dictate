"""Dictations, in the Dictate window: browsing, searching, copying, playing back and deleting past dictations,
grouped by day; each one's actions (icon buttons, found by their tooltips) show on hover."""
import json
import os
import time

import pytest

from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session


def past(data, *entries, audio=()):
    """Write history entries (oldest first) and recordings named in audio, as if dictated earlier."""
    (data / "audio").mkdir(parents=True, exist_ok=True)
    for name in audio:
        (data / "audio" / name).write_bytes(b"RIFF")
    (data / "dictations.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))


MONDAY = {"t": "2026-10-19T09:00:00", "text": "Morning all, standup in five.", "raw": "morning all standup in five",
          "app": "Slack", "cleanup": True, "refinement": "Chat", "audio": "monday.wav"}
TUESDAY = {"t": "2026-10-20T14:30:00", "text": "Pick up milk", "app": "firefox", "cleanup": False}


def open_dictations(start, *entries, audio=()):
    app = start(refinements=[])
    past(app.data, *entries, audio=audio)
    app.send("menu", path=["Dictations"])
    app.wait_window("Dictations")
    return app


def test_history_lists_dictations_newest_first_with_what_was_applied(start):
    app = open_dictations(start, MONDAY, TUESDAY, audio=["monday.wav"])
    texts = app.read("Dictations")

    assert texts.index("Pick up milk") < texts.index("Morning all, standup in five.")
    assert {"Raw transcript", "Cleanup", "Chat"} <= set(texts)
    assert texts.index("Tue 20 Oct") < texts.index("14:30 · firefox") < texts.index("Mon 19 Oct")  # by day


def test_an_empty_history_says_how_to_start(start):
    app = open_dictations(start)

    texts = app.read("Dictations")
    assert "Nothing dictated yet" in texts
    assert "Hold Ctrl+Win, speak, and let go: what you said is pasted, and kept here." in texts


def test_searching_shows_only_matching_dictations(start):
    app = open_dictations(start, MONDAY, TUESDAY)

    app.send("fill", name="Search", text="milk", window_title="Dictations")
    time.sleep(0.3)  # the search box waits briefly for typing to stop

    texts = app.read("Dictations")
    assert "Pick up milk" in texts and "Morning all, standup in five." not in texts


def test_copy_and_original_put_the_text_or_the_transcript_on_the_clipboard(start):
    app = open_dictations(start, MONDAY)

    app.click("Copy", window="Dictations")
    assert app.send("clipboard")["text"] == "Morning all, standup in five."
    app.click("Copy original", window="Dictations")
    assert app.send("clipboard")["text"] == "morning all standup in five"


def test_play_is_offered_only_while_the_recording_exists_and_plays_it(start):
    app = open_dictations(start, MONDAY, TUESDAY, audio=["monday.wav"])
    assert app.read("Dictations").count("Play") == 1

    mark = app.mark()
    app.click("Play", window="Dictations")

    assert app.wait_for("playing", after=mark)["path"].endswith("monday.wav")
    app.click("Stop", window="Dictations")
    app.wait_for("stopped", after=mark)


def test_deleting_an_entry_removes_it_and_its_recording(start):
    app = open_dictations(start, MONDAY, TUESDAY, audio=["monday.wav"])

    app.click("Delete", window="Dictations", nth=1)  # the second card: Monday's, the older one

    assert [e["text"] for e in app.dictations()] == ["Pick up milk"]
    assert not (app.data / "audio/monday.wav").exists()
    assert "Morning all, standup in five." not in app.read("Dictations")


def test_clear_history_asks_first_and_cancel_keeps_everything(start):
    app = open_dictations(start, MONDAY, TUESDAY, audio=["monday.wav"])

    app.click("Clear all…", window="Dictations")
    app.wait_window(None)
    assert "Delete all 2 dictations and their recordings?" in app.read(None)
    app.click("Cancel")

    assert len(app.dictations()) == 2 and (app.data / "audio/monday.wav").exists()


def test_clear_history_deletes_every_entry_and_recording(start):
    app = open_dictations(start, MONDAY, TUESDAY, audio=["monday.wav"])

    app.click("Clear all…", window="Dictations")
    app.wait_window(None)
    app.click("Delete all")

    eventually(lambda: app.dictations() == [])
    assert not (app.data / "audio/monday.wav").exists()
    assert "Nothing dictated yet" in app.read("Dictations")


def test_keeping_recordings_for_less_time_deletes_older_ones_and_hides_their_play_button(start):
    app = open_dictations(start, MONDAY, audio=["monday.wav"])
    two_hours_ago = time.time() - 2 * 3600
    os.utime(app.data / "audio/monday.wav", (two_hours_ago, two_hours_ago))

    app.send("select", row="Settings", window_title="Dictations")
    app.send("choose", option="1 hour", window_title="Settings", setting="Keep dictation recordings")

    assert not (app.data / "audio/monday.wav").exists()
    app.send("select", row="Dictations", window_title="Settings")
    assert "Play" not in app.read("Dictations")
    assert app.dictations()[0]["text"] == "Morning all, standup in five."  # the entry itself stays



REFINEMENTD = {"t": "2026-10-20T16:00:00", "text": "SO, THE MEETING IS AT THREE.",
               "raw": "um so the meeting is at three", "cleaned": "So, the meeting is at three.", "app": "Slack",
               "cleanup": True, "refinement": "Chat"}


def test_clicking_a_step_shows_what_it_changed(start):
    app = open_dictations(start, REFINEMENTD)

    app.click("Cleanup", window="Dictations")

    eventually(lambda: "What cleanup changed" in app.read("Dictations"))
    texts = app.read("Dictations")
    assert "um so So, the meeting is at three." in texts  # what was taken out, then what was put in
    app.click("Chat", window="Dictations")
    eventually(lambda: "What Chat changed" in app.read("Dictations"))
    texts = app.read("Dictations")
    assert "What cleanup changed" not in texts  # one step at a time
    assert texts.index("Before") < texts.index("So, the meeting is at three.") < texts.index("After") \
        < texts.index("SO, THE MEETING IS AT THREE.", texts.index("After"))  # a rewrite: before, then after
    app.click("Chat", window="Dictations")
    eventually(lambda: "What Chat changed" not in app.read("Dictations"))  # clicked again: hidden


def test_without_the_cleaned_up_text_the_steps_cannot_be_opened(start):
    """Dictations with a refinement kept before 22 Oct 2026 didn't keep the text in between."""
    app = open_dictations(start, {k: v for k, v in REFINEMENTD.items() if k != "cleaned"})

    with pytest.raises(AssertionError):  # (a tag, not a button)
        app.click("Cleanup", window="Dictations")

    assert "What cleanup changed" not in app.read("Dictations")


def test_a_dictations_actions_show_when_it_is_hovered(start):
    app = open_dictations(start, MONDAY, audio=["monday.wav"])

    for action in ("Play", "Copy", "Copy original", "Delete"):
        assert app.send("has_icon", label=action, window_title="Dictations")["shown"]
        assert app.send("opacity", label=action, window_title="Dictations", hover=False)["opacity"] == 0
        assert app.send("opacity", label=action, window_title="Dictations", hover=True)["opacity"] == 1
