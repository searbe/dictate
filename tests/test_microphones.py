"""Choosing the microphone: Dictate records the first connected one in the order set on the Settings page, and
starts out with the system's default one first, so nothing changes until you change the order."""
import time

from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session

WEBCAM = ["alsa_input.usb-Logitech_StreamCam", "StreamCam Analog Stereo"]
HEADSET = ["alsa_input.usb-Corsair_HS70", "CORSAIR HS70 Pro Wireless Gaming Headset Mono"]


def recorded_with(app):
    mark = app.mark()
    app.dictate("hello")
    return app.wait_for("recording", after=mark)["mic"]


def open_settings(app):
    app.send("menu", path=["Settings…"])
    app.wait_window("Settings")


def test_the_default_microphone_is_used_until_the_order_is_changed(start):
    app = start(refinements=[])
    app.send("microphones", connected=[WEBCAM, HEADSET])

    assert recorded_with(app) == WEBCAM[0]


def test_moving_a_microphone_up_records_with_it(start):
    app = start(refinements=[])
    app.send("microphones", connected=[WEBCAM, HEADSET])
    open_settings(app)
    texts = app.read("Settings")
    assert texts.index(WEBCAM[1]) < texts.index("In use") < texts.index(HEADSET[1])

    app.click(f"Move {HEADSET[1]} up", window="Settings")

    eventually(lambda: app.read("Settings").index(HEADSET[1]) < app.read("Settings").index(WEBCAM[1]))
    assert recorded_with(app) == HEADSET[0]


def test_when_the_preferred_microphone_is_unplugged_the_next_one_is_used_and_it_is_used_again_once_back(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM])
    assert recorded_with(app) == WEBCAM[0]

    app.send("microphones", connected=[WEBCAM, HEADSET])
    assert recorded_with(app) == HEADSET[0]


def test_transcribe_mode_records_the_preferred_microphone(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM, HEADSET])
    mark = app.mark()

    app.ctrl_win_win()

    assert app.wait_for("recording", after=mark, speakers=False)["mic"] == HEADSET[0]


def test_a_microphone_not_connected_can_be_forgotten(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM])
    open_settings(app)
    assert "Not connected" in app.read("Settings")

    app.click(f"Forget {HEADSET[1]}", window="Settings")

    eventually(lambda: HEADSET[1] not in app.read("Settings"))
    assert WEBCAM[1] in app.read("Settings")


def test_during_a_call_it_moves_to_a_preferred_microphone_once_it_is_there_and_back(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM])  # (the headset's switched off)
    mark = app.mark()
    app.ctrl_win_win()
    assert app.wait_for("recording", after=mark, speakers=False)["mic"] == WEBCAM[0]

    app.send("microphones", connected=[WEBCAM, HEADSET], noticed=False)  # (switched on, mid-call)

    moved = app.wait_for("recording_moved", after=mark)
    assert moved["mic"] == HEADSET[0] and not moved["speakers"]  # (the microphone's recording, not the speakers')
    app.wait_for("listening_anew", after=mark, source="mic")  # (its speech detector: not still tuned to the other)
    app.send("microphones", connected=[WEBCAM], noticed=False)  # (and off again)
    app.wait_for("recording_moved", after=mark, mic=WEBCAM[0])


def test_a_dictation_moves_too_if_the_microphone_changes_while_it_is_recorded(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM, HEADSET])
    mark = app.mark()
    app.send("say", text="hello")
    app.send("keys", down=["ctrl", "meta"])
    assert app.wait_for("recording", after=mark)["mic"] == HEADSET[0]

    app.send("microphones", connected=[WEBCAM])  # (the headset switched off mid-sentence)

    app.wait_for("recording_moved", after=mark, mic=WEBCAM[0])
    app.send("keys", up=["meta", "ctrl"])


def test_a_recording_that_has_stopped_is_not_moved(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM, HEADSET])
    app.dictate("hello")
    mark = app.mark()

    app.send("microphones", connected=[WEBCAM])

    time.sleep(0.5)
    assert not app.happened("recording_moved", after=mark)


def test_the_settings_page_shows_a_microphone_connected_or_gone_while_it_is_open(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM])
    open_settings(app)
    texts = app.read("Settings")
    assert texts[texts.index(HEADSET[1]) + 1] == "Not connected"

    app.send("microphones", connected=[WEBCAM, HEADSET])  # (switched on)

    eventually(lambda: app.read("Settings")[app.read("Settings").index(HEADSET[1]) + 1] == "In use")
    app.send("microphones", connected=[WEBCAM])
    eventually(lambda: app.read("Settings")[app.read("Settings").index(HEADSET[1]) + 1] == "Not connected")


def test_the_microphones_are_still_listed_when_settings_is_shown_again(start):
    app = start(refinements=[], settings={"microphones": [HEADSET, WEBCAM]})
    app.send("microphones", connected=[WEBCAM, HEADSET])
    open_settings(app)

    app.send("select", row="Dictations", window_title="Settings")
    app.send("select", row="Settings", window_title="Dictations")

    texts = app.read("Settings")
    assert HEADSET[1] in texts and WEBCAM[1] in texts and "In use" in texts
