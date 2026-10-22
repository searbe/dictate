"""Which refinement style a dictation gets: the focused app's, Alt+letter's, one picked afterwards, or the default."""
from conftest import needs_session
from harness.client import style

pytestmark = needs_session
STYLES = [style("Chat", "c", apps="whatsapp, slack"), style("Mail", "m", apps="gmail, thunderbird"),
          style("Agent", "a", apps="claude")]
SHOUT = [{"prompt": f"STYLE:{s['name']}", "op": "upper"} for s in STYLES]  # any style: capitals, so we can tell


def styled_as(app):
    return app.dictations()[-1].get("style")


def test_the_focused_windows_title_picks_the_style(start, model):
    model.rules(*SHOUT)
    app = start(styles=STYLES)
    app.focus("org.mozilla.firefox", "(2) WhatsApp — Mozilla Firefox")

    assert app.dictate("see you soon")["text"] == "SEE YOU SOON"
    assert styled_as(app) == "Chat"


def test_the_app_name_alone_can_pick_the_style(start, model):
    app = start(styles=STYLES)
    app.focus("thunderbird", "Write: (no subject)")

    app.dictate("dear sir")

    assert styled_as(app) == "Mail"


def test_a_new_title_in_the_same_window_is_used_without_switching_windows(start):
    """A browser tab change (Gmail → WhatsApp Web) renames the window but keeps it focused."""
    app = start(styles=STYLES)
    app.focus("org.mozilla.firefox", "Inbox (3) - me@gmail.com - Gmail — Mozilla Firefox")
    app.dictate("first")
    app.focus("org.mozilla.firefox", "WhatsApp — Mozilla Firefox", switched=False)

    app.dictate("second")

    assert [e["style"] for e in app.dictations()] == ["Mail", "Chat"]


def test_with_no_matching_app_the_default_style_applies(start):
    app = start(styles=STYLES[:1] + [style("Plain", "p", default=True)])
    app.focus("org.kde.kate", "notes.txt — Kate")

    app.dictate("a note")

    assert styled_as(app) == "Plain"


def test_with_no_matching_app_and_no_default_only_cleanup_applies(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "A note."}, *SHOUT)
    app = start(styles=STYLES)
    app.focus("org.kde.kate", "notes.txt — Kate")

    assert app.dictate("a note")["text"] == "A note."
    assert styled_as(app) is None


def test_the_default_style_chosen_in_the_menu_is_used_and_remembered(start):
    app = start(styles=STYLES)
    app.focus("org.kde.kate", "notes.txt — Kate")
    app.send("menu", path=["Default style", "Agent"])
    app.dictate("a note")
    assert styled_as(app) == "Agent"
    app.stop()

    again = start()  # same data folder, so the same saved styles
    again.focus("org.kde.kate", "notes.txt — Kate")
    again.dictate("another")
    assert styled_as(again) == "Agent"


def test_alt_and_a_letter_picks_that_style_whatever_the_app(start, model):
    model.rules(*SHOUT)
    app = start(styles=STYLES)
    app.focus("org.mozilla.firefox", "WhatsApp — Mozilla Firefox")

    app.dictate("deploy it", alt=True, letter="a")

    assert styled_as(app) == "Agent"


def test_alt_alone_asks_which_style_and_its_letter_applies_it(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Fix the bug."}, *SHOUT)
    app = start(styles=STYLES)
    mark = app.dictate("fix the bug", alt=True, wait=False)
    app.wait_window("Refine")
    assert "Fix the bug." in app.read("Refine")  # shows the cleaned-up text
    assert {"Chat", "Mail", "Agent"} <= set(app.read("Refine"))  # and every style

    app.send("press", key="m", window_title="Refine")

    assert app.result(mark)["text"] == "FIX THE BUG."
    assert styled_as(app) == "Mail"
    assert "Refine" not in app.send("windows")["titles"]


def test_an_alt_letter_that_is_no_styles_is_another_apps_shortcut(start):
    """Ctrl+Win+Alt+Z: not a style's letter, so it's someone else's shortcut, and nothing is pasted."""
    app = start(styles=STYLES)

    assert app.dictate("hello", alt=True, letter="z") is None
    assert "Refine" not in app.send("windows")["titles"]
    assert app.dictations() == []


def test_enter_in_the_picker_pastes_the_cleaned_up_text_as_is(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Hello, see you at the station."}, *SHOUT)
    app = start(styles=STYLES)
    mark = app.dictate("hello see you at the station", alt=True, wait=False)
    app.wait_window("Refine")

    app.send("press", key="Return", window_title="Refine")

    assert app.result(mark)["text"] == "Hello, see you at the station."
    assert styled_as(app) is None


def test_escape_in_the_picker_keeps_the_text_but_pastes_nothing(start, model):
    model.rules({"prompt": "CLEANUP", "reply": "Hello, see you at the station."})
    app = start(styles=STYLES)
    mark = app.dictate("hello see you at the station", alt=True, wait=False)
    app.wait_window("Refine")

    app.send("press", key="Escape", window_title="Refine")

    assert app.result(mark) is None
    assert app.dictations()[-1]["text"] == "Hello, see you at the station."
    assert app.send("clipboard")["text"] == "Hello, see you at the station."


def test_clicking_a_style_in_the_picker_applies_it(start, model):
    model.rules(*SHOUT)
    app = start(styles=STYLES)
    mark = app.dictate("hello", alt=True, wait=False)
    app.wait_window("Refine")

    app.click("Chat", window="Refine")

    assert app.result(mark)["text"] == "HELLO"
