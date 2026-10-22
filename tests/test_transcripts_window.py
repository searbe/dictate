"""Transcripts, in the Dictate window: every saved transcript in a list (when, how long, how it starts), the
selected one shown beside it, with Copy all, Open file and Delete (icon buttons, found by their tooltips), and
Open folder."""
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
    app.wait_window("Transcripts")
    app.hear("A short one.")
    app.ctrl_win_win()
    eventually(lambda: app.stopped())

    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    assert "under a minute" in app.read("Transcripts")
    assert "Speaker 1  A short one." in shown(app)


def test_the_transcript_being_recorded_is_listed_and_kept_up_to_date(start):
    app = start(styles=[])
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
    assert {"No transcripts yet", "To start one, hold Ctrl+Win, lift Win and press it again."} <= set(app.read("Transcripts"))


def test_cancelling_delete_keeps_it(start):
    app = opened(start, ("2026-10-19 10.00.00", MONDAY))

    app.click("Delete", "Transcripts")
    app.wait_window(None)
    app.click("Cancel")

    eventually(lambda: "Mon 19 Oct · 10:00" in app.read("Transcripts"))
    assert (app.data / "transcripts/2026-10-19 10.00.00.md").exists()


def test_with_no_transcripts_it_says_how_to_make_one(start):
    app = opened(start)

    assert {"No transcripts yet", "To start one, hold Ctrl+Win, lift Win and press it again."} <= set(app.read("Transcripts"))
    assert "Open folder" in app.read("Transcripts")
    assert "Delete" not in app.read("Transcripts")


def recording(start, *transcripts):
    """Dictate with these saved transcripts, transcribing."""
    app = start(styles=[])
    for name, text in transcripts:
        saved(app, name, text)
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def rows(app):
    """The dates listed, top to bottom."""
    return [t for t in app.read("Transcripts") if t.count("·") == 1 and t[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]


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
    app = start(styles=[])

    app.send("click_icon")

    assert app.send("windows")["titles"] == []
