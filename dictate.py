#!/usr/bin/env python3
"""Dictate: hold Ctrl+Win (Ctrl+Cmd on a Mac) to record, release to transcribe and paste.

Floating icon (drag to move, right-click for menu), drawn with GTK3. The hotkey, recording and paste
are in osio.py, transcription in stt.py, clean-up / restyling in refine.py, windows in windows.py.
On KDE Wayland, GTK is forced onto XWayland so the icon can stay on top and be positioned.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(HERE, ".venv", "Scripts", "pythonw.exe") if sys.platform == "win32" else os.path.join(HERE, ".venv/bin/python")
if sys.prefix == sys.base_prefix and os.path.exists(VENV_PY):  # launched with system python → use ours
    os.execv(VENV_PY, [VENV_PY, *sys.argv])
if sys.platform.startswith("linux"):
    os.environ["GDK_BACKEND"] = "x11"
elif sys.platform == "win32":  # GTK runtime unpacked into ./gtk by setup-windows.ps1
    GTK = os.path.join(HERE, "gtk")
    os.add_dll_directory(os.path.join(GTK, "bin"))
    os.environ["PATH"] = os.path.join(GTK, "bin") + os.pathsep + os.environ["PATH"]
    os.environ["GI_TYPELIB_PATH"] = os.path.join(GTK, "lib", "girepository-1.0")
    os.environ["XDG_DATA_DIRS"] = os.path.join(GTK, "share")

import json, math, signal, tempfile, threading, time
from datetime import datetime
from pathlib import Path
import cairo, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import activewin, osio, refine, stt, windows

DATA = Path(__file__).parent / "data"  # everything stays inside this folder
HISTORY = DATA / "history.jsonl"
STATE = DATA / "state.json"
SIZE, R = 52, 17  # window size, icon radius (margin leaves room for the pulse ring)
TERMINALS = ("konsole", "terminal", "kitty", "alacritty", "wezterm", "foot", "ghostty", "yakuake")  # Linux paste
ACCENT = (0.49, 0.55, 1.0)
BODY = {  # (top, bottom) gradient colours per state
    "idle": ((0.20, 0.21, 0.24), (0.11, 0.12, 0.14)),
    "rec": ((1.0, 0.39, 0.36), (0.85, 0.20, 0.22)),
    "busy": ((0.20, 0.21, 0.24), (0.11, 0.12, 0.14)),
}
def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


class App:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        windows.install_css()

        w = self.win = Gtk.Window(type_hint=Gdk.WindowTypeHint.UTILITY, decorated=False,
                                  skip_taskbar_hint=True, skip_pager_hint=True, app_paintable=True)
        w.set_visual(w.get_screen().get_rgba_visual())  # per-pixel transparency → round icon
        w.set_keep_above(True)
        w.set_default_size(SIZE, SIZE)
        self.cfg = {"pos": [100, 100], "refine": True, **load_json(STATE, {})}
        w.move(*self.cfg["pos"])
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        w.connect("draw", self.draw)
        w.connect("button-press-event", self.on_click)
        w.connect("configure-event", self.on_moved)
        w.connect("enter-notify-event", lambda *_: self.hover(True))
        w.connect("leave-notify-event", lambda *_: self.hover(False))
        w.connect("destroy", Gtk.main_quit)
        if not osio.WINDOWS:  # quit cleanly so exit hooks (e.g. unloading the KWin script) run
            for sig in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, Gtk.main_quit)

        self.menu = Gtk.Menu()
        toggle = Gtk.CheckMenuItem(label="Refine text", active=self.cfg["refine"])
        toggle.connect("toggled", lambda t: self.save_state(refine=t.get_active()))
        self.menu.append(toggle)
        default = Gtk.MenuItem(label="Default style")
        self.default_menu = Gtk.Menu()
        default.set_submenu(self.default_menu)
        self.menu.append(default)
        for label, cb in (("History", self.show_history), ("Refinement styles…", windows.StyleManager), (None, None), ("Quit", Gtk.main_quit)):
            item = Gtk.MenuItem(label=label) if label else Gtk.SeparatorMenuItem()
            if cb:
                item.connect("activate", lambda _, cb=cb: cb())
            self.menu.append(item)
        self.menu.show_all()

        self.state, self.hovered, self.rec, self.wav, self.anim, self.save_id = "idle", False, None, None, None, None
        self.t0 = time.monotonic()
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.app = activewin.snapshot()
        activewin.start()
        osio.Hotkey(self.on_hotkey).start()
        threading.Thread(target=stt.load, daemon=True).start()  # warm up so first dictation is fast
        self.paster = osio.Paster()  # created after Hotkey so we don't listen to ourselves
        w.show_all()

    # --- icon ---
    def set_state(self, s):
        self.state = s
        if s != "idle" and not self.anim:
            self.anim = GLib.timeout_add(16, lambda: self.win.queue_draw() or self.state != "idle")
        if s == "idle":
            self.anim = None
        self.win.queue_draw()

    def hover(self, on):
        self.hovered = on
        self.win.queue_draw()

    def draw(self, _, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        c, t = SIZE / 2, time.monotonic() - self.t0

        if self.state == "rec":  # expanding pulse rings
            for k in (0, 0.5):
                p = (t * 0.9 + k) % 1
                cr.arc(c, c, R + p * (SIZE / 2 - R - 1), 0, 2 * math.pi)
                cr.set_source_rgba(1, 0.35, 0.33, 0.45 * (1 - p))
                cr.set_line_width(2)
                cr.stroke()

        for i in range(4):  # soft drop shadow
            cr.arc(c, c + 1.5, R + 3 - i, 0, 2 * math.pi)
            cr.set_source_rgba(0, 0, 0, 0.07)
            cr.fill()

        top, bot = BODY[self.state]
        lift = 0.05 if self.hovered and self.state == "idle" else 0
        g = cairo.LinearGradient(0, c - R, 0, c + R)
        g.add_color_stop_rgb(0, *(v + lift for v in top))
        g.add_color_stop_rgb(1, *(v + lift for v in bot))
        cr.arc(c, c, R, 0, 2 * math.pi)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.set_line_width(1)
        cr.stroke()

        if self.state == "busy":  # spinner arc
            a = t * 5
            cr.arc(c, c, R - 3, a, a + 1.6 * math.pi / 2)
            cr.set_source_rgb(*ACCENT)
            cr.set_line_width(2.2)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.stroke()

        # microphone glyph
        cr.set_source_rgba(1, 1, 1, 0.95 if self.state != "idle" else 0.85)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        w, h, top_y = 6, 10, c - 8
        cr.new_sub_path()
        cr.arc(c, top_y + w / 2, w / 2, math.pi, 0)
        cr.arc(c, top_y + h - w / 2, w / 2, 0, math.pi)
        cr.close_path()
        cr.fill()
        cr.set_line_width(1.6)
        cr.arc(c, top_y + h - w / 2, 6, 0, math.pi)
        cr.stroke()
        cr.move_to(c, top_y + h + 3)
        cr.line_to(c, top_y + h + 5.5)
        cr.stroke()

    # --- move / menu ---
    def on_click(self, w, ev):
        if ev.button == 1:
            w.begin_move_drag(1, int(ev.x_root), int(ev.y_root), ev.time)
        elif ev.button == 3:
            self.build_default_menu()
            self.menu.popup_at_pointer(ev)
        return True

    def build_default_menu(self):
        """Radio list: which style a plain Ctrl+Win applies after cleanup (rebuilt each time, as styles change)."""
        for item in self.default_menu.get_children():
            self.default_menu.remove(item)
        current, group = refine.default_style(), None
        for name in [None] + [s["name"] for s in refine.load_styles()["styles"]]:
            item = Gtk.RadioMenuItem(label=name or "None (cleanup only)", group=group,
                                     active=name == (current and current["name"]))
            group = group or item
            item.connect("toggled", lambda i, n=name: i.get_active() and refine.set_default(n))
            self.default_menu.append(item)
        self.default_menu.show_all()

    def on_moved(self, *_):
        if self.save_id:
            GLib.source_remove(self.save_id)
        self.save_id = GLib.timeout_add(500, lambda: self.save_state(pos=list(self.win.get_position())))

    def save_state(self, **changes):
        self.cfg.update(changes)
        STATE.write_text(json.dumps(self.cfg))
        self.save_id = None

    # --- recording pipeline ---
    def on_hotkey(self, down, alt, letter):
        if down and not self.rec:
            self.app = activewin.snapshot()  # where the text will go (before any of our windows take focus)
            self.wav = tempfile.mktemp(suffix=".wav", prefix="dictate-")
            self.rec = osio.Recorder()
            self.rec.start(self.wav)
            self.set_state("rec")
        if down and (self.cfg["refine"] or alt):
            refine.warm()  # load the model while the user is still speaking
        elif not down and self.rec:
            self.rec.stop()
            self.rec = None
            self.set_state("busy")
            refining = self.cfg["refine"] or alt  # Alt asks for a style, which always includes cleanup
            threading.Thread(target=self.process, args=(self.wav, refining, alt, letter, self.app), daemon=True).start()

    def process(self, wav, refining, alt, letter, app):
        """Transcribe → cleanup → a style: Alt+letter's, or (Alt alone / unknown letter) ask which,
        or (no Alt) the style matching the focused app, else the default style."""
        raw = text = style = ""
        ctx = activewin.describe(app)
        try:
            raw = text = stt.transcribe(wav)
            if refining and raw:
                text = refine.cleanup(raw, ctx)
            if alt and raw:
                style = letter and refine.style_for_key(letter)
                if not style:
                    return GLib.idle_add(self.pick_style, text, raw, app)
            elif refining and raw:
                style = refine.style_for_app(f"{app['cls']} {app['title']}") or refine.default_style()
            if style:
                text = refine.apply(text, style, ctx)
        except Exception as err:  # never leave the icon stuck on "busy"
            print("transcription failed:", err)
        finally:
            Path(wav).unlink(missing_ok=True)
            if refining:
                refine.release()
        GLib.idle_add(self.paste, text, raw, app, style and style["name"])

    def paste(self, text, raw, app, style=None, paste=True, delay=150):
        self.set_state("idle")
        if not text:
            return
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "text": text, "app": app["cls"]}
        if raw != text:
            entry["raw"] = raw
        if style:
            entry["style"] = style
        with HISTORY.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self.copy(text)
        if paste:  # wait for the clipboard to reach Wayland (and, after the picker, for focus to return)
            terminal = osio.LINUX and any(t in app["cls"].lower() for t in TERMINALS)
            GLib.timeout_add(delay, self.paster.paste, terminal)

    def copy(self, text):
        self.clip.set_text(text, -1)
        self.clip.store()

    # --- windows ---
    def show_history(self):
        windows.history(self, HISTORY)

    def pick_style(self, text, raw, app):
        def chosen(style, paste):
            if not style:
                return self.paste(text, raw, app, paste=paste, delay=400)
            self.set_state("busy")
            threading.Thread(target=lambda: GLib.idle_add(
                self.paste, refine.apply(text, style, activewin.describe(app)), raw, app, style["name"], True, 400),
                daemon=True).start()
        windows.StylePicker(text, chosen)

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    App().run()
