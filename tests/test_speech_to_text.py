"""Speech-to-text with the real models (Silero VAD + Parakeet). Deterministic: the same audio always gives the
same text. Needs the downloaded models; uses the sample recordings that come with Parakeet."""
import threading, time, wave
import numpy as np
import pytest
from conftest import MODELS, needs_models

pytestmark = [needs_models, pytest.mark.models]
RATE = 16000
ASK_NOT = "Ask not what your country can do for you. Ask what you can do for your country."


@pytest.fixture(scope="module")
def stt():
    from dictate import stt
    stt.load()
    return stt


def sample(name):
    """A bundled sample recording as 16 kHz 16-bit samples, the way Dictate records."""
    with wave.open(str(MODELS / f"parakeet/test_wavs/{name}.wav")) as w:
        audio, rate = np.frombuffer(w.readframes(w.getnframes()), np.int16), w.getframerate()
    t = np.arange(0, len(audio) / rate, 1 / RATE)
    return np.interp(t, np.arange(len(audio)) / rate, audio).astype(np.int16)


def silence(seconds):
    return np.zeros(int(RATE * seconds), np.int16)


def save(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(samples.tobytes())
    return path


def test_speech_is_transcribed_with_punctuation(stt, tmp_path):
    assert stt.transcribe(save(tmp_path / "a.wav", sample("en"))) == ASK_NOT


def test_other_languages_are_transcribed_in_their_own_language(stt, tmp_path):
    assert stt.transcribe(save(tmp_path / "a.wav", sample("de"))) == "Alles hat ein Ende, nur die Wurst hat zwei."


def test_silence_and_noise_give_no_text(stt, tmp_path):
    hiss = (np.random.default_rng(1).normal(0, 300, RATE * 2)).astype(np.int16)
    assert stt.transcribe(save(tmp_path / "quiet.wav", silence(2))) == ""
    assert stt.transcribe(save(tmp_path / "hiss.wav", hiss)) == ""


def test_transcribing_while_recording_gives_the_same_text_as_afterwards(stt, tmp_path):
    """Speech, a pause, more speech: written as a recorder would while Dictate follows the file live."""
    audio = np.concatenate([silence(0.3), sample("en"), silence(1.5), sample("en"), silence(0.3)])
    path = tmp_path / "live.wav"
    live_started = threading.Event()

    def record():  # header first, then the samples arrive in 100 ms chunks (4x faster than real time)
        with open(path, "wb") as f:
            with wave.open(str(tmp_path / "header.wav"), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            f.write((tmp_path / "header.wav").read_bytes())
            f.flush()
            live_started.wait()
            for i in range(0, len(audio), RATE // 10):
                f.write(audio[i:i + RATE // 10].tobytes())
                f.flush()
                time.sleep(0.025)

    recorder = threading.Thread(target=record)
    recorder.start()
    time.sleep(0.1)
    live = stt.Live(str(path))
    live_started.set()
    recorder.join()

    assert live.finish() == f"{ASK_NOT} {ASK_NOT}"
    assert stt.transcribe(save(tmp_path / "whole.wav", audio)) == f"{ASK_NOT} {ASK_NOT}"
