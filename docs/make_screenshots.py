#!/usr/bin/env python3
"""Regenerates the README screenshots in docs/ from sample data: python docs/make_screenshots.py

Windows are drawn off-screen and saved straight to PNG, so nothing on the screen is captured and no
real history, styles or settings are used."""
import json, os, shutil, sys, tempfile, wave
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import dictate  # noqa: E402
dictate.bootstrap()
from dictate import dialogs, osio, refine, transcript  # noqa: E402
from dictate.app import KEEP_AUDIO  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

DOCS = ROOT / "docs"
SAMPLE = [  # (time, text, raw, app, style, has a recording)
    ("09:12:04", "Morning! Can you send me the slides before the 10 o'clock?",
     "um morning can you can you send me the slides before the uh ten o'clock", "Slack", "Slack", True),
    ("11:40:31", "For the release, we need to:\n- fix the login bug\n- write the release notes\n- tell marketing",
     "so for the release we need to uh fix the login bug write the release notes and then tell marketing", "Slack", "Slack", True),
    ("14:05:12", "Run the tests with `pytest -k login` and tell me what fails.",
     "run the tests with pytest dash k login and tell me what fails", "other computer", "AI agent", True),
    ("15:22:47", "running about ten minutes late sorry", None, "firefox", None, False),
]
TRANSCRIPTS = {  # file name: (how long, [(clock, who, text)])
    "2026-10-20 10.00.00": ("32 min", [
        ("10:00:04", "Them", "Morning, everyone. Shall we start with the roadmap and leave hiring for the end?"),
        ("10:00:11", "Me", "Sounds good. I'd like to talk about the release date first, because it affects everything else."),
        ("10:00:19", "Them", "Fair. So the plan was the third of November, but the login work is running about a week late. "
                             "We could ship without it, or move the date."),
        ("10:00:41", "Me", "I'd rather move the date than ship half of it."),
        ("10:00:47", "Them", "Okay. Then the tenth? That gives QA the whole week."),
    ]),
    "2026-10-19 16.30.00": ("1 h 05 min", [("16:30:02", "Them", "Welcome to the talk. Today I want to show you how "
                                                                  "speech recognition got small enough to run on a laptop.")]),
    "2026-10-16 09.15.00": ("12 min", [("09:15:06", "Them", "Hi, thanks for calling. How can I help?"),
                                       ("09:15:09", "Me", "Hi, I'm calling about my broadband bill.")]),
}


def offscreen(win, path, classes, size):
    """Move a window's header bar and contents into an off-screen window and save it as a PNG."""
    bar, body = win.get_titlebar(), win.get_child()
    win.hide()
    win.set_titlebar(None)
    win.remove(body)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.pack_start(bar, False, False, 0)
    box.pack_start(body, True, True, 0)
    off = Gtk.OffscreenWindow()
    dialogs.css(off, *classes)
    off.add(box)
    off.set_size_request(*size)
    box.show()  # not show_all(): that would also show widgets the window hides on purpose
    off.show()
    for _ in range(50):  # let GTK lay out and paint
        while Gtk.events_pending():
            Gtk.main_iteration()
    off.get_pixbuf().savev(str(path), "png", [], [])
    print("wrote", path.relative_to(ROOT))
    win.destroy()
    off.destroy()


def main():
    tmp = Path(tempfile.mkdtemp())
    refine.STYLES, refine.VOCAB = tmp / "styles.json", tmp / "vocab.txt"  # the built-in default styles
    refine.save_styles({"cleanup": refine.CLEANUP, "styles": refine.DEFAULT_STYLES})
    audio = tmp / "audio"
    audio.mkdir()
    history, lines = tmp / "history.jsonl", []
    for when, text, raw, app, style, has_audio in SAMPLE:
        entry = {"t": f"2026-10-20T{when}", "text": text, "app": app, "cleanup": raw is not None}
        if raw:
            entry["raw"] = raw
        if style:
            entry["style"] = style
        if has_audio:
            entry["audio"] = f"{when}.wav"
            with wave.open(str(audio / entry["audio"]), "wb") as w:  # a silent placeholder recording
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(bytes(3200))
        lines.append(json.dumps(entry))
    history.write_text("\n".join(lines) + "\n")

    dialogs.install_css()
    app = SimpleNamespace(player=osio.Player(), cfg={"keep_audio_hours": 24}, KEEP_AUDIO=KEEP_AUDIO,
                          set_keep_audio=lambda hours: None, copy=lambda text: None)
    dialogs.history(app, history, audio)
    offscreen(next(w for w in Gtk.Window.list_toplevels() if w.get_title() == "History"), DOCS / "history.png", ["win"], (760, 470))

    picker = dialogs.StylePicker("So for the release, we need to fix the login bug, write the release notes, "
                                 "and then tell marketing.", lambda *a: None)
    offscreen(picker.win, DOCS / "picker.png", ["win"], (520, -1))

    manager = dialogs.StyleManager()
    manager.list.select_row(manager.list.get_row_at_index(manager.FIXED))  # the first style (Slack)
    offscreen(manager.win, DOCS / "styles.png", ["win", "editor"], (760, 560))

    transcript.FOLDER = tmp / "transcripts"
    transcript.FOLDER.mkdir()
    for name, (took, paragraphs) in TRANSCRIPTS.items():
        (transcript.FOLDER / f"{name}.md").write_text(f"# Transcript\n\nLasted {took}, until 00:00.\n" + "".join(
            f"\n**{clock} {who}:** {text}\n" for clock, who, text in paragraphs))
    browser = dialogs.TranscriptsWindow(lambda: None)
    offscreen(browser.win, DOCS / "transcripts.png", ["win"], (900, 440))
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
