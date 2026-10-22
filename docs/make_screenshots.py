#!/usr/bin/env python3
"""Regenerates the screenshots in docs/ from sample data: python docs/make_screenshots.py [folder] [--light]

Everything is drawn off-screen and saved straight to PNG, so nothing on the screen is captured and no real
history, styles or settings are used. Translucent things (the capsule, HUDs) are shown over a backdrop."""
import json, shutil, sys, tempfile, time, wave
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import dictate  # noqa: E402
dictate.bootstrap()
import cairo, gi  # noqa: E402
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, PangoCairo  # noqa: E402
from dictate import capsule, design, huds, hub, osio, refine, summary, topics, transcript, voices  # noqa: E402
from dictate.app import KEEP_AUDIO, REMOTE_MODES, SAME  # noqa: E402

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
        ("10:00:04", "Priya", "Morning, everyone. Shall we start with the roadmap and leave hiring for the end?"),
        ("10:00:11", "Me", "Sounds good. I'd like to talk about the release date first, because it affects everything else.")]),
    "2026-10-19 16.30.00": ("1 h 05 min", [("16:30:02", "Speaker 1", "Welcome to the talk. Today I want to show you how "
                                                                  "speech recognition got small enough to run on a laptop.")]),
    "2026-10-16 09.15.00": ("12 min", [("09:15:06", "Speaker 1", "Hi, thanks for calling. How can I help?"),
                                       ("09:15:09", "Me", "Hi, I'm calling about my broadband bill.")]),
}
SAID = [  # the call being transcribed: (clock, who, text, topic)
    ("14:02:03", "Priya", "Can everyone see my screen? This is the dashboard from last week.", None),
    ("14:02:07", "Speaker 2", "Yes, but it's a bit blurry.", None),
    ("14:02:12", "Priya", "So the sign-ups dropped on Thursday, and we think it's the new form.", 0),
    ("14:02:20", "Me", "Is it the form, or the email check we added?", 0),
    ("14:02:26", "Speaker 2", "The email check. Half the codes never arrive.", 0),
    ("14:03:02", "Me", "Then the release has to wait. Can we move it to the tenth?", 1),
    ("14:03:09", "Priya", "The tenth works, QA gets the whole week.", 1),
    ("14:03:31", "Priya", "Back to the codes: Sam, can you check the email provider today?", 0)]


SUMMARY = """## Overview
Priya is walking through last week's dashboard: sign-ups fell on Thursday, and the release date depends on why.
## Discussed
- **Sign-ups:** Priya thought the new form; Speaker 2 says it's the email check, as half the codes never arrive.
- **Release date:** Me would rather move it than ship the login work half done.
## Agreed
- The release moves to the tenth, so QA gets the whole week.
## Action points
- **Sam:** check the email provider today.
## Open questions
- Whether rolling back the new form is still needed."""


def pump():
    for _ in range(60):
        while Gtk.events_pending():
            Gtk.main_iteration()


def wrote(path):
    print("wrote", path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def save(widget, path, size, classes=(), backdrop=False):
    """Draw widget (taken out of its window) off-screen at size and save it; over a backdrop if translucent."""
    off = design.grayscale(Gtk.OffscreenWindow())
    design.classes(off, *classes)
    if widget.get_parent():
        widget.get_parent().remove(widget)
    if backdrop:  # painted under it, in the same window (so translucency blends as it would on a desktop)
        holder = Gtk.Box()
        holder.connect("draw", lambda w, cr: paint_backdrop(cr, w.get_allocated_width(), w.get_allocated_height()))
        holder.pack_start(widget, True, True, 0)
        widget = holder
    off.add(widget)
    off.set_size_request(*size)
    widget.show_all()
    off.show()
    pump()
    off.get_pixbuf().savev(str(path), "png", [], [])
    wrote(path)
    off.destroy()


def paint_backdrop(cr, w, h):
    """A desktop-ish background: a soft gradient, darker in dark mode."""
    g = cairo.LinearGradient(0, 0, w, h)
    if design.scheme == "dark":
        g.add_color_stop_rgb(0, 0.16, 0.18, 0.26)
        g.add_color_stop_rgb(1, 0.09, 0.10, 0.14)
    else:
        g.add_color_stop_rgb(0, 0.80, 0.84, 0.93)
        g.add_color_stop_rgb(1, 0.93, 0.91, 0.95)
    cr.set_source(g)
    cr.paint()


def fake_app(tmp, session=None):
    return SimpleNamespace(
        DICTATIONS=tmp / "dictations.jsonl", AUDIO=tmp / "audio", KEEP_AUDIO=KEEP_AUDIO, REMOTE_MODES=REMOTE_MODES, SAME=SAME,
        cfg={"keep_audio_hours": 24, "keep_call_hours": 168, "refine": True, "remote_mode": "type"},
        player=osio.Player(), copy=lambda text: None, set_keep_audio=lambda hours: None, set_keep_calls=lambda hours: None, save_state=lambda **kw: None,
        set_refine=lambda on: None, autostart=lambda: True, set_autostart=lambda on: None,
        session=session, stop_transcribing=lambda: None)


def hub_shot(tmp, page, path, size=(1120, 640), session=None, tab=None):
    """A page of the Dictate window, its header bar and all (Transcripts: on its tab, if given)."""
    h = hub.Hub(fake_app(tmp, session))
    h.win.show = h.win.present = lambda *a: None  # (never on the real screen)
    shown = h.show(page)
    if tab:
        shown.tabs.set_visible_child_name(tab)
        shown.switch.choose(tab)
    bar, body = h.win.get_titlebar(), h.win.get_child()
    h.win.set_titlebar(None)
    h.win.remove(body)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.pack_start(bar, False, False, 0)
    box.pack_start(body, True, True, 0)
    save(box, path, size, ("dictate",))
    h.win.destroy()


def capsule_states(path, session):
    """The capsule in each state, side by side, at 2×."""
    states = [("Idle", "idle", None, 0.0), ("Dictating", "rec", None, 0.8), ("Working", "busy", None, 0.0),
              ("Transcribing a call", "idle", session, 0.0)]
    scale, gap, cell = 2, 16, 230
    width, height = cell * len(states) + gap, capsule.H + 2 * capsule.PAD + 24
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width * scale, height * scale)
    cr = cairo.Context(surface)
    cr.scale(scale, scale)
    paint_backdrop(cr, width, height)
    for n, (label, state, sess, level) in enumerate(states):
        cap = capsule.Capsule()
        cap.update(state, sess, time.time() - 4, lambda level=level: level)
        cap.width, cap.loud, cap.t0 = cap.target, level, time.monotonic() - 0.4
        if cap.ticking:
            GLib.source_remove(cap.ticking)
        cr.save()
        cr.translate(gap + n * cell - capsule.PAD, 0)
        cap.draw(cr, clear=False)
        cr.restore()
        lay, w, h = design.layout(cr, label, "caption")
        c = design.rgba("text-2")
        cr.set_source_rgba(c.red, c.green, c.blue, 1)
        cr.move_to(gap + n * cell, capsule.H + 2 * capsule.PAD)
        PangoCairo.show_layout(cr, lay)
        cap.win.destroy()
    surface.write_to_png(str(path))
    wrote(path)


def main(out):
    if "--light" in sys.argv:
        design._desktop_scheme = lambda: "light"
    design.install()
    tmp = Path(tempfile.mkdtemp())
    refine.STYLES, refine.VOCAB = tmp / "styles.json", tmp / "vocab.txt"  # the built-in default styles
    refine.save_styles({"cleanup": refine.CLEANUP, "styles": refine.DEFAULT_STYLES})
    (tmp / "audio").mkdir()
    today, lines = transcript.datetime.now().strftime("%Y-%m-%d"), []
    for when, text, raw, app_name, style, has_audio in SAMPLE:
        entry = {"t": f"{today if when > '12' else '2026-10-20'}T{when}", "text": text, "app": app_name,
                 "cleanup": raw is not None}
        if raw:
            entry["raw"] = raw
        if style:
            entry["style"] = style
        if has_audio:
            entry["audio"] = f"{when}.wav"
            with wave.open(str(tmp / "audio" / entry["audio"]), "wb") as w:  # a silent placeholder recording
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(bytes(3200))
        lines.append(json.dumps(entry))
    (tmp / "dictations.jsonl").write_text("\n".join(lines) + "\n")
    voices.remembered = lambda: [("Priya", None), ("Sam", None)]
    voices.remembering = voices.available = lambda: True

    for page in ("dictations", "styles", "settings", "voices"):
        hub_shot(tmp, page, out / f"{page}.png")

    transcript.FOLDER = tmp / "transcripts"
    transcript.FOLDER.mkdir()
    for name, (took, paragraphs) in TRANSCRIPTS.items():
        (transcript.FOLDER / f"{name}.md").write_text(f"# Transcript\n\nLasted {took}, until 00:00.\n" + "".join(
            f"\n**{clock} {who}:** {text}\n" for clock, who, text in paragraphs))
    now = transcript.FOLDER / "2026-10-21 14.02.00.md"  # being recorded
    now.write_text("")
    found = topics.Topics({"topics": [
        {"title": "Sign-ups dropped", "colour": 0, "points": [
            "Priya: sign-ups fell on Thursday, maybe because of the new form.",
            "Speaker 2: it's the email check; half the codes never arrive.",
            "Priya asks Sam to check the email provider today."]},
        {"title": "Release date", "colour": 1, "points": [
            "Me wants to move the release to the tenth; Priya agrees, so QA gets the week."]}], "now": 0})
    t0 = time.monotonic() - 754
    live = SimpleNamespace(path=now, started=transcript.datetime(2026, 10, 21, 14, 2), paused=False, voices=True,
                           now=lambda: time.monotonic() - t0, topics=found, summary=summary.Summary(SUMMARY),
                           previews=lambda: [("14:03:40", "…", "And if it's the provider, we")],
                           paragraphs=lambda: [p[:3] for p in SAID],
                           topic_view=lambda: (found, {i: p[3] for i, p in enumerate(SAID) if p[3] is not None},
                                               [["Priya", "Me", "Speaker 2"], ["Me", "Priya"]]))
    hub_shot(tmp, "transcripts", out / "transcripts.png", (1180, 600), session=live)
    hub_shot(tmp, "transcripts", out / "summary.png", (1180, 600), session=live, tab="Summary")

    picker = huds.StylePicker("So for the release, we need to fix the login bug, write the release notes, and then "
                              "tell marketing.", lambda *a: None)
    save(picker.hud.card, out / "picker.png", (-1, -1), ("hud-window",), backdrop=True)
    picker.hud.win.destroy()
    cap = capsule.Capsule()
    cap.update("idle", live)
    cap.width = cap.target
    reminder = huds.StillTranscribing("closed", 10, cap.picture(), (100, 100, 36, 36), lambda: None)
    save(reminder.hud.card, out / "reminder.png", (-1, -1), ("hud-window",), backdrop=True)
    reminder.hud.win.destroy()
    capsule_states(out / "capsule-states.png", live)
    if out == DOCS:
        wrote(design.save_app_icon())
    shutil.rmtree(tmp)


if __name__ == "__main__":
    folders = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(Path(folders[0]) if folders else DOCS)
