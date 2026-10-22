"""Telling the speakers picked up again by the microphone from you speaking (echo.py). The rooms here are
made up: the speakers' sound a moment later, quieter, duller and ringing on. How it does in a real room is
in echo.py's notes."""
import numpy as np
import soundfile
from conftest import needs_models, sample_speech
from dictate import echo

pytestmark = needs_models
RATE = 16000


def speech(tmp_path):
    return soundfile.read(str(sample_speech(tmp_path / "speech.wav")), dtype="float32")[0]


def room(sound, delay=0.06):
    """sound as a microphone across a room hears it from the speakers."""
    out = np.zeros(len(sound) + RATE // 2, np.float32)
    for after, loud in ((delay, 0.4), (delay + 0.015, 0.2), (delay + 0.05, 0.1), (delay + 0.12, 0.05)):
        at = int(after * RATE)
        out[at:at + len(sound)] += loud * sound
    out = np.convolve(out, np.ones(4) / 4, "same")  # a room dulls it
    return (out + np.random.default_rng(1).normal(0, 0.001, len(out))).astype(np.float32)


def played(sound):
    e = echo.Echo()
    data = (np.clip(sound, -1, 1) * 32767).astype(np.int16).tobytes()
    for i in range(0, len(data), RATE // 5):  # as the speakers' recorder passes it on
        e.played(data[i:i + RATE // 5])
    return e


def test_the_speakers_heard_by_the_microphone_are_an_echo(tmp_path):
    them = speech(tmp_path)
    e = played(np.concatenate([them, np.zeros(RATE)]))

    assert e.echo(0.0, room(them))
    assert e.echo(2.0, room(them)[2 * RATE:5 * RATE])  # part of what they said


def test_a_quieter_or_slower_room_is_an_echo_too(tmp_path):
    them = speech(tmp_path)
    e = played(np.concatenate([them, np.zeros(RATE)]))

    assert e.echo(0.0, 0.2 * room(them))
    assert e.echo(0.0, room(them, delay=0.3))


def test_you_speaking_while_the_speakers_are_quiet_is_not(tmp_path):
    you = speech(tmp_path)
    e = played(np.zeros(len(you) + RATE, np.float32))

    assert not e.echo(0.0, you)


def test_you_speaking_over_the_speakers_is_not(tmp_path):
    them = speech(tmp_path)
    you = np.interp(np.arange(0, len(them), 1.2), np.arange(len(them)), them).astype(np.float32)  # another voice
    e = played(np.concatenate([them, np.zeros(RATE)]))
    mic = room(them)
    mic[RATE:RATE + len(you)] += 0.5 * you[:len(mic) - RATE]

    assert not e.echo(1.0, mic[RATE:RATE + 3 * RATE])


def test_only_the_last_two_minutes_of_the_speakers_are_kept(tmp_path):
    """So a long call doesn't fill the memory; a stretch is checked within seconds of being said."""
    them = speech(tmp_path)
    e = played(np.concatenate([them, np.zeros(150 * RATE, np.float32)]))

    assert not e.echo(0.0, room(them))  # forgotten


def cancelled(sound):
    """What an echo canceller leaves of the speakers' sound across a room: louder and quieter by turns, with a
    hiss of its own; so much of it isn't quite the speakers' sound (a real one, through PipeWire's, left 40-70%)."""
    rng = np.random.default_rng(0)
    echoed = room(sound)
    wobble = np.repeat(rng.uniform(0.1, 1.0, len(echoed) // 1600 + 1), 1600)[:len(echoed)]
    return (echoed * wobble + 0.3 * rng.normal(0, 1, len(echoed)) * np.abs(echoed)).astype(np.float32)


def test_an_echo_left_by_an_echo_canceller_is_an_echo_once_echoes_have_been_heard(tmp_path):
    them = np.concatenate([speech(tmp_path)] * 3)
    e = played(np.concatenate([them, np.zeros(RATE)]))
    left = cancelled(them)[5 * RATE:int(6.5 * RATE)]

    assert not e.echo(5.0, left)  # unsure, till it knows how loud an echo is
    for at in (0, 2, 4):
        assert e.echo(at, room(them)[at * RATE:(at + 2) * RATE])
    assert e.echo(5.0, left)


def test_you_speaking_over_what_an_echo_canceller_left_is_not(tmp_path):
    them = np.concatenate([speech(tmp_path)] * 3)
    you = np.interp(np.arange(0, len(them), 1.25), np.arange(len(them)), them).astype(np.float32)  # another voice
    e = played(np.concatenate([them, np.zeros(RATE)]))
    for at in (0, 2, 4):
        e.echo(at, room(them)[at * RATE:(at + 2) * RATE])
    mic = cancelled(them)[5 * RATE:int(6.5 * RATE)] + you[5 * RATE:int(6.5 * RATE)]

    assert not e.echo(5.0, mic)
