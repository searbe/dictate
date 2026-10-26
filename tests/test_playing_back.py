"""Playing back a transcript's call: the whole of it (Play, above it) or one paragraph (its play button, shown while
it's hovered), with the paragraph being played highlighted and its button Stop, following the call as it plays.
One thing plays at a time, everywhere: a dictation's recording too."""
import time

import numpy as np
import soundfile

from conftest import needs_session
from harness.client import eventually

pytestmark = needs_session
NAME = "2026-10-19 10.00.00"
CALL = """# Transcript, Monday 19 October 2026, 10:00

Lasted 10 s, until 10:00.

**10:00:00 Them:** Shall we start with the roadmap?

**10:00:03 Me:** Yes, the roadmap first.

**10:00:06 Them:** Then the budget.
"""
PARAGRAPH = "Play this paragraph"


def opened(start, env=None, seconds=10):
    """The Transcripts window showing CALL, with its recordings (a tone each, seconds long)."""
    app = start(refinements=[], env=env)
    folder = app.data / "transcripts"
    folder.mkdir()
    (folder / f"{NAME}.md").write_text(CALL)
    t = np.arange(16000 * seconds) / 16000
    for who, hz in (("me", 220), ("them", 330)):
        soundfile.write(str(folder / f"{NAME} {who}.ogg"), (0.2 * np.sin(2 * np.pi * hz * t)).astype(np.float32),
                        16000, format="OGG", subtype="OPUS")
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    return app


def seconds_played(app, mark):
    audio, rate = soundfile.read(app.wait_for("playing", after=mark)["path"])
    return len(audio) / rate


def highlighted(app):
    return app.send("highlighted", window_title="Transcripts")["texts"]


def play_paragraph(app, text):
    app.send("hover_text", text=text, window_title="Transcripts")
    app.click(PARAGRAPH, "Transcripts")


def test_a_paragraph_s_play_button_shows_while_it_is_hovered(start):
    app = opened(start)
    assert PARAGRAPH not in app.read("Transcripts")

    app.send("hover_text", text="Yes, the roadmap first.", window_title="Transcripts")
    assert app.read("Transcripts").count(PARAGRAPH) == 1

    app.send("hover_text", text=None, window_title="Transcripts")
    assert PARAGRAPH not in app.read("Transcripts")


def test_playing_a_paragraph_plays_only_it_highlighted_with_a_stop_button(start):
    app = opened(start)
    mark = app.mark()

    play_paragraph(app, "Yes, the roadmap first.")

    assert abs(seconds_played(app, mark) - 3) < 0.1  # until the next paragraph, at 10:00:06
    eventually(lambda: highlighted(app) == ["10:00:03 Me  Yes, the roadmap first."])
    app.send("hover_text", text=None, window_title="Transcripts")
    assert app.read("Transcripts").count("Stop") == 2  # its own, and Play above, which stops it too
    assert PARAGRAPH not in app.read("Transcripts")

    app.click("Stop", "Transcripts", nth=1)

    app.wait_for("stopped", after=mark)
    eventually(lambda: highlighted(app) == [] and "Stop" not in app.read("Transcripts"))


def test_play_above_plays_the_whole_call_and_the_highlight_follows_it(start):
    app = opened(start)
    mark = app.mark()

    app.click("Play", "Transcripts")

    assert abs(seconds_played(app, mark) - 10) < 0.1
    eventually(lambda: highlighted(app) == ["10:00:00 Them  Shall we start with the roadmap?"])
    eventually(lambda: highlighted(app) == ["10:00:03 Me  Yes, the roadmap first."], timeout=5)
    assert app.read("Transcripts").count("Stop") == 2  # above, and the paragraph being played

    app.click("Stop", "Transcripts", nth=1)  # (the paragraph's: the same playback)

    app.wait_for("stopped", after=mark)
    eventually(lambda: "Stop" not in app.read("Transcripts"))


def test_another_paragraph_while_one_plays_plays_that_one_instead(start):
    app = opened(start)
    first = app.mark()
    play_paragraph(app, "Yes, the roadmap first.")
    app.wait_for("playing", after=first)  # (it's highlighted from the click, before it's ready and plays)
    eventually(lambda: highlighted(app) == ["10:00:03 Me  Yes, the roadmap first."])
    mark = app.mark()

    play_paragraph(app, "Then the budget.")

    assert abs(seconds_played(app, mark) - 4) < 0.1  # to the end
    eventually(lambda: highlighted(app) == ["10:00:06 Them  Then the budget."])
    assert app.read("Transcripts").count("Stop") == 2


def test_while_it_is_being_prepared_it_is_already_stop_and_stopping_it_plays_nothing(start):
    app = opened(start, env={"DICTATE_TEST_SLOW_CUT": "1"})
    mark = app.mark()

    app.click("Play", "Transcripts")
    assert "Stop" in app.read("Transcripts")
    app.click("Stop", "Transcripts")

    time.sleep(1.5)
    assert not app.happened("playing", after=mark)
    assert "Play" in app.read("Transcripts")


def test_asking_for_another_part_while_one_is_prepared_plays_only_the_last(start):
    app = opened(start, env={"DICTATE_TEST_SLOW_CUT": "1"})
    mark = app.mark()

    app.click("Play", "Transcripts")
    play_paragraph(app, "Then the budget.")

    assert abs(seconds_played(app, mark) - 4) < 0.1
    time.sleep(1.5)
    assert [e["type"] for e in app.events[mark:]].count("playing") == 1


def test_closing_the_window_while_it_is_prepared_plays_nothing(start):
    app = opened(start, env={"DICTATE_TEST_SLOW_CUT": "1"})
    mark = app.mark()

    app.click("Play", "Transcripts")
    app.send("close", window_title="Transcripts")

    time.sleep(1.5)
    assert not app.happened("playing", after=mark)


def test_showing_another_transcript_stops_it(start):
    app = opened(start)
    (app.data / "transcripts" / "2026-10-20 16.30.00.md").write_text(
        "# Transcript\n\n**16:30:02 Them:** Welcome to the talk.\n")
    app.send("close", window_title="Transcripts")
    app.send("menu", path=["Transcripts"])
    app.wait_window("Transcripts")
    app.send("select", row="Mon 19 Oct · 10:00", window_title="Transcripts")
    mark = app.mark()
    app.click("Play", "Transcripts")
    app.wait_for("playing", after=mark)

    app.send("select", row="Tue 20 Oct · 16:30", window_title="Transcripts")

    app.wait_for("stopped", after=mark)


def test_playing_a_dictation_stops_a_transcript_playing(start):
    app = opened(start)
    (app.data / "audio").mkdir(exist_ok=True)
    soundfile.write(str(app.data / "audio" / "monday.wav"), np.zeros(16000, np.int16), 16000)
    (app.data / "dictations.jsonl").write_text(
        '{"t": "2026-10-19T09:00:00", "text": "Morning all.", "app": "Slack", "cleanup": false, '
        '"audio": "monday.wav"}\n')
    mark = app.mark()
    app.click("Play", "Transcripts")
    app.wait_for("playing", after=mark)

    app.send("select", row="Dictations", window_title="Transcripts")
    mark = app.mark()
    app.click("Play", "Dictations")

    assert app.wait_for("playing", after=mark)["path"].endswith("monday.wav")
    app.send("select", row="Transcripts", window_title="Dictations")
    eventually(lambda: "Stop" not in app.read("Transcripts"))


def mixes(app):
    return list((app.home / ".cache" / "dictate" / "mixes").glob("*.wav"))


def test_the_copy_mixed_to_play_from_is_deleted_with_the_transcript(start):
    app = opened(start)
    mark = app.mark()
    app.click("Play", "Transcripts")
    app.wait_for("playing", after=mark)
    assert len(mixes(app)) == 1

    app.click("Delete", "Transcripts")
    app.click("Delete")

    eventually(lambda: mixes(app) == [])


def test_the_copy_mixed_to_play_from_goes_when_its_recordings_do(start):
    app = opened(start)
    mark = app.mark()
    app.click("Play", "Transcripts")
    app.wait_for("playing", after=mark)
    app.click("Stop", "Transcripts")
    assert len(mixes(app)) == 1

    app.send("select", row="Settings", window_title="Transcripts")
    app.send("choose", option="Don't keep", window_title="Settings", setting="Keep transcript recordings")

    eventually(lambda: mixes(app) == [])


def test_a_paragraph_played_to_its_end_stays_highlighted_not_the_next(start):
    app = opened(start)
    play_paragraph(app, "Shall we start with the roadmap?")
    eventually(lambda: highlighted(app) == ["10:00:00 Them  Shall we start with the roadmap?"])

    time.sleep(3.5)  # past its end, at 10:00:03 (the stand-in player never finishes by itself)

    assert highlighted(app) == ["10:00:00 Them  Shall we start with the roadmap?"]


FROM_HERE, BEFORE_HERE = "Delete from here to the end…", "Delete everything before here…"


def right_click(app, text):
    items = app.send("right_click_text", text=text, window_title="Transcripts")["items"]
    return {m["label"]: m["enabled"] for m in items}


def trimmed(app, text, item):
    right_click(app, text)
    app.send("choose_from_menu", label=item)
    app.wait_window(None)
    app.click("Delete")


def seconds(app, who, name=NAME):
    audio, rate = soundfile.read(str(app.data / "transcripts" / f"{name} {who}.ogg"))
    return audio, rate


LATER = "2026-10-19 10.00.06"  # (what's left of the call, everything before 10:00:06 deleted, starts then)


def test_a_paragraphs_menu_can_delete_from_it_to_the_end_text_and_audio(start):
    app = opened(start)
    assert right_click(app, "Yes, the roadmap first.") == {FROM_HERE: True, BEFORE_HERE: True}
    assert right_click(app, "Shall we start")[BEFORE_HERE] is False  # (nothing's before the first)

    trimmed(app, "Yes, the roadmap first.", FROM_HERE)

    eventually(lambda: "Yes, the roadmap first." not in app.transcript())
    md = (app.data / "transcripts" / f"{NAME}.md").read_text()
    assert "Shall we start with the roadmap?" in md and "roadmap first" not in md and "the budget" not in md
    audio, rate = seconds(app, "me")
    assert abs(len(audio) / rate - 3) < 0.1  # (cut off at 10:00:03)


def test_a_paragraphs_menu_can_delete_everything_before_it_text_and_audio(start):
    app = opened(start)

    trimmed(app, "Then the budget.", BEFORE_HERE)

    eventually(lambda: "Shall we start" not in app.transcript())
    folder = app.data / "transcripts"
    assert sorted(f.name for f in folder.iterdir()) == [f"{LATER} me.ogg", f"{LATER} summary.json", f"{LATER} them.ogg",
                                                        f"{LATER}.md"]  # (renamed: the call starts later now)
    md = (folder / f"{LATER}.md").read_text()
    assert "Then the budget." in md and "Shall we start" not in md and "roadmap first" not in md
    audio, rate = seconds(app, "them", LATER)
    assert abs(len(audio) / rate - 4) < 0.1  # (cut off before 10:00:06)
    mark = app.mark()
    app.click("Play", "Transcripts")  # (what's left still plays at its times: the last paragraph, from 0 s)
    audio, rate = soundfile.read(app.wait_for("playing", after=mark)["path"])
    assert abs(len(audio) / rate - 4) < 0.1


def test_deleting_from_the_first_paragraph_deletes_the_transcript(start):
    app = opened(start)

    trimmed(app, "Shall we start", FROM_HERE)

    eventually(lambda: not list((app.data / "transcripts").glob("*")))


def test_after_deleting_part_the_summary_is_written_again_from_what_is_left(start, model):
    model.rules({"prompt": "running summary of a meeting", "reply": "## Overview\nOnly the budget."})
    app = opened(start)
    (app.data / "transcripts" / f"{NAME} summary.json").write_text(
        '{"text": "## Overview\\nThe roadmap, then the budget.", "final": true}')

    trimmed(app, "Then the budget.", BEFORE_HERE)

    md = app.data / "transcripts" / f"{LATER}.md"
    eventually(lambda: md.exists() and "Only the budget." in md.read_text())
    asked = [r for r in model.requests() if "running summary of a meeting" in r["system"]]
    assert asked and all("roadmap" not in r["user"] for r in asked)  # (what's deleted isn't sent)
