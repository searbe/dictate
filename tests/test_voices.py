"""Telling voices apart in transcripts: "Speaker 1", "Speaker 2", …, naming them, and (opt-in) remembering
the voices you name, to name them in later transcripts. The voiceprints here are stand-ins: the same for
the same voice, unrelated for different voices. How well the real model tells real voices apart is
measured by scripts/bench_voices.py."""
from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
LONG = 2.0  # seconds: long enough to tell a new voice by


def recording(start, **kw):
    app = start(styles=[], **kw)
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def shown(app):
    return app.transcript()


def name(app, label, new):
    """Click a voice above the transcript and name it."""
    app.click(label, "Transcripts")
    app.wait_window(None)
    app.send("fill", name="Name", text=new)
    app.click("Rename")
    eventually(lambda: _dialog_gone(app))


def _dialog_gone(app):
    try:
        app.read(None)
        return False
    except AssertionError:
        return True


def stop(app):
    app.click("Stop", "Transcripts")
    eventually(app.stopped)
    app.send("close", window_title="Transcripts")
    eventually(lambda: "Transcripts" not in app.send("windows")["titles"])


def again(app):
    """Start another recording."""
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    eventually(lambda: "Recording now" in app.read("Transcripts"))


def remember_voices(app):
    """Tick (or untick) Remember voices I name, in the Voices window."""
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    app.click("Voices…", "Transcripts")
    app.wait_window("Voices")
    app.click("Remember voices I name", "Voices")


def test_each_voice_through_the_speakers_is_a_different_speaker(start):
    app = recording(start)

    app.hear("Shall we start?", voice="alice", length=LONG)
    app.hear("Yes, let's.", voice="bob", length=LONG)
    app.hear("Great.", voice="alice", length=LONG)

    text = eventually(lambda: "Great." in shown(app)) or shown(app)
    assert "Speaker 1  Shall we start?" in text
    assert "Speaker 2  Yes, let's." in text
    assert "Speaker 1  Great." in text
    assert "Speaker 1:** Shall we start?" in app.transcript_file()


def test_a_voice_can_be_named_while_recording(start):
    app = recording(start)
    app.hear("Hello.", voice="alice", length=LONG)
    app.hear("Hi there.", voice="bob", length=LONG)
    eventually(lambda: "Hi there." in shown(app))

    name(app, "Speaker 2", "Sarah")
    app.hear("How was the weekend?", voice="bob", length=LONG)

    text = eventually(lambda: "How was the weekend?" in shown(app)) or shown(app)
    assert "Sarah  Hi there." in text and "How was the weekend?" in text.split("Sarah")[-1]
    assert "Speaker 2" not in text
    assert "Sarah:** Hi there." in app.transcript_file()


def test_naming_two_voices_the_same_makes_them_one_person(start):
    """For when one person was taken for two."""
    app = recording(start)
    app.hear("First.", voice="alice", length=LONG)
    app.hear("Second.", voice="alice-on-a-bad-line", length=LONG)
    eventually(lambda: "Speaker 2" in shown(app))

    name(app, "Speaker 1", "Sarah")
    name(app, "Speaker 2", "Sarah")

    text = shown(app)
    assert "Speaker" not in text and "Sarah  First. Second." in text
    assert app.read("Transcripts").count("Sarah") == 1  # one button to name her


def test_a_voice_in_a_saved_transcript_can_be_named(start):
    app = recording(start)
    app.hear("Let's begin.", voice="alice", length=LONG)
    eventually(lambda: "Let's begin." in shown(app))
    app.click("Stop", "Transcripts")
    eventually(app.stopped)

    name(app, "Speaker 1", "Priya")

    eventually(lambda: "Priya  Let's begin." in shown(app))
    assert "Priya:** Let's begin." in app.transcript_file()


def test_voices_are_not_remembered_unless_you_turn_it_on(start):
    app = recording(start)
    app.hear("Hello.", voice="alice", length=LONG)
    eventually(lambda: "Hello." in shown(app))
    name(app, "Speaker 1", "Sarah")
    stop(app)

    again(app)
    app.hear("Hello again.", voice="alice", length=LONG)

    eventually(lambda: "Speaker 1  Hello again." in shown(app))
    assert not list((app.data / "transcripts").glob("*voices*"))


def test_with_remembering_on_a_named_voice_is_named_in_later_transcripts(start):
    app = start(styles=[])
    remember_voices(app)
    app.send("close", window_title="Voices")
    again(app)
    app.hear("Hello.", voice="alice", length=LONG)
    eventually(lambda: "Hello." in shown(app))
    name(app, "Speaker 1", "Sarah")
    stop(app)

    again(app)
    app.hear("It's me again.", voice="alice", length=LONG)
    app.hear("And I'm new.", voice="bob", length=LONG)

    text = eventually(lambda: "And I'm new." in shown(app)) or shown(app)
    assert "Sarah  It's me again." in text
    assert "Speaker 1  And I'm new." in text


def test_with_remembering_on_a_voice_named_after_the_call_is_remembered(start):
    app = start(styles=[])
    remember_voices(app)
    app.send("close", window_title="Voices")
    again(app)
    app.hear("Hello.", voice="alice", length=LONG)
    eventually(lambda: "Hello." in shown(app))
    app.click("Stop", "Transcripts")
    eventually(app.stopped)
    name(app, "Speaker 1", "Sarah")  # once it's saved
    app.send("close", window_title="Transcripts")

    again(app)
    app.hear("Hello again.", voice="alice", length=LONG)

    eventually(lambda: "Sarah  Hello again." in shown(app))


def test_the_voices_window_lists_remembered_voices_and_can_forget_one(start):
    app = start(styles=[])
    remember_voices(app)
    app.send("close", window_title="Voices")
    again(app)
    app.hear("Hello.", voice="alice", length=LONG)
    eventually(lambda: "Hello." in shown(app))
    name(app, "Speaker 1", "Sarah")
    stop(app)
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    app.click("Voices…", "Transcripts")
    app.wait_window("Voices")
    assert "Sarah" in app.read("Voices")

    app.click("Forget", "Voices")

    eventually(lambda: "Sarah" not in app.read("Voices"))
    app.send("close", window_title="Voices")
    app.send("close", window_title="Transcripts")
    eventually(lambda: "Transcripts" not in app.send("windows")["titles"])
    again(app)
    app.hear("Hello again.", voice="alice", length=LONG)
    eventually(lambda: "Speaker 1  Hello again." in shown(app))


def test_turning_remembering_off_asks_then_forgets_every_voice(start):
    app = start(styles=[])
    remember_voices(app)
    app.send("close", window_title="Voices")
    again(app)
    app.hear("Hello.", voice="alice", length=LONG)
    eventually(lambda: "Hello." in shown(app))
    name(app, "Speaker 1", "Sarah")
    stop(app)
    assert list((app.data / "transcripts").glob("*voices.json"))

    remember_voices(app)  # untick
    app.wait_window(None)
    assert "Forget the remembered voice?" in app.read(None)
    app.click("Forget")

    eventually(lambda: "Sarah" not in app.read("Voices"))
    assert not list((app.data / "transcripts").glob("*voices.json"))
    assert "Remember voices I name" in app.read("Voices")


def test_without_the_voice_model_everyone_through_the_speakers_is_them(start):
    app = recording(start, env={"DICTATE_TEST_NO_VOICES": "1"})

    app.hear("Hello.", voice="alice", length=LONG)
    app.hear("Hi.", voice="bob", length=LONG)

    eventually(lambda: "Them  Hello. Hi." in shown(app))
    assert "Voices…" not in app.read("Transcripts")
