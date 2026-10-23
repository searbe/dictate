"""Refinements, in the Dictate window: creating, editing and deleting refinements, the vocabulary and the cleanup prompt.
Each change is checked by what it does to the next dictation, not by what's in the settings file."""
import json
from conftest import needs_session
from harness.client import eventually, refinement

pytestmark = needs_session
W = "Refinements"


def open_manager(start, model, **kw):
    model.rules({"prompt": "REFINEMENT:", "op": "upper"}, {"prompt": "Shout everything", "op": "upper"})
    app = start(**kw)
    app.send("menu", path=["Refinements…"])
    app.wait_window(W)
    return app


def add_refinement(app, name, letter, apps, prompt):
    app.click("New refinement", window=W)
    app.send("fill", name="Name", text=name, window_title=W)
    app.send("fill", name="Letter", text=letter, window_title=W)
    app.send("fill", name="Use automatically in apps", text=apps, window_title=W)
    app.send("fill", name="text", text=prompt, window_title=W)
    app.click("Save", window=W)


def test_a_new_refinement_is_used_in_its_apps_and_by_its_letter(start, model):
    app = open_manager(start, model, refinements=[])
    add_refinement(app, "Loud", "l", "discord", "Shout everything")
    assert "Saved" in app.read(W)

    app.focus("discord", "#general - Discord")
    assert app.dictate("hello friends")["text"] == "HELLO FRIENDS"
    app.focus("org.kde.kate", "notes.txt — Kate")
    assert app.dictate("hello friends", alt=True, letter="l")["text"] == "HELLO FRIENDS"


def test_a_new_refinement_is_offered_in_the_picker_and_the_default_refinement_menu(start, model):
    app = open_manager(start, model, refinements=[])
    add_refinement(app, "Loud", "l", "", "Shout everything")

    assert "Loud" in [i["label"] for i in app.send("menu_items", path=["Default refinement"])["items"]]
    app.dictate("hello friends", alt=True, wait=False)
    app.wait_window("Refine")
    assert "Loud" in app.read("Refine")


def test_a_refinement_needs_a_name_a_free_letter_and_a_description(start, model):
    app = open_manager(start, model, refinements=[refinement("Chat", "c")])
    app.click("New refinement", window=W)
    app.send("fill", name="Name", text="", window_title=W)

    for name, letter, prompt, error in (("", "x", "p", "Give the refinement a name."),
                                        ("Loud", "", "p", "Choose a letter A–Z."),
                                        ("Loud", "1", "p", "Choose a letter A–Z."),
                                        ("Loud", "c", "p", "C is already used by another refinement."),
                                        ("Loud", "l", "", "Describe the refinement.")):
        app.send("fill", name="Name", text=name, window_title=W)
        app.send("fill", name="Letter", text=letter, window_title=W)
        app.send("fill", name="text", text=prompt, window_title=W)
        app.click("Save", window=W)
        assert error in app.read(W)

    assert [s["name"] for s in json.loads((app.data / "refinements.json").read_text())["refinements"]] == ["Chat"]


def test_editing_a_refinement_changes_what_it_does(start, model):
    model.rules({"prompt": "Shout everything", "op": "upper"})
    app = open_manager(start, model, refinements=[{**refinement("Chat", "c", apps="slack"), "prompt": "Leave it alone"}])
    app.send("select", row="Chat", window_title=W)
    app.send("fill", name="text", text="Shout everything", window_title=W)
    app.click("Save", window=W)

    app.focus("Slack", "general - Slack")
    assert app.dictate("hello team")["text"] == "HELLO TEAM"


def test_a_deleted_refinement_is_no_longer_used(start, model):
    app = open_manager(start, model, refinements=[refinement("Chat", "c", apps="slack")])
    app.send("select", row="Chat", window_title=W)
    app.click("Delete", window=W)

    app.focus("Slack", "general - Slack")
    app.dictate("hello team")
    assert "refinement" not in app.dictations()[-1]


def test_renaming_the_other_computers_default_refinement_keeps_it_as_the_default(start, model):
    app = start(refinements=[refinement("Chat", "c")])
    app.send("menu", path=["When another computer has the keyboard", "Default refinement there", "Chat"])
    app.send("menu", path=["Refinements…"])
    app.wait_window(W)
    app.send("select", row="Chat", window_title=W)
    app.send("fill", name="Name", text="Messages", window_title=W)
    app.click("Save", window=W)

    items = app.send("menu_items", path=["When another computer has the keyboard", "Default refinement there"])["items"]
    assert {"label": "Messages", "ticked": True} in items


def test_vocabulary_edits_reach_the_model(start, model):
    app = open_manager(start, model, refinements=[])
    app.send("select", row="Vocabulary", window_title=W)
    app.send("fill", name="text", text="Synergy\nDeskflow", window_title=W)
    app.click("Save", window=W)

    app.dictate("start the synergy server")

    assert "- Deskflow" in model.requests()[-1]["system"]


def test_the_cleanup_prompt_can_be_edited_and_reset_to_the_default(start, model):
    app = open_manager(start, model, refinements=[])
    app.send("select", row="Cleanup", window_title=W)
    app.send("fill", name="text", text="Shout everything", window_title=W)
    app.click("Save", window=W)
    assert app.dictate("hello there")["text"] == "HELLO THERE"

    app.click("Reset to default", window=W)
    app.click("Save", window=W)
    app.dictate("hello there")
    assert "Make the minimal edits" in model.requests()[-1]["system"]


def saved_prompt(app, name):
    return next(s["prompt"] for s in json.loads((app.data / "refinements.json").read_text())["refinements"] if s["name"] == name)


def edit_chat(start, model):
    app = open_manager(start, model, refinements=[{**refinement("Chat", "c"), "prompt": "Leave it alone"}])
    app.send("select", row="Chat", window_title=W)
    app.send("fill", name="text", text="Shout everything", window_title=W)
    return app


def test_closing_with_unsaved_changes_asks_and_save_saves_them(start, model):
    app = edit_chat(start, model)

    app.send("close", window_title=W)
    app.wait_window(None)
    assert "Save your changes to Chat?" in app.read(None)
    app.click("Save")

    eventually(lambda: W not in app.send("windows")["titles"])
    assert saved_prompt(app, "Chat") == "Shout everything"


def test_closing_without_saving_keeps_what_was_saved(start, model):
    app = edit_chat(start, model)

    app.send("close", window_title=W)
    app.wait_window(None)
    app.click("Don't save")

    eventually(lambda: W not in app.send("windows")["titles"])
    assert saved_prompt(app, "Chat") == "Leave it alone"


def test_cancel_keeps_the_window_open_with_the_changes(start, model):
    app = edit_chat(start, model)

    app.send("close", window_title=W)
    app.wait_window(None)
    app.click("Cancel")

    assert W in app.send("windows")["titles"]
    assert app.send("field", name="text", window_title=W)["text"] == "Shout everything"


def test_picking_another_row_with_unsaved_changes_asks_first(start, model):
    app = edit_chat(start, model)

    app.send("select", row="Vocabulary", window_title=W)
    app.wait_window(None)
    app.click("Cancel")
    assert app.send("field", name="text", window_title=W)["text"] == "Shout everything"

    app.send("select", row="Vocabulary", window_title=W)
    app.wait_window(None)
    app.click("Save")
    eventually(lambda: saved_prompt(app, "Chat") == "Shout everything")


def test_unsaved_changes_are_still_there_after_looking_at_another_page(start, model):
    app = edit_chat(start, model)

    app.send("menu", path=["Settings…"])
    app.wait_window("Settings")
    app.send("menu", path=["Refinements…"])
    app.wait_window(W)

    assert app.send("field", name="text", window_title=W)["text"] == "Shout everything"


def test_closing_with_nothing_changed_just_closes(start, model):
    app = open_manager(start, model, refinements=[refinement("Chat", "c")])
    app.send("select", row="Chat", window_title=W)

    app.send("close", window_title=W)

    eventually(lambda: W not in app.send("windows")["titles"])


def test_saving_a_refinement_keeps_the_defaults_chosen_in_settings_meanwhile(start, model):
    app = open_manager(start, model, refinements=[refinement("Chat", "c"), refinement("Mail", "m")])
    app.send("menu", path=["Settings…"])
    app.wait_window("Settings")
    app.send("choose", option="Mail", setting="Default refinement", window_title="Settings")
    app.send("choose", option="Chat", setting="Default refinement there", window_title="Settings")
    app.send("menu", path=["Refinements…"])
    app.wait_window(W)
    app.send("select", row="Chat", window_title=W)
    app.send("fill", name="text", text="Shout everything", window_title=W)
    app.click("Save", window=W)

    data = json.loads((app.data / "refinements.json").read_text())
    assert [s["name"] for s in data["refinements"] if s.get("default")] == ["Mail"]
    assert data["remote_default"] == "Chat"
