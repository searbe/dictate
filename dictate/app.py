"""The floating icon (drag to move, right-click for menu), drawn with GTK3, and the dictation pipeline:
record → transcribe → cleanup → style → paste or type. Started by dictate.py, after dictate.bootstrap().
Ctrl+Win, lift Win, Win again starts or stops transcribe mode (transcript.py).
"""
import json, math, os, signal, socket, sys, threading, time
from datetime import datetime
from pathlib import Path
import cairo, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk, Gdk, GLib
from . import DATA, activewin, dialogs, osio, refine, remote, stt, transcript, tray

HISTORY = DATA / "history.jsonl"
AUDIO = DATA / "audio"  # each dictation's recording, kept for playback for "keep_audio_hours"
KEEP_AUDIO = ((0, "Don't keep"), (1, "1 hour"), (2, "2 hours"), (3, "3 hours"), (12, "12 hours"), (24, "24 hours"),
              (None, "Forever (∞)"))  # hours; None = never delete
STATE = DATA / "state.json"
SIZE, R = 52, 17  # window size, icon radius (margin leaves room for the pulse ring)
REMOTE_MODES = (("type", "Type the text there"), ("ignore", "Ignore the hotkey"))
SAME = "same"  # remote default style: same as here
OTHER_COMPUTER = {"cls": "", "title": "", "remote": True}  # where text goes when Synergy has the keyboard
TERMINALS = ("konsole", "terminal", "kitty", "alacritty", "wezterm", "foot", "ghostty", "yakuake")  # Linux paste
ACCENT = (0.49, 0.55, 1.0)
BODY = {  # (top, bottom) gradient colours per state
    "idle": ((0.20, 0.21, 0.24), (0.11, 0.12, 0.14)),
    "rec": ((1.0, 0.39, 0.36), (0.85, 0.20, 0.22)),
    "busy": ((0.20, 0.21, 0.24), (0.11, 0.12, 0.14)),
}
def log(msg):
    """Timestamped, flushed at once (stdout is buffered when launched from the desktop): see journalctl."""
    print(f"{datetime.now():%H:%M:%S.%f}"[:-3], msg, flush=True)


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


class App:
    KEEP_AUDIO = KEEP_AUDIO
    TRANSCRIBE = "Transcribe this computer"

    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        dialogs.install_css()

        w = self.win = Gtk.Window(type_hint=Gdk.WindowTypeHint.UTILITY, decorated=False,
                                  skip_taskbar_hint=True, skip_pager_hint=True, app_paintable=True)
        w.set_visual(w.get_screen().get_rgba_visual())  # per-pixel transparency → round icon
        w.set_keep_above(True)
        w.set_default_size(SIZE, SIZE)
        self.cfg = {"pos": [100, 100], "refine": True, "remote_mode": "type", "keep_audio_hours": 24,
                    **load_json(STATE, {})}
        self.cfg.pop("remote_guard", None)  # setting from an older version
        w.move(*self.cfg["pos"])
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        w.connect("draw", self.draw)
        w.connect("button-press-event", self.on_click)
        w.connect("configure-event", self.on_moved)
        w.connect("enter-notify-event", lambda *_: self.hover(True))
        w.connect("leave-notify-event", lambda *_: self.hover(False))
        w.connect("destroy", lambda _: self.quit("the icon's window was destroyed"))
        if not osio.WINDOWS:  # quit cleanly so exit hooks (e.g. unloading the KWin script) run
            for sig in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda sig=sig: self.quit(f"got {sig.name}"))

        self.menu = Gtk.Menu()
        toggle = Gtk.CheckMenuItem(label="Refine text", active=self.cfg["refine"])
        toggle.connect("toggled", lambda t: self.save_state(refine=t.get_active()))
        self.menu.append(toggle)
        default = Gtk.MenuItem(label="Default style")
        self.default_menu = Gtk.Menu()
        default.set_submenu(self.default_menu)
        self.menu.append(default)
        for label, cb in (("History", self.show_history), ("Refinement styles…", dialogs.StyleManager), (None, None)):
            item = Gtk.MenuItem(label=label) if label else Gtk.SeparatorMenuItem()
            if cb:
                item.connect("activate", lambda _, cb=cb: cb())
            self.menu.append(item)
        if osio.HEARS_SPEAKERS:
            self.transcribe_item = Gtk.MenuItem(label=self.TRANSCRIBE)
            self.transcribe_item.connect("activate", lambda _: self.toggle_transcribing())
            folder = Gtk.MenuItem(label="Transcripts folder")
            folder.connect("activate", lambda _: self.open_folder(transcript.FOLDER))
            for item in (self.transcribe_item, folder, Gtk.SeparatorMenuItem()):
                self.menu.append(item)
        away = Gtk.MenuItem(label="When another computer has the keyboard")  # e.g. through Synergy
        away_menu, group = Gtk.Menu(), None
        for mode, label in REMOTE_MODES:
            item = Gtk.RadioMenuItem(label=label, group=group, active=mode == self.cfg["remote_mode"])
            group = group or item
            away_menu.append(item)
        for item, (mode, _) in zip(away_menu.get_children(), REMOTE_MODES):  # connected after ticking,
            item.connect("toggled", lambda i, m=mode: i.get_active() and self.save_state(remote_mode=m))  # so setup isn't saved
        away_menu.append(Gtk.SeparatorMenuItem())
        remote_style = Gtk.MenuItem(label="Default style there")  # per-app styles can't apply: we can't see its apps
        self.remote_style_menu = Gtk.Menu()
        remote_style.set_submenu(self.remote_style_menu)
        away_menu.append(remote_style)
        away.set_submenu(away_menu)
        self.menu.append(away)
        startup = Gtk.CheckMenuItem(label="Run at startup", active=osio.autostart_enabled())
        startup.connect("toggled", lambda t: osio.set_autostart(t.get_active()))
        self.menu.append(startup)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: self.quit("Quit chosen from the menu"))
        self.menu.append(quit_item)
        self.menu.show_all()
        self.build_default_menu()

        self.state, self.hovered, self.rec, self.wav, self.anim, self.save_id = "idle", False, None, None, None, None
        self.session = self.transcript_win = self.cancelled = None  # transcribe mode; a dictation to drop
        self.t0 = time.monotonic()
        self.tray = tray.Tray(self.menu, self.render_icon, self.build_default_menu)  # same menu in the system tray
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.app = activewin.snapshot()
        # the menu is an XWayland popup: a click on a Wayland app never reaches it, so it can't tell it
        # should close. KWin tells us when another app gets focus instead.
        activewin.on_switch.append(lambda: self.menu.get_visible() and self.menu.popdown())
        activewin.start()
        remote.start()
        self.hotkey = osio.Hotkey(self.on_hotkey, self.on_again)
        self.hotkey.start()
        self.loader = threading.Thread(target=stt.load, daemon=True)  # warm up so first dictation is fast
        self.loader.start()
        self.paster = osio.Paster()  # created after Hotkey so we don't listen to ourselves
        # plays recordings back in the History window; not to be transcribed off the speakers
        self.player = osio.Player(lambda playing: self.session and self.session.mute("them", playing))
        self.prune_audio()
        GLib.timeout_add_seconds(600, self.prune_audio)  # and every 10 minutes
        w.show_all()

    # --- icon ---
    def set_state(self, s):
        self.state = s
        if s != "idle" and not self.anim:
            self.anim = GLib.timeout_add(16, lambda: self.win.queue_draw() or self.state != "idle")
        if s == "idle":
            self.anim = None
        self.win.queue_draw()
        self.tray.update()

    def hover(self, on):
        self.hovered = on
        self.win.queue_draw()

    def render_icon(self, px):
        """The icon in its current state as a px-by-px image (for the system tray)."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        cr = cairo.Context(surface)
        cr.scale(px / SIZE, px / SIZE)
        self.draw(None, cr)
        return surface

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

        if self.session:  # transcribe mode: a ring around the icon, grey while paused
            cr.arc(c, c, R + 2.5, 0, 2 * math.pi)
            cr.set_source_rgba(*((0.55, 0.57, 0.62) if self.session.paused else ACCENT), 0.95)
            cr.set_line_width(2.2)
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
        """Refresh the two "default style" radio lists (here, and on the other computer).
        Called whenever the menu opens, as styles may have changed."""
        data = refine.load_styles()
        names = [s["name"] for s in data["styles"]]
        here = refine.default_style()
        self.fill_style_menu(self.default_menu, [(None, "None (cleanup only)")] + [(n, n) for n in names],
                             here and here["name"], refine.set_default)
        remote = data.get("remote_default", SAME)
        self.fill_style_menu(self.remote_style_menu,
                             [(SAME, "Same as here"), (None, "None (cleanup only)")] + [(n, n) for n in names],
                             remote if remote in [SAME, None, *names] else None,
                             lambda v: refine.set_remote_default(v, same=v is SAME))

    def fill_style_menu(self, menu, choices, current, pick):
        """A radio list of (value, label) choices with current ticked; pick(value) saves a choice.
        Rebuilt only if the choices changed, otherwise just re-ticked, so the tray's item ids stay valid.
        While building, GTK ticks items itself (e.g. when the ticked one is removed); those aren't choices."""
        self.ticking = True
        if choices != getattr(menu, "choices", None):
            for item in menu.get_children():
                menu.remove(item)
            menu.choices, menu.items, group = choices, {}, None
            for value, label in choices:
                item = menu.items[value] = Gtk.RadioMenuItem(label=label, group=group)
                group = group or item
                item.connect("toggled", lambda i, v=value: i.get_active() and not self.ticking and pick(v))
                menu.append(item)
            menu.show_all()
        menu.items[current].set_active(True)
        self.ticking = False

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
            away = remote.on_remote_screen()
            if away and self.cfg["remote_mode"] == "ignore":
                return  # e.g. the other computer runs its own Dictate
            pressed = self.hotkey.chord.pressed_at
            # where the text will go: the other computer (typed through Synergy), or the focused app here,
            # captured now, before any of our windows take focus
            self.app = OTHER_COMPUTER if away else activewin.snapshot()
            AUDIO.mkdir(parents=True, exist_ok=True)
            self.wav = str(AUDIO / f"{datetime.now():%Y%m%d-%H%M%S-%f}.wav")
            self.rec = osio.Recorder()
            self.rec.start(self.wav)
            self.live = stt.Live(self.wav)  # transcribes each stretch of speech as soon as you pause
            if self.session:
                self.session.mute("me", True)  # a dictation isn't part of the conversation
            self.set_state("rec")
            log(f"recording: {(time.time() - pressed) * 1000:.0f} ms after the key was pressed" if pressed else "recording")
        if down and (self.cfg["refine"] or alt):
            refine.warm()  # load the model while the user is still speaking
        elif not down and self.rec:
            if self.session:
                self.session.mute("me", False)
            rec, self.rec = self.rec, None
            self.set_state("busy")
            refining = self.cfg["refine"] or alt  # Alt asks for a style, which always includes cleanup
            threading.Thread(target=self.process, args=(rec, self.live, self.wav, refining, alt, letter, self.app),
                             daemon=True).start()

    def process(self, rec, live, wav, refining, alt, letter, app):
        """Stop recording → transcribe → cleanup → a style: Alt+letter's, or (Alt alone / unknown letter)
        ask which, or (no Alt) the style matching the focused app, else the default style."""
        raw = text = style = ""
        ctx = activewin.describe(app)
        try:
            rec.stop()  # here, not on the GTK thread: pw-record takes ~0.35 s to finish the file
            try:
                raw = text = live.finish()  # most of it was transcribed while you were speaking
            except Exception as err:
                log(f"live transcription failed ({err}), transcribing the whole recording")
                raw = text = stt.transcribe(wav)
            if refining and raw:
                text = refine.cleanup(raw, ctx)
            if alt and raw:
                style = letter and refine.style_for_key(letter)
                if not style:
                    return GLib.idle_add(self.pick_style, text, raw, app, wav)
            elif refining and raw and app.get("remote"):  # we can't see its apps: its own default style
                style = refine.default_style(remote=True)
            elif refining and raw:
                style = refine.style_for_app(f"{app['cls']} {app['title']}") or refine.default_style()
            if style:
                text = refine.apply(text, style, ctx)
        except Exception as err:  # never leave the icon stuck on "busy"
            print("transcription failed:", err)
        finally:
            if refining:
                refine.release()
        GLib.idle_add(lambda: self.paste(text, raw, app, style and style["name"], audio=wav, cleanup=refining))

    def paste(self, text, raw, app, style=None, paste=True, delay=150, audio=None, cleanup=False):
        """Save to history (with the recording and what was applied), then paste or type the text."""
        if audio and self.hotkey.chord.may_go_again():  # this hold may be the start of Ctrl+Win, Win again
            GLib.timeout_add(50, lambda: self.paste(text, raw, app, style, paste, delay, audio, cleanup) and False)
            return
        self.set_state("idle")
        if audio and audio == self.cancelled:  # it was: not a dictation
            Path(audio).unlink(missing_ok=True)
            return
        if not text:  # nothing heard: no history entry, so don't keep the recording either
            if audio:
                Path(audio).unlink(missing_ok=True)
            return
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "text": text,
                 "app": "other computer" if app.get("remote") else app["cls"], "cleanup": cleanup}
        if app.get("title"):
            entry["title"] = app["title"]  # what per-app styles matched against
        if raw != text:
            entry["raw"] = raw
        if style:
            entry["style"] = style
        if audio and self.cfg["keep_audio_hours"] == 0:  # recordings aren't being kept
            Path(audio).unlink(missing_ok=True)
        elif audio:
            entry["audio"] = Path(audio).name
        with HISTORY.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self.copy(text)
        if paste and app.get("remote") and remote.on_remote_screen():
            # the other computer has no access to our clipboard paste, so type it; Synergy forwards the keys
            threading.Thread(target=self.paster.type_text, args=(text,), daemon=True).start()
        elif paste:  # wait for the clipboard to reach Wayland (and, after the picker, for focus to return)
            terminal = osio.LINUX and any(t in app["cls"].lower() for t in TERMINALS)
            GLib.timeout_add(delay, self.paster.paste, terminal)

    def prune_audio(self):
        """Delete recordings older than the "keep recordings" setting (history entries stay)."""
        hours = self.cfg["keep_audio_hours"]
        if hours is not None:
            cutoff = time.time() - hours * 3600
            recording = {Path(self.wav or ""), *map(Path, self.session.recordings if self.session else [])}
            for wav in [*AUDIO.glob("*.wav"), *transcript.FOLDER.glob("*.ogg"), *transcript.FOLDER.glob("*.wav")]:
                if wav.stat().st_mtime < cutoff and wav not in recording:  # never one being recorded
                    wav.unlink(missing_ok=True)
        return True  # keep the 10-minute timer going

    def set_keep_audio(self, hours):
        self.save_state(keep_audio_hours=hours)
        self.prune_audio()

    def copy(self, text):
        self.clip.set_text(text, -1)
        self.clip.store()

    # --- transcribe mode ---
    def on_again(self):
        """Ctrl+Win, lift Win, Win again: start or stop transcribing. The first hold of the gesture was
        reported as a (very short) dictation; drop it."""
        self.cancelled = self.wav
        if not osio.HEARS_SPEAKERS:
            return log("transcribe mode: not available on this computer yet")
        self.toggle_transcribing()

    def toggle_transcribing(self):
        if self.session:
            self.stop_transcribing()
        else:
            self.start_transcribing()

    def start_transcribing(self):
        try:
            session = transcript.Session()
        except OSError as err:  # e.g. pw-record missing
            return log(f"transcribe mode: can't record ({err})")
        self.session, win = session, dialogs.TranscriptWindow(session, self.stop_transcribing)
        self.transcript_win = win
        session.on_change = lambda: (win.refresh(), self.win.queue_draw(), self.tray.update())
        self.transcribe_item.set_label("Stop transcribing")
        session.on_change()
        log(f"transcribing: {session.path.name}")

    def stop_transcribing(self):
        session, win, self.session = self.session, self.transcript_win, None
        if not session:
            return

        def saved():
            win.stopped()
            if self.cfg["keep_audio_hours"] == 0:
                for path in session.recordings:
                    Path(path).unlink(missing_ok=True)
            log(f"transcribing: stopped, {len(session.paragraphs())} paragraphs saved to {session.path.name}")
        session.stop(saved)
        self.transcribe_item.set_label(self.TRANSCRIBE)
        self.win.queue_draw()
        self.tray.update()

    def open_folder(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(folder.as_uri(), None)

    # --- windows ---
    def show_history(self):
        dialogs.history(self, HISTORY, AUDIO)

    def pick_style(self, text, raw, app, audio):
        def chosen(style, paste):
            if not style:
                return self.paste(text, raw, app, paste=paste, delay=400, audio=audio, cleanup=True)
            self.set_state("busy")
            def restyle():
                styled = refine.apply(text, style, activewin.describe(app))
                GLib.idle_add(lambda: self.paste(styled, raw, app, style["name"], True, 400, audio=audio, cleanup=True))
            threading.Thread(target=restyle, daemon=True).start()
        dialogs.StylePicker(text, chosen)

    def quit(self, reason):
        """Every way out goes through here, so the log says why Dictate stopped."""
        log(f"quitting: {reason}")
        if self.session:  # save what's still to be transcribed
            session, self.session = self.session, None
            return session.stop(Gtk.main_quit)
        Gtk.main_quit()

    def run(self):
        log(f"started (pid {os.getpid()})")
        Gtk.main()
        self.loader.join()  # exiting while the speech model is still loading crashes inside onnxruntime
        log("exited")


def only_instance():
    """Claim a fixed local port: only one process can hold it, and the OS frees it even after a crash.
    Two copies would both hear the hotkey and paste everything twice."""
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 47613))
    except OSError:
        sys.exit("Dictate is already running.")
    return lock

