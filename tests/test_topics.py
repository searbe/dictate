"""Topics: while a conversation is transcribed, its topics are listed beside it in the Transcripts window, each
in its own colour, with who brought it up and who else spoke on it, the one being talked about now marked; the
transcript shows each topic's name where the conversation turns to it. They're saved with the transcript. The model finds them (here, its stand-in: see
harness/fake_llama.py), in JSON: each topic with the numbers of the lines about it."""
import json, time
from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
TOPICS = "live list of the topics"  # in the topics prompt


def answer(when, *found):
    """A rule: when the lines sent include when, the model answers with these (title, what was said, line numbers)."""
    return {"prompt": TOPICS, "text": when,
            "reply": json.dumps({"topics": [{"topic": 0, "title": t, "said": n, "lines": l} for t, n, l in found]})}


BUDGET = answer("budget", ("The budget", "Speaker 1 asked about it; Me thinks it's too high.", [1, 2]))
HIRING = answer("hire", ("Hiring", "Speaker 1 wants to hire a designer.", [1]))


def recording(start, model, *rules):
    model.rules(*rules)
    app = start(refinements=[])
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    return app


def test_topics_are_listed_beside_the_transcript_with_who_brought_them_up(start, model):
    app = recording(start, model, BUDGET)

    app.hear("Shall we look at the budget?")
    app.hear("Yes, the budget is too high.", source="mic")

    eventually(lambda: "Speaker 1 brought it up · with Me" in app.read("Transcripts"))
    texts = app.read("Transcripts")
    assert "The budget" in texts and "Speaker 1 asked about it; Me thinks it's too high." in texts
    assert "Now" in texts
    assert "● The budget\n" in app.transcript()  # where the conversation turns to it


def test_small_talk_is_no_topic(start, model):
    app = recording(start, model, answer("weather"))

    app.hear("Lovely weather today.")

    eventually(lambda: model.requests() and any(TOPICS in r["system"] for r in model.requests()))
    assert "The topics of the conversation appear here as it goes on, about a minute in." in app.read("Transcripts")
    assert "●" not in app.transcript()


def test_the_topic_now_is_the_latest_and_a_new_topic_starts_a_new_paragraph(start, model):
    app = recording(start, model, HIRING, BUDGET)  # (the lines before, sent for context, mention the budget)
    app.hear("Shall we look at the budget?")
    eventually(lambda: "The budget" in app.read("Transcripts"))

    app.hear("And we need to hire a designer.")

    eventually(lambda: "Hiring" in app.read("Transcripts"))
    texts = app.read("Transcripts")
    assert texts.index("The budget") < texts.index("Hiring")  # in the order they came up
    assert texts.index("Now") > texts.index("Hiring")  # marked on the latest
    text = app.transcript()
    assert text.index("● The budget") < text.index("● Hiring")
    assert text.count("Speaker 1") == 2  # one person talking on, but onto another topic


def test_going_back_to_a_topic_carries_it_on(start, model):
    app = recording(start, model, HIRING, BUDGET)  # (the lines before, sent for context, mention the budget)
    app.hear("Shall we look at the budget?")
    eventually(lambda: "The budget" in app.read("Transcripts"))
    app.hear("And we need to hire a designer.")
    eventually(lambda: "Hiring" in app.read("Transcripts"))
    model.rules(answer("Back to", ("The budget", "Me will cut it.", [1])), HIRING)

    app.hear("Back to the money, I'll cut it.", source="mic")

    eventually(lambda: "Me will cut it." in app.read("Transcripts"))
    texts = app.read("Transcripts")
    assert texts.count("The budget") == 1  # still one topic, with what was said on it before, and now
    assert texts.index("Speaker 1 asked about it; Me thinks it's too high.") < texts.index("Me will cut it.") < texts.index("Hiring")
    assert texts.index("Now") < texts.index("Hiring")  # marked on the budget again
    assert app.transcript().count("● The budget") == 2  # where the conversation turned to it, both times


def test_topics_are_saved_at_the_top_of_the_transcript(start, model):
    app = recording(start, model, BUDGET)
    app.hear("Shall we look at the budget?")
    app.hear("Yes, the budget is too high.", source="mic")
    eventually(lambda: "The budget" in app.read("Transcripts"))

    app.click("Stop", "Transcripts")

    eventually(lambda: app.stopped())
    saved = app.transcript_file()
    assert "## Topics\n\n- **The budget** (Speaker 1, Me): Speaker 1 asked about it; Me thinks it's too high.\n" in saved
    assert saved.index("## Topics") < saved.index("Speaker 1:** Shall we look at the budget?")
    eventually(lambda: "Speaker 1 brought it up · with Me" in app.read("Transcripts"))  # shown, as saved
    assert "Now" not in app.read("Transcripts")  # nothing is being talked about now
    assert "● The budget" in app.transcript()


def test_what_was_said_last_is_sorted_into_topics_when_it_is_stopped(start, model):
    app = recording(start, model, BUDGET)
    app.hear("Shall we look at the budget?")

    app.ctrl_win_win()

    eventually(lambda: "**The budget**" in (app.transcript_file() or ""))


def test_when_the_model_fails_the_transcript_carries_on_without_topics(start, model):
    app = recording(start, model, {"prompt": TOPICS, "op": "error"})

    app.hear("Shall we look at the budget?")

    eventually(lambda: any(TOPICS in r["system"] for r in model.requests()))
    assert "Shall we look at the budget?" in app.transcript()
    assert "Shall we look at the budget?" in app.transcript_file()
    assert "The topics of the conversation appear here as it goes on, about a minute in." in app.read("Transcripts")


BUSY = "Warning: using a less reliable model because your graphics card is busy."


def test_with_the_graphics_card_busy_a_warning_says_a_less_reliable_model_is_in_use(start, model):
    model.rules(BUDGET)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")

    app.hear("Shall we look at the budget?")

    eventually(lambda: "The budget" in app.read("Transcripts"))
    assert BUSY in app.read("Transcripts")
    assert "--device" in model.starts()[0]["args"] and "none" in model.starts()[0]["args"]  # on the CPU


def test_without_a_graphics_card_the_warning_says_so(start, model):
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "none"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")

    eventually(lambda: "Warning: using a less reliable model because this computer has no graphics card it can use."
               in app.read("Transcripts"))


def test_it_switches_to_the_better_model_once_the_graphics_card_is_free(start, model):
    model.rules(BUDGET)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    eventually(lambda: BUSY in app.read("Transcripts"))

    app.send("gpu", state="free")

    eventually(lambda: BUSY not in app.read("Transcripts"))
    eventually(lambda: len(model.starts()) == 2)  # loaded again (it says so a moment after the old one stops)
    assert "Vulkan0" in model.starts()[-1]["args"]  # on the GPU
    app.hear("Shall we look at the budget?")
    eventually(lambda: "The budget" in app.read("Transcripts"))  # and topics carry on


def test_it_does_not_switch_in_the_middle_of_a_dictation(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Note to self."})
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    eventually(lambda: BUSY in app.read("Transcripts"))
    app.send("say", text="note to self")
    app.send("keys", down=["ctrl", "meta"])

    app.send("gpu", state="free")
    time.sleep(1.5)  # longer than the graphics card has to be free for

    assert len(model.starts()) == 1
    mark = app.mark()
    app.send("keys", up=["meta", "ctrl"])
    assert app.result(mark)["text"] == "Note to self."
    eventually(lambda: len(model.starts()) == 2)  # once it's done


def test_topics_found_by_the_less_reliable_model_say_so_once_saved(start, model):
    model.rules(BUDGET)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("Shall we look at the budget?")
    eventually(lambda: "The budget" in app.read("Transcripts"))

    app.click("Stop", "Transcripts")

    eventually(lambda: "These topics were found with a less reliable model, as your graphics card was busy."
               in app.read("Transcripts"))



MERGING = "Reply with the groups of topics"  # in the prompt asking which topics are one subject
SAME = "Are they one subject"  # and in the one asking again about each pair


def four_topics(start, model, *rules):
    """Dictate transcribing, with four topics heard: the budget, hiring, the office move, and money again
    under another title."""
    model.rules(*rules, answer("costs", ("Cutting costs", "Me will cut the travel costs.", [1])),  # (newest first:
                answer("office", ("Office move", "Me says the move is in May.", [1])),  # the lines before are
                answer("hire", ("Hiring", "Speaker 1 wants a designer.", [1])), BUDGET)  # sent too)
    app = start(refinements=[])
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    for said, source in (("Shall we look at the budget?", "speakers"), ("And we need to hire a designer.", "speakers"),
                         ("The office move is in May.", "mic"), ("I'll cut the travel costs.", "mic")):
        app.hear(said, source=source)
        eventually(lambda: len([r for r in model.requests() if TOPICS in r["system"] and said in r["text"]]) > 0)
    return app


def test_topics_that_turn_out_to_be_one_subject_are_merged(start, model):
    app = four_topics(start, model, {"prompt": MERGING, "reply": json.dumps(
        {"groups": [{"topics": [1, 4], "title": "Budget and costs"}]})}, {"prompt": SAME, "reply": '{"same": true}'})

    eventually(lambda: "Budget and costs" in app.read("Transcripts"))
    texts = app.read("Transcripts")
    assert "The budget" not in texts and "Cutting costs" not in texts
    assert texts.index("Speaker 1 asked about it; Me thinks it's too high.") < texts.index("Me will cut the travel costs.")
    assert "Hiring" in texts and "Office move" in texts  # the others stay as they were
    assert app.transcript().count("● Budget and costs") == 2  # where the conversation turned to it, both times


def test_topics_are_not_merged_unless_asked_again_they_are_one_subject(start, model):
    """Asked about the whole list, a model is quick to group things only talked about together."""
    app = four_topics(start, model, {"prompt": MERGING, "reply": json.dumps(
        {"groups": [{"topics": [2, 3], "title": "Hiring and the office"}]})}, {"prompt": SAME, "reply": '{"same": false}'})

    eventually(lambda: any(SAME in r["system"] for r in model.requests()))
    time.sleep(0.5)
    texts = app.read("Transcripts")
    assert "Hiring" in texts and "Office move" in texts and "Hiring and the office" not in texts


def test_the_less_reliable_model_does_not_merge_topics(start, model):
    model.rules(answer("hire", ("Hiring", "Speaker 1 wants a designer.", [1])), BUDGET)
    app = start(refinements=[], env={"DICTATE_TEST_GPU": "busy"})
    app.ctrl_win_win()
    app.wait_window("Transcripts")
    for said in ("Shall we look at the budget?", "And we need to hire a designer.", "Budget again.", "Hire again."):
        app.hear(said)
    eventually(lambda: "Hiring" in app.read("Transcripts"))

    time.sleep(1)

    assert not any(MERGING in r["system"] for r in model.requests())
