"""Sharing transcripts with Claude Code (the /meeting-notes skill): a session runs scripts/meeting_notes.py, and
Dictate asks which transcripts to give it, if any, each as its summary or the whole of it. Off until it's turned on
in Settings; refused unless you choose; nothing ticked to begin with. Settings also installs the skill and blocks
Claude Code from reading Dictate's files itself (a deny rule in ~/.claude/settings.json)."""
import json
import os
import stat
import subprocess
import sys
import threading
import time

from conftest import ROOT, needs_session
from dictate import sharing
from harness.client import eventually

pytestmark = needs_session
WINDOW = "Share transcripts with Claude Code?"
BUDGET = """# Transcript, Monday 19 October 2026, 10:00

Lasted 27 min, until 10:27.

**10:00:05 Speaker 1:** Shall we go through the demo budget?

**10:00:09 Me:** Yes, the budget first.
"""
WEATHER = """# Transcript, Tuesday 20 October 2026, 16:30

Lasted 5 min, until 16:35.

**16:30:02 Speaker 1:** Lovely weather today.
"""
SUMMARY = "## Overview\nThey went through the demo budget."


def opened(start, allowed=True):
    app = start(refinements=[], settings={"share_with_claude": allowed})
    folder = app.data / "transcripts"
    folder.mkdir()
    (folder / "2026-10-19 10.00.00.md").write_text(BUDGET)
    (folder / "2026-10-19 10.00.00 summary.json").write_text(json.dumps({"text": SUMMARY, "final": True}))
    (folder / "2026-10-20 16.30.00.md").write_text(WEATHER)
    return app


MON, TUE = "Mon 19 Oct 2026, 10:00 · 27 min", "Tue 20 Oct 2026, 16:30 · 5 min"  # (each transcript's row)


def choose(app, row, option):
    app.send("choose", option=option, window_title=WINDOW, setting=row)


def ask(app, topic="the demo budget"):
    """Run the skill's script as a Claude Code session would: (thread, output) — output fills once it's answered."""
    out = []
    env = {**os.environ, "DICTATE_DATA": str(app.data)}

    def run():
        out.append(subprocess.run([sys.executable, str(ROOT / "scripts/meeting_notes.py"), topic], env=env,
                                  capture_output=True, text=True, timeout=60).stdout)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def answer(thread, out):
    thread.join(30)
    return out[0]


def test_it_is_off_until_turned_on_and_then_refused_without_asking(start):
    app = opened(start, allowed=False)

    said = answer(*ask(app))

    assert "Nothing shared" in said and "turned off in Dictate's Settings" in said
    assert WINDOW not in app.send("windows")["titles"]


def test_it_asks_saying_what_for_and_that_it_is_sent_to_anthropic(start):
    app = opened(start)

    ask(app, "quarterly hiring plans")

    app.wait_window(WINDOW)
    texts = app.read(WINDOW)
    assert "quarterly hiring plans" in texts
    assert any("sent to Anthropic" in t for t in texts)
    assert texts.index(TUE) < texts.index(MON)  # (nothing mentions it: one list, newest first, no headings)
    assert not any(t.startswith(("Mentions", "Other transcripts")) for t in texts)
    assert "Nothing chosen to share." in texts
    app.send("click", label="Share", window_title=WINDOW)  # not yet: nothing's chosen
    assert WINDOW in app.send("windows")["titles"]


def test_those_that_mention_it_come_first_set_to_share_their_summary(start):
    app = opened(start)

    asked = ask(app, "the demo budget")

    app.wait_window(WINDOW)
    texts = app.read(WINDOW)
    assert texts.index("Mentions what Claude is looking for (1)") < texts.index(MON) \
        < texts.index("Other transcripts (1)") < texts.index(TUE)
    assert "Mentions budget, demo" in texts
    assert "Sharing the summary of Mon 19 Oct 10:00." in texts
    app.click("Share", WINDOW)
    said = answer(*asked)
    assert "They went through the demo budget." in said and "Lovely weather" not in said


def test_none_sets_a_group_back_to_not_shared(start):
    app = opened(start)
    asked = ask(app, "the demo budget")
    app.wait_window(WINDOW)

    app.click("None", WINDOW)  # (the first group's: those that mention it)

    assert "Nothing chosen to share." in app.read(WINDOW)
    app.click("Refuse", WINDOW)
    answer(*asked)


def test_a_groups_heading_stays_in_sight_while_its_transcripts_are_scrolled_through(start):
    app = opened(start)
    for day in range(1, 13):  # (enough to scroll)
        (app.data / "transcripts" / f"2026-09-{day:02d} 09.00.00.md").write_text(
            f"# Transcript\n\n**09:00:00 Speaker 1:** Notes for day {day}.\n")
    ask(app, "the demo budget")
    app.wait_window(WINDOW)
    assert app.read(WINDOW).count("Other transcripts (13)") == 1

    app.send("scroll_list", to="end", window_title=WINDOW)

    eventually(lambda: app.read(WINDOW).count("Other transcripts (13)") == 2)  # its own, and pinned at the top
    app.send("scroll_list", to="top", window_title=WINDOW)
    eventually(lambda: app.read(WINDOW).count("Other transcripts (13)") == 1)
    app.click("Refuse", WINDOW)


def test_only_what_is_chosen_is_shared(start):
    app = opened(start)
    asked = ask(app)
    app.wait_window(WINDOW)

    choose(app, MON, "Its summary")
    app.click("Share", WINDOW)

    said = answer(*asked)
    assert "They went through the demo budget." in said and "(Its summary.)" in said
    assert "Shall we go through" not in said and "Lovely weather" not in said
    assert WINDOW not in app.send("windows")["titles"]


def test_the_whole_transcript_can_be_shared(start):
    app = opened(start)
    asked = ask(app)
    app.wait_window(WINDOW)

    choose(app, MON, "Whole transcript")
    choose(app, TUE, "Whole transcript")  # (it has no summary: the whole transcript is the only choice)
    assert "Sharing the whole transcripts of Mon 19 Oct 10:00 and Tue 20 Oct 16:30." in app.read(WINDOW)
    app.click("Share", WINDOW)

    said = answer(*asked)
    assert "Shall we go through the demo budget?" in said and "Lovely weather today." in said
    assert said.count("(The whole transcript.)") == 2


def test_refusing_closing_or_escape_shares_nothing(start):
    app = opened(start)
    for refuse in (lambda: app.click("Refuse", WINDOW), lambda: app.send("close", window_title=WINDOW),
                   lambda: app.send("press", key="Escape", window_title=WINDOW)):
        asked = ask(app)
        app.wait_window(WINDOW)
        choose(app, MON, "Its summary")

        refuse()

        said = answer(*asked)
        assert "Nothing shared: The user chose not to share any transcripts." in said
        eventually(lambda: WINDOW not in app.send("windows")["titles"])


def test_another_request_while_one_is_asked_is_refused(start):
    app = opened(start)
    first = ask(app)
    app.wait_window(WINDOW)

    said = answer(*ask(app, "something else"))

    assert "already asking" in said
    app.click("Refuse", WINDOW)
    answer(*first)


def test_without_dictate_running_it_says_so(start):
    app = opened(start)
    app.stop()

    said = answer(*ask(app))

    assert "Dictate isn't running" in said


def test_only_you_can_connect(start):
    app = opened(start)

    path = sharing.address(app.data)

    assert stat.S_ISSOCK(path.stat().st_mode) and stat.S_IMODE(path.stat().st_mode) == 0o600  # (and it checks who)


def settings_json(app):
    return json.loads((app.home / ".claude/settings.json").read_text())


def test_settings_installs_the_skill_and_the_block_and_the_block_can_be_turned_off(start):
    app = opened(start)
    claude = app.home / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"theme": "dark", "permissions": {"deny": ["Read(./.env)"]}}))
    app.send("menu", path=["Settings…"])
    app.wait_window("Settings")

    app.click("Install", "Settings")

    eventually(lambda: (claude / "skills/meeting-notes/SKILL.md").exists())
    skill = (claude / "skills/meeting-notes/SKILL.md").read_text()
    assert str(ROOT / "scripts/meeting_notes.py") in skill and "disable-model-invocation: true" in skill
    rule = f"Read(/{app.data.resolve()}/**)"
    assert settings_json(app) == {"theme": "dark", "permissions": {"deny": ["Read(./.env)", rule]}}

    app.click("Block Claude Code from reading Dictate's files", "Settings")

    eventually(lambda: settings_json(app) == {"theme": "dark", "permissions": {"deny": ["Read(./.env)"]}})
    app.click("Block Claude Code from reading Dictate's files", "Settings")
    eventually(lambda: rule in settings_json(app)["permissions"]["deny"])
    time.sleep(0.2)
    app.click("Remove", "Settings")
    eventually(lambda: not (claude / "skills/meeting-notes").exists())


def test_claude_codes_settings_are_left_alone_if_they_are_not_json(start):
    app = opened(start)
    claude = app.home / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{ not json")
    app.send("menu", path=["Settings…"])
    app.wait_window("Settings")

    app.click("Block Claude Code from reading Dictate's files", "Settings")

    app.wait_window("Couldn't change Claude Code's settings")
    assert (claude / "settings.json").read_text() == "{ not json"


REAL = ("Recent meetings where you or the team talked about the level editor, custom arena shapes (donut, figure 8), "
        "or feedback on the camera and debug-menu experiments, so I can act on any decisions or requests.")


def test_everyday_words_and_what_was_only_said_in_passing_do_not_make_a_match(start):
    app = opened(start)  # (its budget call: "They went through the demo budget.")
    folder = app.data / "transcripts"
    for name, summary, said in (
            ("2026-10-21 09.00.00", "## Overview\nThe team talked about recent meetings and what was decided.",
             "We talked about it."),
            ("2026-10-22 09.00.00", "## Overview\nThey reviewed the level editor and the new arena shapes.",
             "The level editor is in."),
            ("2026-10-23 09.00.00", "## Overview\nThey planned the trip.", "Mind the camera on the way.")):
        (folder / f"{name}.md").write_text(f"# Transcript\n\n**09:00:00 Speaker 1:** {said}\n")
        (folder / f"{name} summary.json").write_text(json.dumps({"text": summary, "final": True}))

    asked = ask(app, REAL)

    app.wait_window(WINDOW)
    texts = app.read(WINDOW)
    assert "Mentions what Claude is looking for (1)" in texts and "Mentions arena, editor, level, shapes" in texts
    assert "Sharing the summary of Thu 22 Oct 09:00." in texts  # (not those with only everyday words, or "camera"
    app.click("Refuse", WINDOW)  # said in passing, not in its summary)
    answer(*asked)
