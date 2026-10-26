"""A stopped call's final pass (its last topics and final summary) waits for the graphics card, where the careful
model runs, rather than using the rough one on the CPU: meanwhile the capsule shows a sand timer, and clicking it
says what's waiting and for how long, with Use the CPU and Keep waiting. It survives Dictate quitting."""
import json
import time

from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
SUMMARY = "running summary of a meeting"  # in the summary prompt
FINAL = "## Overview\nThey agreed the budget."
LIVE = "## Overview\nThey're looking at the budget."
RULES = ({"prompt": SUMMARY, "user": "has ended", "reply": FINAL}, {"prompt": SUMMARY, "reply": LIVE})
POPUP = "Waiting for the graphics card"


def call(start, model, gpu="busy"):
    """A call heard with the graphics card gpu, and stopped."""
    model.rules(*RULES)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": gpu})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("Shall we look at the budget?")
    eventually(lambda: LIVE.split("\n")[1] in (app.transcript_file() or ""))
    app.click("Stop", "Transcripts")
    eventually(lambda: app.stopped())
    return app


def finals(model):
    return [r for r in model.requests() if SUMMARY in r["system"] and "has ended" in r["user"]]


def on_gpu(model):
    return "Vulkan0" in model.starts()[-1]["args"]


def summary_json(app):
    return json.loads(next((app.data / "transcripts").glob("* summary.json")).read_text())


def test_with_the_graphics_card_busy_the_final_summary_waits_for_it_with_a_sand_timer(start, model):
    app = call(start, model)

    time.sleep(1)
    assert finals(model) == []
    icon = app.send("icon")
    assert icon["waiting"] and icon["status"] == "Waiting for the graphics card to summarise 1 call"
    assert summary_json(app)["waiting"]  # (so it's done even if Dictate quits first)

    app.send("gpu", state="free")

    eventually(lambda: FINAL.split("\n")[1] in app.transcript_file())
    assert on_gpu(model)
    assert not app.send("icon")["waiting"] and "waiting" not in summary_json(app)


def test_with_the_graphics_card_free_it_does_not_wait(start, model):
    app = call(start, model, gpu="free")

    eventually(lambda: FINAL.split("\n")[1] in app.transcript_file())
    assert not app.send("icon")["waiting"]


def test_clicking_the_sand_timer_says_what_is_waiting_and_use_the_cpu_does_it_now(start, model):
    app = call(start, model)
    eventually(lambda: app.send("icon")["waiting"])

    app.send("click_icon")

    app.wait_window(POPUP)
    texts = " ".join(app.read(POPUP))
    assert "The call at" in texts and "waiting" in texts and "Summarise on the CPU now instead?" in texts
    app.click("Use the CPU", POPUP)
    eventually(lambda: FINAL.split("\n")[1] in app.transcript_file())
    assert not on_gpu(model)
    assert POPUP not in app.send("windows")["titles"]


def test_keep_waiting_keeps_waiting(start, model):
    app = call(start, model)
    eventually(lambda: app.send("icon")["waiting"])
    app.send("click_icon")
    app.wait_window(POPUP)

    app.click("Keep waiting", POPUP)

    eventually(lambda: POPUP not in app.send("windows")["titles"])
    time.sleep(1)
    assert finals(model) == [] and app.send("icon")["waiting"]


def test_the_transcript_says_its_summary_is_waiting_with_use_the_cpu(start, model):
    app = call(start, model)
    app.click("Summary", "Transcripts")

    eventually(lambda: "Waiting for the graphics card to write the final summary." in app.read("Transcripts"))
    app.click("Use the CPU", "Transcripts")

    eventually(lambda: FINAL.split("\n")[1] in app.transcript_file())
    eventually(lambda: "The final summary" in app.read("Transcripts"))


def test_a_final_pass_still_waiting_when_dictate_quits_is_done_when_it_starts_again(start, model):
    app = call(start, model)
    eventually(lambda: app.send("icon")["waiting"])
    app.stop()

    app = start(refinements=[], env={"DICTATE_TEST_GPU": "free"})

    eventually(lambda: FINAL.split("\n")[1] in app.transcript_file())
    assert "## Summary\n\n### Overview\nThey agreed the budget." in app.transcript_file()
    assert "waiting" not in summary_json(app)


def test_quitting_mid_call_leaves_its_final_pass_for_next_time(start, model):
    model.rules(*RULES)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("Shall we look at the budget?")
    eventually(lambda: LIVE.split("\n")[1] in (app.transcript_file() or ""))
    app.stop()
    assert summary_json(app)["waiting"]

    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})

    assert app.send("icon")["waiting"]


def test_a_transcript_deleted_while_it_waits_stays_deleted(start, model):
    app = call(start, model)
    eventually(lambda: app.send("icon")["waiting"])

    app.click("Delete", "Transcripts")
    app.click("Delete")
    app.send("gpu", state="free")

    eventually(lambda: not app.send("icon")["waiting"])
    time.sleep(1)
    assert finals(model) == [] and list((app.data / "transcripts").glob("*.md")) == []


def test_slices_of_a_long_call_wait_for_the_graphics_card_too(start, model):
    part = "Summarise just this part"
    model.rules({"prompt": SUMMARY, "user": part, "reply": "## Discussed\n- The budget."},
                {"prompt": SUMMARY, "user": "summaries of its parts", "reply": FINAL}, *RULES)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy", "DICTATE_TEST_SLICE": "5"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("Shall we look at the budget today?")
    app.hear("And we need to hire a designer soon.")
    time.sleep(1.5)
    assert not [r for r in model.requests() if part in r["user"]]  # (the smaller model's would be rough)
    app.click("Stop", "Transcripts")
    eventually(lambda: app.stopped())

    app.send("gpu", state="free")

    eventually(lambda: FINAL.split("\n")[1] in app.transcript_file())
    assert len(summary_json(app)["slices"]) == 2 and on_gpu(model)
