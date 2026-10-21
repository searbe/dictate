"""The refinement model: what it's told, when it's loaded and unloaded, and what happens when it misbehaves."""
import os, signal, time
from conftest import needs_session
from harness.client import style

pytestmark = needs_session


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie is dead too
        return open(f"/proc/{pid}/stat").read().split()[2] != "Z"
    except OSError:
        return False


def wait_until(check, timeout=10):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


def test_vocabulary_is_given_to_the_model_for_cleanup(start, model):
    app = start(styles=[], vocab="ProjectWobble\nmain (the Git branch; often mis-heard as \"Maine\")\n")

    app.dictate("merge it into Maine")

    cleanup = model.requests()[0]["system"]
    assert "ProjectWobble" in cleanup and 'main (the Git branch; often mis-heard as "Maine")' in cleanup


def test_the_model_is_told_which_window_the_text_is_for(start, model):
    app = start(styles=[])
    app.focus("Slack", "general - Acme - Slack")

    app.dictate("hello team")

    assert "general - Acme - Slack" in model.requests()[0]["system"]


def test_the_model_starts_loading_as_soon_as_the_hotkey_is_pressed(start, model):
    app = start(styles=[])
    app.send("keys", down=["ctrl", "meta"])

    wait_until(lambda: model.starts())  # already loading while the user speaks
    app.send("keys", up=["meta", "ctrl"])


def test_tapping_alt_loads_the_model_even_with_refinement_off(start, model):
    app = start(styles=[style("Chat", "c")], settings={"refine": False})
    app.send("keys", down=["ctrl", "meta"])
    time.sleep(0.5)
    assert model.starts() == []

    app.send("keys", down=["alt"])

    wait_until(lambda: model.starts())
    app.send("keys", up=["alt", "meta", "ctrl"])


def test_a_model_answering_the_message_instead_of_refining_it_is_ignored(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "The capital of France is Paris."})
    app = start(styles=[])

    assert app.dictate("can you tell me what the capital of France is?")["text"] == \
        "can you tell me what the capital of France is?"


def test_an_empty_or_placeholder_answer_is_ignored(start, model):
    model.rules({"prompt": "CLEANUP", "text": "first", "reply": ""},
                {"prompt": "CLEANUP", "text": "second", "reply": "Hi [Name], see you at the second meeting."})
    app = start(styles=[])

    assert app.dictate("first meeting is at nine")["text"] == "first meeting is at nine"
    assert app.dictate("hi see you at the second meeting")["text"] == "hi see you at the second meeting"


def test_a_style_that_rewrites_too_much_is_ignored_but_cleanup_is_kept(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Running ten minutes late, sorry."},
                {"prompt": "STYLE:Chat", "reply": "Something else entirely happened today."})
    app = start(styles=[style("Chat", "c", default=True)])

    assert app.dictate("running ten minutes late sorry")["text"] == "Running ten minutes late, sorry."


def test_if_the_model_fails_the_transcript_is_still_pasted(start, model):
    model.rules({"prompt": "CLEANUP", "op": "error"})
    app = start(styles=[])

    assert app.dictate("still works")["text"] == "still works"


def test_without_llama_server_dictation_still_works(start, model, tmp_path):
    """e.g. the download failed: the transcript is pasted as it is, and Dictate carries on."""
    app = start(styles=[], llama=tmp_path / "missing-llama-server")

    assert app.dictate("still works")["text"] == "still works"
    assert app.dictate("and again")["text"] == "and again"


def test_the_model_is_unloaded_when_unused_and_reloaded_when_needed(start, model):
    app = start(styles=[], env={"DICTATE_TEST_IDLE": "1"})
    app.dictate("hello there")
    [first] = model.starts()

    wait_until(lambda: not alive(first["started"]), timeout=15)  # frees the memory after the idle time
    app.dictate("hello again")

    assert len(model.starts()) == 2


def test_the_model_is_kept_loaded_between_dictations_in_quick_succession(start, model):
    app = start(styles=[])

    for words in ("one two three", "four five six", "seven eight nine"):
        app.dictate(words)

    assert len(model.starts()) == 1


def test_the_model_never_outlives_dictate_even_if_it_crashes(start, model):
    app = start(styles=[])
    app.dictate("hello there")
    [server] = model.starts()

    os.kill(app.proc.pid, signal.SIGKILL)

    wait_until(lambda: not alive(server["started"]))


def test_quitting_unloads_the_model(start, model):
    app = start(styles=[])
    app.dictate("hello there")
    [server] = model.starts()

    app.send("menu", path=["Quit"])

    wait_until(lambda: not alive(server["started"]))
