"""The History window: browsing, searching, copying, playing back and deleting past dictations."""
import json, os, time
from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session


def past(data, *entries, audio=()):
    """Write history entries (oldest first) and recordings named in audio, as if dictated earlier."""
    (data / "audio").mkdir(parents=True, exist_ok=True)
    for name in audio:
        (data / "audio" / name).write_bytes(b"RIFF")
    (data / "history.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))


MONDAY = {"t": "2026-10-19T09:00:00", "text": "Morning all, standup in five.", "raw": "morning all standup in five",
          "app": "Slack", "cleanup": True, "style": "Chat", "audio": "monday.wav"}
TUESDAY = {"t": "2026-10-20T14:30:00", "text": "Pick up milk", "app": "firefox", "cleanup": False}


def open_history(start, *entries, audio=()):
    app = start(styles=[])
    past(app.data, *entries, audio=audio)
    app.send("menu", path=["History"])
    app.wait_window("History")
    return app


def test_history_lists_dictations_newest_first_with_what_was_applied(start):
    app = open_history(start, MONDAY, TUESDAY, audio=["monday.wav"])
    texts = app.read("History")

    assert texts.index("Pick up milk") < texts.index("Morning all, standup in five.")
    assert {"Raw transcript", "Cleanup", "+ Chat"} <= set(texts)
    assert "Tue 20 Oct · 14:30 · firefox" in texts


def test_an_empty_history_says_how_to_start(start):
    app = open_history(start)

    assert "Nothing yet — hold Ctrl+Win to dictate" in app.read("History")


def test_searching_shows_only_matching_dictations(start):
    app = open_history(start, MONDAY, TUESDAY)

    app.send("fill", name="Search", text="milk", window_title="History")
    time.sleep(0.3)  # the search box waits briefly for typing to stop

    texts = app.read("History")
    assert "Pick up milk" in texts and "Morning all, standup in five." not in texts


def test_copy_and_original_put_the_text_or_the_transcript_on_the_clipboard(start):
    app = open_history(start, MONDAY)

    app.click("Copy", window="History")
    assert app.send("clipboard")["text"] == "Morning all, standup in five."
    app.click("Original", window="History")
    assert app.send("clipboard")["text"] == "morning all standup in five"


def test_play_is_offered_only_while_the_recording_exists_and_plays_it(start):
    app = open_history(start, MONDAY, TUESDAY, audio=["monday.wav"])
    assert app.read("History").count("▶ Play") == 1

    mark = app.mark()
    app.click("▶ Play", window="History")

    assert app.wait_for("playing", after=mark)["path"].endswith("monday.wav")
    app.click("■ Stop", window="History")
    app.wait_for("stopped", after=mark)


def test_deleting_an_entry_removes_it_and_its_recording(start):
    app = open_history(start, MONDAY, TUESDAY, audio=["monday.wav"])

    app.click("Delete", window="History", nth=1)  # the second card: Monday's, the older one

    assert [e["text"] for e in app.history()] == ["Pick up milk"]
    assert not (app.data / "audio/monday.wav").exists()
    assert "Morning all, standup in five." not in app.read("History")


def test_clear_history_asks_first_and_cancel_keeps_everything(start):
    app = open_history(start, MONDAY, TUESDAY, audio=["monday.wav"])

    app.click("Clear history", window="History")
    app.wait_window(None)
    assert "Delete all 2 history entries and their recordings?" in app.read(None)
    app.click("Cancel")

    assert len(app.history()) == 2 and (app.data / "audio/monday.wav").exists()


def test_clear_history_deletes_every_entry_and_recording(start):
    app = open_history(start, MONDAY, TUESDAY, audio=["monday.wav"])

    app.click("Clear history", window="History")
    app.wait_window(None)
    app.click("Delete all")

    eventually(lambda: app.history() == [])
    assert not (app.data / "audio/monday.wav").exists()
    assert "Nothing yet — hold Ctrl+Win to dictate" in app.read("History")


def test_keeping_recordings_for_less_time_deletes_older_ones_and_hides_their_play_button(start):
    app = open_history(start, MONDAY, audio=["monday.wav"])
    two_hours_ago = time.time() - 2 * 3600
    os.utime(app.data / "audio/monday.wav", (two_hours_ago, two_hours_ago))

    app.send("choose", option="1 hour", window_title="History")

    assert not (app.data / "audio/monday.wav").exists()
    assert "▶ Play" not in app.read("History")
    assert app.history()[0]["text"] == "Morning all, standup in five."  # the entry itself stays
