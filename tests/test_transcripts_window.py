"""The Transcripts window: every saved transcript in a list (when, how long, how it starts), the selected one
shown beside it, with Copy all, Open file, Delete and Open folder."""
import numpy as np
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
    app = start(styles=[])
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
    app = start(styles=[])
    app.ctrl_win_win()
    app.wait_window("Transcript")
    app.hear("A short one.")
    app.ctrl_win_win()
    eventually(lambda: any("Stopped" in t for t in app.read("Transcript")))

    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    assert "under a minute" in app.read("Transcripts")
    assert "Them  A short one." in shown(app)


def test_the_transcript_being_recorded_is_listed_and_kept_up_to_date(start):
    app = start(styles=[])
    app.ctrl_win_win()
    app.wait_window("Transcript")
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    assert "Recording now" in app.read("Transcripts")

    app.hear("Still going.")

    eventually(lambda: "Them  Still going." in shown(app))
    app.click("Stop", "Transcript")
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
    assert "No transcripts yet. To start one, hold Ctrl+Win, lift Win and press it again." in shown(app)


def test_cancelling_delete_keeps_it(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY))

    app.click("Delete", "Transcripts")
    app.wait_window(None)
    app.click("Cancel")

    eventually(lambda: "Mon 19 Oct · 10:00" in app.read("Transcripts"))
    assert (app.data / "transcripts/2026-10-19 10.00.00.md").exists()


def test_older_transcripts_take_their_length_from_their_recording(start):
    """Transcripts saved before they said how long they lasted."""
    app = start(styles=[])
    old = "\n".join(l for l in MONDAY.splitlines() if not l.startswith("Lasted")) + "\n"
    path = saved(app, "2026-10-19 10.00.00", old)
    soundfile.write(str(path.with_name("2026-10-19 10.00.00 them.ogg")), np.zeros(16000 * 125, np.int16), 16000,
                    format="OGG", subtype="OPUS")

    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    assert "2 min" in app.read("Transcripts")


def test_with_no_transcripts_it_says_how_to_make_one(start):
    app = opened(start)

    assert "No transcripts yet. To start one, hold Ctrl+Win, lift Win and press it again." in shown(app)
    assert "Open folder" in app.read("Transcripts")
    assert "Delete" not in app.read("Transcripts")
