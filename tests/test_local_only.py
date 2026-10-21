"""The real thing, end to end: the real speech model hears a real recording, and the real llama-server and
refinement model clean it up. Only the keyboard, microphone and paste are stand-ins.

scripts/prove_local.py runs this inside a sealed sandbox with no network and records every network call that
every process makes, to show that Dictate works entirely on this computer."""
import shutil, subprocess, sys
import pytest
from conftest import MODELS, ROOT, needs_models, needs_session, sample_speech

LLAMA = ROOT / "bin/llama/llama-server"
pytestmark = [needs_session, needs_models, pytest.mark.models,
              pytest.mark.skipif(not LLAMA.exists() or not list(MODELS.glob("qwen*.gguf")),
                                 reason="needs llama.cpp and the refinement models: run the setup script")]
SAID = "ask not what your country can do for you"


def test_a_real_dictation_is_transcribed_and_refined_on_this_computer(start, tmp_path):
    from dictate.refine import CLEANUP
    shout = {"name": "Shout", "key": "s", "apps": "",
             "prompt": "Rewrite the message in CAPITAL LETTERS. Change nothing else."}  # unmistakably the model's work
    app = start(styles=[shout], cleanup=CLEANUP, llama=LLAMA,
                env={"DICTATE_TEST_SPEECH": str(sample_speech(tmp_path / "speech.wav"))})
    app.focus("org.kde.kate", "notes.txt — Kate")

    cleaned = app.dictate("(the recording)", timeout=300)
    shouted = app.dictate("(the recording)", alt=True, letter="s", timeout=300)

    assert SAID in cleaned["text"].lower()  # heard by the speech model
    assert SAID.upper() in shouted["text"]  # rewritten by the refinement model
    assert [e.get("style") for e in app.history()] == [None, "Shout"]


@pytest.mark.skipif(not shutil.which("bwrap") or not shutil.which("strace"), reason="needs bubblewrap and strace")
def test_the_local_only_proof_passes_and_catches_a_deliberate_leak():
    """scripts/prove_local.py, as a user would run it."""
    proof = subprocess.run([sys.executable, str(ROOT / "scripts/prove_local.py")], capture_output=True, text=True,
                           timeout=600)
    assert proof.returncode == 0, proof.stdout[-4000:] + proof.stderr[-2000:]
    assert "a test program that tries to go online is caught: yes" in proof.stdout
    assert "RESULT: LOCAL ONLY" in proof.stdout
