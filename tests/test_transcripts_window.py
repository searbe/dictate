"""Transcripts, in the Dictate window: every saved transcript in a list (when, how long, how it starts), the
selected one shown beside it, with Copy all, Open file and Delete (icon buttons, found by their tooltips), and
Open folder."""
import json
import shutil
import subprocess
import time

import numpy as np
import pytest
import soundfile

from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
MONDAY = """# Transcript, Monday 19 October 2026, 10:00

Lasted 27 min, until 10:27.

**10:00:05 Them:** Shall we start with the roadmap?

**10:00:09 Me:** Yes, the roadmap first.
"""
TUESDAY = """# Transcript, Tuesday 20 October 2026, 16:30

Lasted 1 h 05 min, until 17:35.

**16:30:02 Them:** Welcome to the talk.
"""


def saved(app, name, text):
    folder = app.data / "transcripts"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.md").write_text(text)
    return folder / f"{name}.md"


def opened(start, *transcripts):
    app = start(refinements=[])
    for name, text in transcripts:
        saved(app, name, text)
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    return app


def shown(app):
    return app.send("field", name="text", window_title="Transcripts")["text"]


def test_every_transcript_is_listed_newest_first_with_when_and_how_long(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY), ("2026-10-20 16.30.00", TUESDAY))

    texts = app.read("Transcripts")

    assert texts.index("Tue 20 Oct · 16:30") < texts.index("Mon 19 Oct · 10:00")
    assert "1 h 05 min" in texts and "27 min" in texts
    assert "Shall we start with the roadmap? Yes, the roadmap first." in texts  # how it starts
    assert "Welcome to the talk." in shown(app)  # the newest is shown to begin with


def test_clicking_a_transcript_shows_it(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY), ("2026-10-20 16.30.00", TUESDAY))

    app.send("select", row="Mon 19 Oct · 10:00", window_title="Transcripts")

    text = shown(app)
    assert "10:00:05 Them  Shall we start with the roadmap?" in text
    assert "10:00:09 Me  Yes, the roadmap first." in text
    assert "Welcome" not in text


def test_copy_all_copies_the_transcript(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY))

    app.click("Copy all", "Transcripts")

    assert app.send("clipboard")["text"] == MONDAY


def test_a_transcript_just_recorded_is_listed_with_how_long_it_lasted(start):
    app = start(refinements=[])
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("A short one.")
    app.ctrl_win_win()
    eventually(lambda: app.stopped())

    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    assert "under a minute" in app.read("Transcripts")
    assert "Speaker 1  A short one." in shown(app)


def at_end(app):
    s = app.send("scroll", window_title="Transcripts")
    return s["value"] >= s["upper"] - s["page"] - 2 and s["upper"] > s["page"]


def talk(app, first, last, said="A long line that goes on for a while, so the transcript fills the window soon. " * 3):
    for i in range(first, last + 1):
        app.hear(f"{i}. {said}", voice=("a", "b")[i % 2])


def test_at_the_end_of_the_transcript_being_recorded_it_follows_what_is_said(start):
    app = recording(start)
    talk(app, 0, 29)
    eventually(lambda: "29. A long line" in shown(app))

    eventually(lambda: at_end(app))
    talk(app, 30, 34)
    eventually(lambda: "34. A long line" in shown(app))
    time.sleep(0.5)
    assert at_end(app)


def test_at_the_end_it_isnt_lost_when_the_view_moves_by_itself(start):
    """A wheel's or touchpad's scrolling glides on for a moment, to where the end was before the text grew; that
    isn't you scrolling up."""
    app = recording(start)
    talk(app, 0, 29)
    eventually(lambda: "29. A long line" in shown(app) and at_end(app))

    app.send("scroll", to=600, by_user=False, window_title="Transcripts")
    talk(app, 30, 31)
    eventually(lambda: "31. A long line" in shown(app))
    time.sleep(0.5)

    assert at_end(app)


def test_scrolled_up_it_stays_put_as_more_is_said_until_scrolled_back_to_the_end(start):
    """Only what's changed is written again, so the text doesn't shrink away for a moment (it flashed)."""
    app = recording(start)
    talk(app, 0, 29)
    eventually(lambda: "29. A long line" in shown(app) and at_end(app))

    top = app.send("scroll", to=600, window_title="Transcripts")["top"]  # part way up
    talk(app, 30, 32)
    app.hear_so_far("And something still being said")
    eventually(lambda: "32. A long line" in shown(app) and "still being said" in shown(app))
    time.sleep(0.5)
    assert abs(app.send("scroll", window_title="Transcripts")["top"] - top) < 100  # the same text shown (a line or so)

    app.send("scroll", to="end", window_title="Transcripts")
    talk(app, 33, 35)
    eventually(lambda: "35. A long line" in shown(app))
    time.sleep(0.5)
    assert at_end(app)


def test_the_transcript_being_recorded_is_listed_and_kept_up_to_date(start):
    app = start(refinements=[])
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    assert "Recording now" in app.read("Transcripts")

    app.hear("Still going.")

    eventually(lambda: "Speaker 1  Still going." in shown(app))
    app.click("Stop", "Transcripts")
    eventually(lambda: "under a minute" in app.read("Transcripts"))


def test_delete_asks_then_deletes_the_transcript_and_its_recordings(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY))
    folder = app.data / "transcripts"
    for who in ("me", "them"):
        (folder / f"2026-10-19 10.00.00 {who}.ogg").write_bytes(b"audio")

    app.click("Delete", "Transcripts")
    app.wait_window(None)
    assert "Delete the transcript from Mon 19 Oct, 10:00?" in app.read(None)
    app.click("Delete")

    eventually(lambda: not list(folder.iterdir()))
    assert ({"No transcripts yet", "To start one, hold Ctrl+Win, lift Win and press it again."}
            <= set(app.read("Transcripts")))


def test_cancelling_delete_keeps_it(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY))

    app.click("Delete", "Transcripts")
    app.wait_window(None)
    app.click("Cancel")

    eventually(lambda: "Mon 19 Oct · 10:00" in app.read("Transcripts"))
    assert (app.data / "transcripts/2026-10-19 10.00.00.md").exists()


def test_with_no_transcripts_it_says_how_to_make_one(start):
    app = opened(start)

    assert ({"No transcripts yet", "To start one, hold Ctrl+Win, lift Win and press it again."}
            <= set(app.read("Transcripts")))
    assert "Open folder" in app.read("Transcripts")
    assert "Delete" not in app.read("Transcripts")


def recording(start, *transcripts):
    """Dictate with these saved transcripts, transcribing."""
    app = start(refinements=[])
    for name, text in transcripts:
        saved(app, name, text)
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def rows(app):
    """The dates listed, top to bottom."""
    return [t for t in app.read("Transcripts")
            if t.count("·") == 1 and t[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]


def test_a_new_recording_appears_at_the_top_of_the_transcripts_and_is_shown(start):
    app = recording(start, ("2026-10-19 10.00.00", MONDAY), ("2026-10-20 16.30.00", TUESDAY))

    app.hear("Hello, can you hear me?")

    assert rows(app)[1:] == ["Tue 20 Oct · 16:30", "Mon 19 Oct · 10:00"]
    texts = app.read("Transcripts")
    assert "Recording now" in texts and "Stop" in texts and "Pause" in texts
    assert "Delete" not in texts  # not while it's being recorded
    eventually(lambda: "Speaker 1  Hello, can you hear me?" in shown(app))


def test_reading_another_transcript_meanwhile_the_recording_stays_at_the_top(start):
    app = recording(start, ("2026-10-19 10.00.00", MONDAY), ("2026-10-20 16.30.00", TUESDAY))

    app.send("select", row="Mon 19 Oct · 10:00", window_title="Transcripts")
    app.hear("This goes on in the background.")
    app.send("select", row="Tue 20 Oct · 16:30", window_title="Transcripts")
    app.hear("And so does this.")

    assert "Welcome to the talk." in shown(app)  # what's being read isn't disturbed
    assert "background" not in shown(app)
    assert rows(app)[1:] == ["Tue 20 Oct · 16:30", "Mon 19 Oct · 10:00"]
    assert "Recording now" in app.read("Transcripts")
    assert "Copy all" in app.read("Transcripts") and "Stop" not in app.read("Transcripts")


def test_clicking_the_recording_again_shows_what_has_been_said_since(start):
    app = recording(start, ("2026-10-19 10.00.00", MONDAY))
    app.send("select", row="Mon 19 Oct · 10:00", window_title="Transcripts")
    app.hear("Said while you were reading.")

    app.send("select", row=rows(app)[0], window_title="Transcripts")

    eventually(lambda: "Speaker 1  Said while you were reading." in shown(app))
    assert "Stop" in app.read("Transcripts")


def test_the_recording_shows_how_it_starts_in_the_list_as_it_is_heard(start):
    app = recording(start, ("2026-10-19 10.00.00", MONDAY))
    app.send("select", row="Mon 19 Oct · 10:00", window_title="Transcripts")

    app.hear("Let's begin with the numbers.")

    eventually(lambda: "Let's begin with the numbers." in app.read("Transcripts"))


def test_pause_shows_in_the_list_until_resumed(start):
    app = recording(start)

    app.click("Pause", "Transcripts")
    eventually(lambda: "Paused" in app.read("Transcripts") and "Resume" in app.read("Transcripts"))
    app.click("Resume", "Transcripts")

    eventually(lambda: "Recording now" in app.read("Transcripts"))


def test_once_stopped_it_is_listed_like_the_others(start):
    app = recording(start, ("2026-10-19 10.00.00", MONDAY))
    app.hear("The end.")

    app.click("Stop", "Transcripts")

    eventually(lambda: "under a minute" in app.read("Transcripts"))
    assert "Speaker 1  The end." in shown(app)  # still the one shown
    assert "Copy all" in app.read("Transcripts") and "Delete" in app.read("Transcripts")


def test_clicking_the_icon_while_recording_shows_the_recording(start):
    app = recording(start, ("2026-10-19 10.00.00", MONDAY))
    app.send("select", row="Mon 19 Oct · 10:00", window_title="Transcripts")
    app.hear("Back to the call.")

    app.send("click_icon")

    eventually(lambda: "Speaker 1  Back to the call." in shown(app))
    assert "Stop" in app.read("Transcripts")


def test_clicking_the_icon_while_recording_reopens_the_window(start):
    app = recording(start)
    app.send("close", window_title="Transcripts")
    eventually(lambda: "Transcripts" not in app.send("windows")["titles"])

    app.send("click_icon")

    app.wait_window("Transcripts")
    assert "Recording now" in app.read("Transcripts")


def test_clicking_the_icon_otherwise_opens_nothing(start):
    app = start(refinements=[])

    app.send("click_icon")

    assert app.send("windows")["titles"] == []


def recorded(app, name, seconds=3):
    """Recordings for a saved transcript: its microphone and this computer's audio (a tone each)."""
    folder = app.data / "transcripts"
    t = np.arange(16000 * seconds) / 16000
    for who, hz in (("me", 220), ("them", 330)):
        soundfile.write(str(folder / f"{name} {who}.ogg"), (0.2 * np.sin(2 * np.pi * hz * t)).astype(np.float32),
                        16000, format="OGG", subtype="OPUS")


def test_a_transcripts_recording_can_be_played_while_it_is_kept(start):
    app = start(refinements=[])
    saved(app, "2026-10-19 10.00.00", MONDAY)
    recorded(app, "2026-10-19 10.00.00")
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    mark = app.mark()

    app.click("Play", "Transcripts")

    played = app.wait_for("playing", after=mark)["path"]
    audio, rate = soundfile.read(played)
    assert rate == 16000 and len(audio) > 16000 * 2  # both recordings, mixed into one
    eventually(lambda: "Stop" in app.read("Transcripts"))
    app.click("Stop", "Transcripts")
    app.wait_for("stopped", after=mark)


def test_without_its_recordings_a_transcript_offers_no_play(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY))

    assert "Play" not in app.read("Transcripts")


def test_the_one_being_recorded_offers_no_play(start):
    app = recording(start)

    assert "Play" not in app.read("Transcripts")


@pytest.mark.skipif(not shutil.which("xdotool"), reason="drags with xdotool")
def test_the_list_and_the_topics_can_be_dragged_wider_while_a_call_is_recorded(start):
    """With the mouse, on the test's own desktop. While it's recorded, the transcript changes every second: its
    narrowest mustn't change with it (the dividers would stop wherever it is at the time)."""
    app = recording(start)
    for i in range(6):
        app.hear(f"Line {i} about the roadmap, and hiring, and the other things on the list.", voice=f"v{i % 3}")
    app.send("resize", width=1260, height=700, window_title="Transcripts")  # (the test screen's widest: room for both)
    left, right = app.send("panes", window_title="Transcripts")["panes"]

    drag(left["x"], left["y"] + left["height"] // 2, +100, lambda: app.hear_so_far("still talking"))
    right = app.send("panes", window_title="Transcripts")["panes"][1]
    drag(right["x"], right["y"] + right["height"] // 2, -100, lambda: app.hear_so_far("still talking"))

    after = app.send("panes", window_title="Transcripts")["panes"]
    assert after[0]["position"] >= left["position"] + 80  # the list: 100 px wider (the divider trails a step or two)
    assert after[1]["x"] <= right["x"] - 80  # the topics: likewise
    eventually(lambda: json.loads((app.data / "state.json").read_text()).get("transcript_panes", [0])[0]
               >= left["position"] + 80)  # and remembered, for next time


def drag(x, y, by, meanwhile):
    """Press the mouse at (x, y), move it by px sideways in steps (meanwhile() between them), and let go."""
    xdo = lambda *args: subprocess.run(["xdotool", *map(str, args)], check=True)
    xdo("mousemove", x, y)
    time.sleep(0.2)
    xdo("mousedown", 1)
    for step in range(10, abs(by) + 10, 10):
        xdo("mousemove", x + (step if by > 0 else -step), y)
        meanwhile()
        time.sleep(0.05)
    xdo("mouseup", 1)
    time.sleep(0.3)


def test_the_recordings_clock_runs_while_nothing_is_heard(start):
    app = recording(start)
    clock = lambda: next(t for t in app.read("Transcripts") if t[:1].isdigit() and t[1:2] == ":")

    first = clock()
    time.sleep(2.2)  # (nothing heard meanwhile: e.g. the microphone's switched off)

    assert clock() != first


def test_once_it_is_stopped_the_transcript_is_shown_once(start):
    app = recording(start)
    app.hear("Shall we look at the budget?")
    eventually(lambda: "Shall we look at the budget?" in app.transcript())

    app.click("Stop", "Transcripts")

    eventually(lambda: app.stopped())
    eventually(lambda: "Play" in app.read("Transcripts"))  # (saved, with its recordings: it can be played back)
    assert app.transcript().count("Shall we look at the budget?") == 1
