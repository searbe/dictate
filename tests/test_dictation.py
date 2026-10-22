"""Holding the hotkey, speaking and releasing: what ends up pasted, on the clipboard and in history."""
import os, time
from conftest import needs_session
from harness.client import refinement

pytestmark = needs_session


def test_speech_is_cleaned_up_copied_and_pasted(start, model):
    model.rules({"prompt": "CLEANUP", "text": "um so the meeting", "reply": "So, the meeting is at three."})
    app = start(refinements=[])
    app.focus("org.kde.kate", "notes.txt — Kate")

    pasted = app.dictate("um so the meeting is at uh three")

    assert pasted == {"type": "pasted", "terminal": False, "text": "So, the meeting is at three."}
    assert app.send("clipboard")["text"] == "So, the meeting is at three."


def test_terminals_get_the_terminal_paste_shortcut(start):
    app = start(refinements=[])
    app.focus("org.kde.konsole", "~ : bash — Konsole")

    assert app.dictate("list the files")["terminal"] is True


def test_each_dictation_is_kept_in_history_with_what_was_done_to_it(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Hello there."}, {"prompt": "REFINEMENT:Chat", "reply": "hello there!"})
    app = start(refinements=[refinement("Chat", "c", apps="slack")])
    app.focus("Slack", "general - Acme - Slack")

    app.dictate("uh hello there")

    [entry] = app.dictations()
    assert entry["text"] == "hello there!" and entry["raw"] == "uh hello there"
    assert entry["cleaned"] == "Hello there."  # each step: heard, cleaned up, refined
    assert entry["refinement"] == "Chat" and entry["cleanup"] is True
    assert entry["app"] == "Slack" and entry["title"] == "general - Acme - Slack"
    assert (app.data / "audio" / entry["audio"]).exists()  # the recording is kept for playback


def test_saying_nothing_pastes_nothing_and_leaves_no_trace(start):
    app = start(refinements=[])

    assert app.dictate(None) is None
    assert app.dictations() == []
    assert list((app.data / "audio").glob("*.wav")) == []


def test_with_refinement_off_the_raw_transcript_is_pasted_without_asking_the_model(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Should not be used."})
    app = start(refinements=[], settings={"refine": False})

    assert app.dictate("um raw words")["text"] == "um raw words"
    assert model.requests() == []
    assert app.dictations()[0]["cleanup"] is False


def test_turning_refinement_off_from_the_menu_takes_effect_and_is_remembered(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Cleaned."})
    app = start(refinements=[])
    app.send("menu", path=["Refine text"])
    assert app.dictate("um words")["text"] == "um words"
    app.stop()

    again = start(refinements=[])
    assert {"label": "Refine text", "ticked": False} in again.send("menu_items")["items"]
    assert again.dictate("um words")["text"] == "um words"


def test_recordings_are_not_kept_when_set_to_dont_keep(start):
    app = start(refinements=[], settings={"keep_audio_hours": 0})

    app.dictate("hello")

    assert "audio" not in app.dictations()[0]
    assert list((app.data / "audio").glob("*.wav")) == []


def test_old_recordings_are_deleted_when_dictate_starts(start, tmp_path):
    audio = tmp_path / "data/audio"
    audio.mkdir(parents=True)
    old, new = audio / "old.wav", audio / "new.wav"
    old.write_bytes(b"RIFF"), new.write_bytes(b"RIFF")
    two_hours_ago = time.time() - 2 * 3600
    os.utime(old, (two_hours_ago, two_hours_ago))

    start(refinements=[], settings={"keep_audio_hours": 1})

    assert not old.exists() and new.exists()


def test_holding_the_keys_down_records_once(start):
    """Keyboards repeat a held key; that mustn't restart the recording."""
    app = start(refinements=[])
    mark = app.mark()
    app.send("say", text="one long thought")
    app.send("keys", down=["ctrl", "meta"])
    app.send("keys", down=["meta", "ctrl", "meta"])  # auto-repeat
    app.send("keys", up=["meta", "ctrl"])

    assert app.result(mark)["text"] == "one long thought"
    assert sum(ev["type"] == "recording" for ev in app.events[mark:]) == 1


def test_the_keys_can_be_pressed_in_either_order(start):
    app = start(refinements=[])
    mark = app.mark()
    app.send("say", text="win first")
    app.send("keys", down=["meta"])
    app.send("keys", down=["ctrl"])
    app.send("keys", up=["ctrl", "meta"])

    assert app.result(mark)["text"] == "win first"


def test_win_alone_or_ctrl_alone_does_nothing(start):
    app = start(refinements=[])
    mark = app.mark()

    for key in ("meta", "ctrl"):
        app.send("keys", down=[key])
        app.send("keys", up=[key])

    assert not app.happened("recording", after=mark)


def test_another_key_with_ctrl_win_is_another_apps_shortcut_and_drops_the_recording(start):
    """e.g. Ctrl+Win+→ switches desktop: whatever you were saying meanwhile mustn't be pasted."""
    app = start(refinements=[])
    mark = app.mark()
    app.send("say", text="and then we talked about the budget")
    app.send("keys", down=["ctrl", "meta"])
    app.wait_for("recording", after=mark)

    app.send("keys", down=["right"], up=["right"])
    app.send("keys", up=["meta", "ctrl"])

    app.wait_for("icon", after=mark, state="idle")
    time.sleep(0.8)
    assert not app.happened("pasted", after=mark) and not app.happened("typed", after=mark)
    assert app.dictations() == []
    assert list((app.data / "audio").glob("*.wav")) == []  # the recording isn't kept either


def test_ctrl_win_pressed_while_another_key_is_held_does_not_record(start):
    """e.g. Shift held first: Shift+Ctrl+Win+→ moves a window to another desktop."""
    app = start(refinements=[])
    mark = app.mark()

    app.send("keys", down=["shift", "ctrl", "meta"])
    app.send("keys", up=["meta", "ctrl", "shift"])

    time.sleep(0.5)
    assert not app.happened("recording", after=mark)


def test_after_another_apps_shortcut_win_again_is_an_ordinary_dictation(start):
    """Ctrl+Win+→, lift Win, Win again (Ctrl held): not the gesture that starts transcribing."""
    app = start(refinements=[])
    app.send("keys", down=["ctrl", "meta", "right"], up=["right", "meta"])
    mark = app.mark()
    app.send("say", text="just a note")

    app.send("keys", down=["meta"])
    app.send("keys", up=["meta", "ctrl"])

    assert app.result(mark)["text"] == "just a note"
    assert "Transcripts" not in app.send("windows")["titles"]
