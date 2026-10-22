"""Transcribe mode: Ctrl+Win, lift Win, Win again, and everything said through the speakers (by "Speaker 1",
"Speaker 2", …: see test_voices.py) and into the microphone ("Me") is written into a transcript as it's heard,
shown at the top of the Transcripts window, until it's stopped the same way, or with the Stop button."""
import os, re, time
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
    assert re.search(r"\d\d:\d\d:\d\d Speaker 1  So what do you think about the budget\?", text)
    assert re.search(r"\d\d:\d\d:\d\d Me  I think we should cut it\.", text)
    saved = app.transcript_file()
    assert "**" in saved and "Speaker 1:** So what do you think about the budget?" in saved
    assert "Me:** I think we should cut it." in saved


def test_one_person_talking_on_is_one_paragraph(start):
    app = started(start)

    app.hear("First point.")
    app.hear("Second point.")
    app.hear("Fair enough.", source="mic")

    text = shows(app, "Fair enough.")
    assert "First point. Second point." in text
    assert text.count("Speaker 1") == 1


def test_starting_it_neither_pastes_nor_keeps_a_dictation(start):
    app = start(styles=[])
    mark = app.mark()
    app.send("say", text="hello there")

    app.ctrl_win_win()
    app.wait_window("Transcripts")
    time.sleep(1.5)  # long enough for a dictation to have been pasted

    assert not app.happened("pasted", after=mark) and not app.happened("typed", after=mark)
    assert app.dictations() == []


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
    assert app.dictations() == []


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


def test_an_echo_of_two_of_their_stretches_at_once_is_not_written_down(start):
    """The microphone pauses where the speakers don't, so it can hear two of their stretches as one."""
    app = started(start)

    app.hear("Then I'll put this")
    app.hear("at the very end.")
    app.hear("Then I'll put this at the very end.", source="mic")
    app.hear("Sounds good.", source="mic")

    text = shows(app, "at the very end.", "Sounds good.")
    assert "Me  Then" not in text and text.count("Then I'll put this") == 1


def test_the_microphone_is_recorded_with_the_speakers_taken_out_of_it(start):
    app = started(start)

    assert app.happened("recording", speakers=False, echo_cancel=True)
    assert app.happened("recording", speakers=True, echo_cancel=False)


def test_playing_a_recording_from_history_is_not_transcribed(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Played back."})
    app = start(styles=[], settings={"keep_audio_hours": 24})
    app.dictate("played back")
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.send("menu", path=["Dictations"])
    app.wait_window("Dictations")

    app.click("Play", "Dictations")
    app.hear("Played back.")
    app.click("Stop", "Dictations")
    time.sleep(0.3)
    app.hear("Live again.")
    app.send("select", row="Transcripts", window_title="Dictations")  # back to the transcript, in the sidebar

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

    eventually(lambda: [e["text"] for e in app.dictations()] == ["first", "second"])
    assert "Transcripts" not in app.send("windows")["titles"]


def test_a_calls_recordings_follow_their_own_keep_setting(start):
    app = started(start, settings={"keep_call_hours": 0, "keep_audio_hours": 24})
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
    assert "Speaker 1:**" in app.transcript_file()  # its voice, told apart by the real voice model
    assert "Me:**" not in app.transcript_file()  # the microphone heard silence


def test_what_is_being_said_shows_before_the_pause_and_is_then_replaced(start):
    app = started(start)

    app.hear_so_far("So the plan is")
    shows(app, "…  So the plan is")
    app.hear("So the plan is to ship on Monday.")

    text = shows(app, "Speaker 1  So the plan is to ship on Monday.")
    assert "…" not in text
    assert "So the plan is to ship on Monday." in app.transcript_file()


def test_what_is_being_said_is_not_saved_until_it_is_transcribed_whole(start):
    app = started(start)

    app.hear_so_far("Half a sent")
    shows(app, "Half a sent")

    assert "Half a sent" not in app.transcript_file()


def test_a_dictation_does_not_show_up_while_it_is_being_said(start):
    app = started(start)
    app.dictate("note to self", wait=False)

    app.hear_so_far("note to self", source="mic")
    app.hear_so_far("On the call meanwhile")

    shows(app, "On the call meanwhile")
    assert "note to self" not in app.transcript()
    app.send("keys", up=["meta", "ctrl"])


def test_nothing_shows_while_paused(start):
    app = started(start)
    app.click("Pause", "Transcripts")

    app.hear_so_far("Off the record")
    app.hear("Still off.")

    app.click("Resume", "Transcripts")
    time.sleep(0.3)
    app.hear("Back on.")
    text = shows(app, "Back on.")
    assert "Off the record" not in text and "Still off." not in text


@needs_models
@pytest.mark.models
def test_a_stretch_cut_between_voices_loses_no_words_with_the_real_models(start, tmp_path):
    """Two voices without a pause: the stretch is transcribed whole, then cut between words where the voice
    changes, so every word is kept, once, in order. (The second voice is the sample sped up by a fifth;
    scripts/bench_voices.py measures how well real different voices are told apart.)"""
    import numpy as np, soundfile
    voice = soundfile.read(str(sample_speech(tmp_path / "one.wav")), dtype="float32")[0]
    other = np.interp(np.arange(0, len(voice), 1.2), np.arange(len(voice)), voice)
    both = tmp_path / "both.wav"
    soundfile.write(str(both), np.concatenate([voice, other]), 16000, subtype="PCM_16")
    app = started(start, env={"DICTATE_TEST_SPEAKERS": str(both)})

    app.click("Stop", "Transcripts")
    eventually(lambda: app.transcript_file().lower().count("country") == 4, timeout=60)

    said = " ".join(re.sub(r"\*\*[^*]+:\*\*", " ", app.transcript_file().split("\n", 3)[3]).split()).lower()
    whole = "ask not what your country can do for you. ask what you can do for your country."
    assert said == f"{whole} {whole}"


@needs_models
@pytest.mark.models
def test_the_speakers_echoing_into_the_microphone_are_not_you_with_the_real_models(start, tmp_path):
    """Without headphones: the microphone hears them through the speakers (here, a made-up room: see
    test_echo.py), then you say the same once they've stopped."""
    import numpy as np, soundfile
    from test_echo import room
    them = soundfile.read(str(sample_speech(tmp_path / "speech.wav")), dtype="float32")[0]
    gap = np.zeros(16000 * 3, np.float32)
    speakers, mic = tmp_path / "speakers.wav", tmp_path / "mic.wav"
    soundfile.write(str(speakers), np.concatenate([them, gap, np.zeros_like(them)]), 16000, subtype="PCM_16")
    echoed = room(them)
    soundfile.write(str(mic), np.concatenate([echoed, gap[len(echoed) - len(them):], them]), 16000, subtype="PCM_16")
    app = started(start, env={"DICTATE_TEST_SPEAKERS": str(speakers), "DICTATE_TEST_SPEECH": str(mic)})

    app.click("Stop", "Transcripts")
    eventually(lambda: app.transcript_file().count("country") >= 4, timeout=60)
    time.sleep(1)  # for anything more to arrive

    said = re.findall(r"\*\*\S+ (.+?):\*\* ([^\n]*)", app.transcript_file())
    assert sum(t.lower().count("ask not") for who, t in said if who == "Speaker 1") == 1
    assert sum(t.lower().count("ask not") for who, t in said if who == "Me") == 1


def test_a_transcript_where_nothing_was_heard_is_not_kept(start):
    app = started(start)

    app.ctrl_win_win()

    eventually(lambda: not list((app.data / "transcripts").glob("*")))  # nor its recordings
    assert "No transcripts yet" in app.read("Transcripts")


def test_call_recordings_are_kept_longer_than_dictations_if_set_to(start, tmp_path):
    """Dictations' recordings and calls' each go when their own setting says."""
    data = tmp_path / "data"
    (data / "audio").mkdir(parents=True)
    (data / "transcripts").mkdir()
    two_days_ago = time.time() - 48 * 3600
    for f in (data / "audio/old.wav", data / "transcripts/2026-10-19 10.00.00 them.ogg"):
        f.write_bytes(b"audio")
        os.utime(f, (two_days_ago, two_days_ago))

    start(styles=[], settings={"keep_audio_hours": 24, "keep_call_hours": 168})

    eventually(lambda: not (data / "audio/old.wav").exists())
    assert (data / "transcripts/2026-10-19 10.00.00 them.ogg").exists()
