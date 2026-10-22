"""The live summary: while a conversation is transcribed, the Summary tab beside Topics has a summary of it (what
it's about, what was discussed and agreed, the action points), kept up to date as it goes on, with a final pass
when it's stopped; saved at the top of the transcript. Its prompt is in Styles. The model writes it (here, its
stand-in: see harness/fake_llama.py)."""
import json
from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
SUMMARY = "running summary of a meeting"  # in the default prompt
FIRST = "## Overview\nThey're looking at the budget.\n## Action points\n- **Me:** cut the travel costs."
LATER = "## Overview\nThey're looking at the budget, then hiring.\n## Agreed\n- Hire a designer."
FINAL = "## Overview\nThey agreed the budget and to hire a designer.\n## Action points\n- **Speaker 1:** post the job."


def summary_rule(reply, text="", user=""):
    return {"prompt": SUMMARY, "text": text, "user": user, "reply": reply}


def recording(start, model, *rules):
    model.rules(*rules)
    app = start(styles=[])
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def test_the_summary_tab_shows_a_summary_of_the_conversation_so_far(start, model):
    app = recording(start, model, summary_rule(FIRST))
    assert "Topics" in app.read("Transcripts") and "Summary" in app.read("Transcripts")  # the two tabs

    app.hear("Shall we look at the budget? I'll cut the travel costs.")
    app.click("Summary", "Transcripts")

    eventually(lambda: "They're looking at the budget." in app.read("Transcripts"))
    texts = app.read("Transcripts")
    assert {"Overview", "Action points", "•  Me: cut the travel costs.", "Kept up to date as it goes on"} <= set(texts)


def test_it_is_kept_up_to_date_as_the_conversation_goes_on(start, model):
    app = recording(start, model, summary_rule(LATER, text="hire"), summary_rule(FIRST))
    app.click("Summary", "Transcripts")
    app.hear("Shall we look at the budget?")
    eventually(lambda: "They're looking at the budget." in app.read("Transcripts"))
    asked = [r for r in model.requests() if SUMMARY in r["system"]]

    app.hear("And we need to hire a designer.")

    eventually(lambda: "They're looking at the budget, then hiring." in app.read("Transcripts"))
    assert "Hire a designer." in " ".join(app.read("Transcripts"))
    later = [r for r in model.requests() if SUMMARY in r["system"]][len(asked):]
    assert "hire a designer" in later[0]["text"] and "Shall we look" not in later[0]["text"]  # only what's new


def test_when_it_is_stopped_a_final_pass_is_saved_at_the_top_of_the_transcript(start, model):
    app = recording(start, model, summary_rule(FINAL, user="has ended"), summary_rule(FIRST))
    app.hear("Shall we look at the budget?")
    app.click("Summary", "Transcripts")
    eventually(lambda: "They're looking at the budget." in app.read("Transcripts"))

    app.click("Stop", "Transcripts")

    eventually(lambda: "They agreed the budget and to hire a designer." in (app.transcript_file() or ""))
    saved = app.transcript_file()
    assert "## Summary\n\n### Overview\nThey agreed the budget" in saved
    assert saved.index("## Summary") < saved.index("## Transcript") < saved.index("Shall we look at the budget?")
    eventually(lambda: "The final summary" in app.read("Transcripts"))


def test_a_saved_transcripts_summary_is_shown(start):
    app = start(styles=[])
    folder = app.data / "transcripts"
    folder.mkdir()
    (folder / "2026-10-19 10.00.00.md").write_text("# Transcript, Monday 19 October 2026, 10:00\n\nLasted 2 min, until "
                                                   "10:02.\n\n**10:00:05 Speaker 1:** Shall we start?\n")
    (folder / "2026-10-19 10.00.00 summary.json").write_text(json.dumps({"text": FINAL, "final": True}))
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")

    app.click("Summary", "Transcripts")

    assert "They agreed the budget and to hire a designer." in app.read("Transcripts")
    assert "•  Speaker 1: post the job." in app.read("Transcripts")


def test_the_summarys_prompt_can_be_changed_in_styles(start, model):
    model.rules(summary_rule(FIRST))
    app = start(styles=[])
    app.send("menu", path=["Styles…"])
    app.wait_window("Styles")
    app.send("select", row="Live summary", window_title="Styles")
    app.send("fill", name="text", text="Summarise it like a ship's log.", window_title="Styles")
    app.click("Save", window="Styles")

    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("Shall we look at the budget?")

    eventually(lambda: any("ship's log" in r["system"] for r in model.requests()))
    app.send("select", row="Styles", window_title="Transcripts")
    app.send("select", row="Live summary", window_title="Styles")
    app.click("Reset to default", window="Styles")
    app.click("Save", window="Styles")
    assert not (app.data / "summary.txt").exists()  # back to following the default
