"""Transcribe mode: Ctrl+Win, lift Win, Win again, and everything said through the speakers ("Them") and into
the microphone ("Me") is written into a transcript as it's heard, shown at the top of the Transcripts window,
until it's stopped the same way, or with the Stop button."""
import re, time
import pytest
from conftest import needs_models, needs_session, sample_speech
from harness.client import eventually

pytestmark = needs_session
SAID = "ask not what your country can do for you"


def started(start, **kw):
    app = start(styles=[], **kw)
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def shows(app, *texts):
    """The transcript window comes to show each of texts."""
    eventually(lambda: all(t in app.transcript() for t in texts))
    return app.transcript()


def test_what_the_speakers_and_the_microphone_hear_is_written_down_as_it_is_said(start):
    app = started(start)

    app.hear("So what do you think about the budget?")
    app.hear("I think we should cut it.", source="mic")

    text = shows(app, "So what do you think about the budget?", "I think we should cut it.")
    assert re.search(r"\d\d:\d\d:\d\d Them  So what do you think about the budget\?", text)
    assert re.search(r"\d\d:\d\d:\d\d Me  I think we should cut it\.", text)
    saved = app.transcript_file()
    assert "**" in saved and "Them:** So what do you think about the budget?" in saved
    assert "Me:** I think we should cut it." in saved


def test_one_person_talking_on_is_one_paragraph(start):
    app = started(start)

    app.hear("First point.")
    app.hear("Second point.")
    app.hear("Fair enough.", source="mic")

    text = shows(app, "Fair enough.")
    assert "First point. Second point." in text
    assert text.count("Them") == 1


def test_starting_it_neither_pastes_nor_keeps_a_dictation(start):
    app = start(styles=[])
    mark = app.mark()
    app.send("say", text="hello there")

    app.ctrl_win_win()
    app.wait_window("Transcripts")
    time.sleep(1.5)  # long enough for a dictation to have been pasted

    assert not app.happened("pasted", after=mark) and not app.happened("typed", after=mark)
    assert app.history() == []


def test_doing_it_again_stops_and_saves_it(start):
    app = started(start)
    app.hear("Before the end.")
    shows(app, "Before the end.")

    app.ctrl_win_win()
    eventually(lambda: app.stopped())
    app.hear("After the end.")

    time.sleep(0.5)
    assert "After the end." not in app.transcript()
    assert "Before the end." in app.transcript_file() and "After the end." not in app.transcript_file()
    assert app.history() == []


def test_the_stop_button_stops_it(start):
    app = started(start)
    app.hear("Hello.")

    app.click("Stop", "Transcripts")

    eventually(lambda: app.stopped())
    assert "Copy all" in app.read("Transcripts") and "Open file" in app.read("Transcripts")
    assert "Hello." in app.transcript_file()


def test_closing_the_window_keeps_it_going(start):
    app = started(start)

    app.send("close", window_title="Transcripts")
    app.hear("Still listening.")
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    assert "Recording now" in app.read("Transcripts")
    shows(app, "Still listening.")
    assert {"label": "Stop transcribing"} in app.send("menu_items")["items"]


def test_dictating_while_transcribing_pastes_as_usual_and_stays_out_of_the_transcript(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Note to self: buy milk."})
    app = started(start)
    mark = app.dictate("note to self buy milk", wait=False)
    app.hear("note to self buy milk", source="mic")  # the transcript's microphone hears the dictation too
    app.hear("Meanwhile, on the call.")  # the call goes on through the speakers
    app.send("keys", up=["meta", "ctrl"])

    assert app.result(mark)["text"] == "Note to self: buy milk."
    time.sleep(0.3)
    app.hear("And after it.", source="mic")
    text = shows(app, "Meanwhile, on the call.", "And after it.")
    assert "milk" not in text.lower()


def test_pause_leaves_out_what_is_said_until_resume(start):
    app = started(start)
    app.click("Pause", "Transcripts")
    app.hear("Off the record.")
    app.hear("Me neither.", source="mic")
    time.sleep(0.3)

    app.click("Resume", "Transcripts")
    time.sleep(0.3)
    app.hear("Back on the record.")

    text = shows(app, "Back on the record.")
    assert "Off the record." not in text and "Me neither." not in text


def test_the_speakers_picked_up_by_the_microphone_are_not_written_down_twice(start):
    """On a laptop's speakers, the microphone hears the other person too: the same words, at the same time."""
    app = started(start)

    app.hear("Can everyone hear me okay?")
    app.hear("Can everyone hear me ok", source="mic")
    app.hear("Yes, loud and clear.", source="mic")

    text = shows(app, "Can everyone hear me okay?", "Yes, loud and clear.")
    assert "Can everyone hear me ok\n" not in text + "\n" and text.count("Can everyone") == 1


def test_playing_a_recording_from_history_is_not_transcribed(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Played back."})
    app = start(styles=[], settings={"keep_audio_hours": 24})
    app.dictate("played back")
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.send("menu", path=["History"])
    app.wait_window("History")

    app.click("▶ Play", "History")
    app.hear("Played back.")
    app.click("■ Stop", "History")
    time.sleep(0.3)
    app.hear("Live again.")

    text = shows(app, "Live again.")
    assert "Played back." not in text


def test_it_can_be_started_and_stopped_from_the_menu(start):
    app = start(styles=[])

    app.send("menu", path=["Transcribe this computer"])
    app.wait_window("Transcripts")
    assert {"label": "Stop transcribing"} in app.send("menu_items")["items"]
    app.send("menu", path=["Stop transcribing"])

    eventually(lambda: app.stopped())
    assert {"label": "Transcribe this computer"} in app.send("menu_items")["items"]


def test_an_ordinary_dictation_is_not_mistaken_for_it(start):
    """Letting go of Win before Ctrl, or pressing Win again after a moment, is just dictating."""
    app = start(styles=[])
    mark = app.mark()
    app.send("say", text="first")
    app.send("keys", down=["ctrl", "meta"])
    app.wait_for("recording", after=mark)
    app.send("keys", up=["meta"])
    time.sleep(1.2)  # Ctrl still held, but too long to be the gesture
    app.send("say", text="second")
    app.send("keys", down=["meta"])
    app.send("keys", up=["meta", "ctrl"])

    eventually(lambda: [e["text"] for e in app.history()] == ["first", "second"])
    assert "Transcripts" not in app.send("windows")["titles"]


def test_the_transcript_recordings_follow_the_keep_recordings_setting(start):
    app = started(start, settings={"keep_audio_hours": 0})
    app.hear("Hello.")
    app.click("Stop", "Transcripts")
    eventually(lambda: app.stopped())

    eventually(lambda: [f.suffix for f in (app.data / "transcripts").iterdir()] == [".md"])
    assert "Hello." in app.transcript_file()


@needs_models
@pytest.mark.models
def test_speech_through_the_speakers_is_transcribed_by_the_real_model(start, tmp_path):
    app = started(start, env={"DICTATE_TEST_SPEAKERS": str(sample_speech(tmp_path / "speech.wav"))})

    app.click("Stop", "Transcripts")  # the sample ends mid-word: its last stretch is transcribed on stopping
    eventually(lambda: SAID in app.transcript_file().lower(), timeout=60)
    assert "Me:**" not in app.transcript_file()  # the microphone heard silence
