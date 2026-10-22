"""When Synergy (or similar) has moved the keyboard to another computer, the text is typed over there."""
import json
from conftest import needs_session
from harness.client import refinement

pytestmark = needs_session
REFINEMENTS = [refinement("Plain", "p", default=True), refinement("Agent", "a")]


def synergy(home, *switches):
    """Synergy's config naming this computer "deck", and its log with these switches (screen names)."""
    conf = home / ".config/Synergy/synergy-core.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("[core]\ncomputerName=deck\n")
    log = home / ".local/state/Synergy/synergy.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"msg": "starting core"}) + "\n")
    switch(home, *switches)


def switch(home, *screens):
    with open(home / ".local/state/Synergy/synergy.jsonl", "a") as f:
        for frm, to in screens:
            f.write(json.dumps({"msg": f'switch from "{frm}" to "{to}"'}) + "\n")


def start_with_synergy(start, tmp_path, *switches, **kw):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    synergy(home, *switches)
    return start(**kw)


def test_on_the_other_computer_the_text_is_typed_not_pasted(start, tmp_path, model):
    model.rules({"prompt": "CLEANUP", "reply": "Run the tests on the laptop."})
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=[])

    out = app.dictate("run the tests on the laptop")

    assert out == {"type": "typed", "text": "Run the tests on the laptop."}
    assert app.dictations()[-1]["app"] == "other computer"


def test_back_on_this_computer_it_is_pasted_again(start, tmp_path):
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=[])
    app.dictate("over there")

    switch(tmp_path / "home", ("laptop", "deck"))

    assert app.dictate("back here")["type"] == "pasted"


def test_synergy_restarting_means_the_keyboard_is_back_here(start, tmp_path):
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=[])
    with open(tmp_path / "home/.local/state/Synergy/synergy.jsonl", "a") as f:
        f.write(json.dumps({"msg": "starting core"}) + "\n")

    assert app.dictate("back here")["type"] == "pasted"


def test_the_other_computer_has_its_own_default_refinement(start, tmp_path):
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=REFINEMENTS)
    app.send("menu", path=["When another computer has the keyboard", "Default refinement there", "Agent"])
    app.focus("Slack", "general - Slack")  # ignored: we can't see the other computer's apps

    app.dictate("run the tests")

    assert app.dictations()[-1]["refinement"] == "Agent"


def test_by_default_the_other_computer_uses_the_same_default_refinement(start, tmp_path):
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=REFINEMENTS)

    app.dictate("run the tests")

    assert app.dictations()[-1]["refinement"] == "Plain"


def test_the_hotkey_can_be_ignored_while_the_other_computer_has_the_keyboard(start, tmp_path):
    """e.g. the other computer runs its own Dictate, which will hear the same keys."""
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=[])
    app.send("menu", path=["When another computer has the keyboard", "Ignore the hotkey"])
    mark = app.mark()

    app.send("say", text="ignored")
    app.send("keys", down=["ctrl", "meta"])
    app.send("keys", up=["meta", "ctrl"])

    assert not app.happened("recording", after=mark)
    assert app.dictations() == []


def test_when_the_other_computer_drops_off_the_keyboard_is_back_here(start, tmp_path):
    """Synergy says "jump", not "switch", when it brings the keyboard home because the other computer went away."""
    app = start_with_synergy(start, tmp_path, ("deck", "laptop"), refinements=[])
    with open(tmp_path / "home/.local/state/Synergy/synergy.jsonl", "a") as f:
        f.write(json.dumps({"msg": 'error writing to client "laptop"'}) + "\n")
        f.write(json.dumps({"msg": 'jump from "laptop" to "deck" at 1720,720'}) + "\n")

    assert app.dictate("back here")["type"] == "pasted"
