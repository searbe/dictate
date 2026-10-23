"""Shared fixtures. Run the suite with `python scripts/test.py`: it gives the tests their own invisible
desktop (a headless KWin, or Xvfb) and their own D-Bus, so nothing touches your real session, your
running Dictate, or your data. Tests that need that isolation skip under a bare `pytest`."""
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.client import Dictate

ROOT = Path(__file__).resolve().parent.parent
ISOLATED = os.environ.get("DICTATE_TEST_SESSION") == "1"
KWIN = os.environ.get("DICTATE_TEST_KWIN") == "1"  # a real (headless) KWin is running the session
MODELS = ROOT / "models"

needs_session = pytest.mark.skipif(not ISOLATED, reason="needs the isolated desktop: run python scripts/test.py")
needs_kwin = pytest.mark.skipif(not KWIN, reason="needs a headless KWin (KDE): run python scripts/test.py on KDE")
needs_models = pytest.mark.skipif(not (MODELS / "parakeet").exists() or not (MODELS / "silero_vad.onnx").exists(),
                                  reason="needs the speech models: run the setup script")


def sample_speech(path):
    """The sample that comes with the speech model ("... ask not what your country can do for you ..."),
    saved to path as Dictate records: 16 kHz, 16-bit mono."""
    with wave.open(str(MODELS / "parakeet/test_wavs/en.wav")) as w:
        audio, rate = np.frombuffer(w.readframes(w.getnframes()), np.int16), w.getframerate()
    t = np.arange(0, len(audio) / rate, 1 / 16000)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(np.interp(t, np.arange(len(audio)) / rate, audio).astype(np.int16).tobytes())
    return path


class FakeModel:
    """The refinement model: set rules for its answers (see harness/fake_llama.py), read what it was asked."""

    def __init__(self, folder):
        self.rules_file, self.log_file = folder / "rules.json", folder / "requests.jsonl"
        os.environ["FAKE_LLAMA_RULES"], os.environ["FAKE_LLAMA_LOG"] = str(self.rules_file), str(self.log_file)

    def rules(self, *rules):
        self.rules_file.write_text(json.dumps(list(rules)))

    def _log(self):
        return [json.loads(line) for line in self.log_file.read_text().splitlines()] if self.log_file.exists() else []

    def requests(self):
        return [r for r in self._log() if "system" in r]

    def starts(self):
        return [r for r in self._log() if "started" in r]


@pytest.fixture
def model(tmp_path):
    folder = tmp_path / "model"
    folder.mkdir()
    return FakeModel(folder)


@pytest.fixture
def start(tmp_path, model):
    """start(refinements=..., vocab=..., settings=...) runs a fresh Dictate with its own home and data folders.
    refinements: the "refinements" list for refinements.json (with a "CLEANUP" cleanup prompt); settings: state.json."""
    running = []

    def start(refinements=None, vocab=None, settings=None, cleanup="CLEANUP",
              llama=ROOT / "tests/harness/fake_llama.py", env=None):
        home, data = tmp_path / "home", tmp_path / "data"
        home.mkdir(exist_ok=True)
        data.mkdir(exist_ok=True)
        if refinements is not None:
            (data / "refinements.json").write_text(json.dumps({"cleanup": cleanup, "refinements": refinements}))
        if vocab is not None:
            (data / "vocab.txt").write_text(vocab)
        if settings is not None:
            (data / "state.json").write_text(json.dumps(settings))
        app = Dictate(home, data, llama, env)
        running.append(app)
        return app

    yield start
    for app in running:
        app.stop()

