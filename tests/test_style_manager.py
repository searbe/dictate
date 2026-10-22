"""Styles, in the Dictate window: creating, editing and deleting styles, the vocabulary and the cleanup prompt.
Each change is checked by what it does to the next dictation, not by what's in the settings file."""
import json
from conftest import needs_session
from harness.client import style

pytestmark = needs_session
W = "Styles"


def open_manager(start, model, **kw):
    model.rules({"prompt": "STYLE:", "op": "upper"}, {"prompt": "Shout everything", "op": "upper"})
    app = start(**kw)
    app.send("menu", path=["Styles…"])
    app.wait_window(W)
    return app


def add_style(app, name, letter, apps, prompt):
    app.click("New style", window=W)
    app.send("fill", name="Name", text=name, window_title=W)
    app.send("fill", name="Letter", text=letter, window_title=W)
    app.send("fill", name="Use automatically in apps", text=apps, window_title=W)
    app.send("fill", name="text", text=prompt, window_title=W)
    app.click("Save", window=W)


def test_a_new_style_is_used_in_its_apps_and_by_its_letter(start, model):
    app = open_manager(start, model, styles=[])
    add_style(app, "Loud", "l", "discord", "Shout everything")
    assert "Saved" in app.read(W)

    app.focus("discord", "#general - Discord")
    assert app.dictate("hello friends")["text"] == "HELLO FRIENDS"
    app.focus("org.kde.kate", "notes.txt — Kate")
    assert app.dictate("hello friends", alt=True, letter="l")["text"] == "HELLO FRIENDS"


def test_a_new_style_is_offered_in_the_picker_and_the_default_style_menu(start, model):
    app = open_manager(start, model, styles=[])
    add_style(app, "Loud", "l", "", "Shout everything")

    assert "Loud" in [i["label"] for i in app.send("menu_items", path=["Default style"])["items"]]
    app.dictate("hello friends", alt=True, wait=False)
    app.wait_window("Refine")
    assert "Loud" in app.read("Refine")


def test_a_style_needs_a_name_a_free_letter_and_a_description(start, model):
    app = open_manager(start, model, styles=[style("Chat", "c")])
    app.click("New style", window=W)
    app.send("fill", name="Name", text="", window_title=W)

    for name, letter, prompt, error in (("", "x", "p", "Give the style a name."),
                                        ("Loud", "", "p", "Choose a letter A–Z."),
                                        ("Loud", "1", "p", "Choose a letter A–Z."),
                                        ("Loud", "c", "p", "C is already used by another style."),
                                        ("Loud", "l", "", "Describe the style.")):
        app.send("fill", name="Name", text=name, window_title=W)
        app.send("fill", name="Letter", text=letter, window_title=W)
        app.send("fill", name="text", text=prompt, window_title=W)
        app.click("Save", window=W)
        assert error in app.read(W)

    assert [s["name"] for s in json.loads((app.data / "styles.json").read_text())["styles"]] == ["Chat"]


def test_editing_a_style_changes_what_it_does(start, model):
    model.rules({"prompt": "Shout everything", "op": "upper"})
    app = open_manager(start, model, styles=[{**style("Chat", "c", apps="slack"), "prompt": "Leave it alone"}])
    app.send("select", row="Chat", window_title=W)
    app.send("fill", name="text", text="Shout everything", window_title=W)
    app.click("Save", window=W)

    app.focus("Slack", "general - Slack")
    assert app.dictate("hello team")["text"] == "HELLO TEAM"


def test_a_deleted_style_is_no_longer_used(start, model):
    app = open_manager(start, model, styles=[style("Chat", "c", apps="slack")])
    app.send("select", row="Chat", window_title=W)
    app.click("Delete", window=W)

    app.focus("Slack", "general - Slack")
    app.dictate("hello team")
    assert "style" not in app.dictations()[-1]


def test_renaming_the_other_computers_default_style_keeps_it_as_the_default(start, model):
    app = start(styles=[style("Chat", "c")])
    app.send("menu", path=["When another computer has the keyboard", "Default style there", "Chat"])
    app.send("menu", path=["Styles…"])
    app.wait_window(W)
    app.send("select", row="Chat", window_title=W)
    app.send("fill", name="Name", text="Messages", window_title=W)
    app.click("Save", window=W)

    items = app.send("menu_items", path=["When another computer has the keyboard", "Default style there"])["items"]
    assert {"label": "Messages", "ticked": True} in items


def test_vocabulary_edits_reach_the_model(start, model):
    app = open_manager(start, model, styles=[])
    app.send("select", row="Vocabulary", window_title=W)
    app.send("fill", name="text", text="Synergy\nDeskflow", window_title=W)
    app.click("Save", window=W)

    app.dictate("start the synergy server")

    assert "- Deskflow" in model.requests()[-1]["system"]


def test_the_cleanup_prompt_can_be_edited_and_reset_to_the_default(start, model):
    app = open_manager(start, model, styles=[])
    app.send("select", row="Cleanup", window_title=W)
    app.send("fill", name="text", text="Shout everything", window_title=W)
    app.click("Save", window=W)
    assert app.dictate("hello there")["text"] == "HELLO THERE"

    app.click("Reset to default", window=W)
    app.click("Save", window=W)
    app.dictate("hello there")
    assert "Make the minimal edits" in model.requests()[-1]["system"]
