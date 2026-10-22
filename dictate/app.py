"""The capsule (capsule.py: drag to move, right-click for the menu, click while transcribing to see the
transcript), the Dictate window (hub.py), and the dictation pipeline: record → transcribe → cleanup → refinement →
paste or type. Started by dictate.py, after dictate.bootstrap(). Ctrl+Win, lift Win, Win again starts or stops
transcribe mode (transcript.py). So it isn't left running by mistake, closing the Dictate window while it is (the
first time each day), or nothing being heard for QUIET seconds, brings up a reminder beside the capsule (a desktop
notification if the capsule isn't on screen). How it all looks: docs/design/DESIGN.md.
"""
import json, math, os, signal, socket, sys, threading, time
from datetime import datetime
from pathlib import Path
import cairo, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from . import DATA, activewin, capsule, design, huds, hub, osio, refine, remote, stt, transcript, tray

DICTATIONS = DATA / "dictations.jsonl"  # every dictation, a JSON line each
AUDIO = DATA / "audio"  # each dictation's recording, kept for playback for "keep_audio_hours" (calls': "keep_call_hours")
KEEP_AUDIO = ((0, "Don't keep"), (1, "1 hour"), (3, "3 hours"), (12, "12 hours"), (24, "1 day"), (72, "3 days"),
              (168, "1 week"), (None, "Forever"))  # hours, for dictations' and calls' recordings; None = never delete
STATE = DATA / "state.json"
REMOTE_MODES = (("type", "Type the text there"), ("ignore", "Ignore the hotkey"))
SAME = "same"  # remote default refinement: same as here
QUIET = 600  # seconds with nothing added to a transcript before reminding that it's still being recorded
QUIET_CHECK = 30  # seconds between checks (and updates of the tray icon's tooltip)
OTHER_COMPUTER = {"cls": "", "title": "", "remote": True}  # where text goes when Synergy has the keyboard
TERMINALS = ("konsole", "terminal", "kitty", "alacritty", "wezterm", "foot", "ghostty", "yakuake")  # Linux paste

def log(msg):
    """Timestamped, flushed at once (stdout is buffered when launched from the desktop): see journalctl."""
    print(f"{datetime.now():%H:%M:%S.%f}"[:-3], msg, flush=True)


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


class App:
    KEEP_AUDIO, DICTATIONS, AUDIO, REMOTE_MODES, SAME = KEEP_AUDIO, DICTATIONS, AUDIO, REMOTE_MODES, SAME
    TRANSCRIBE = "Transcribe this computer"

    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        design.install()

        self.capsule = capsule.Capsule()
        w = self.win = self.capsule.win
        self.cfg = {"pos": [100, 100], "refine": True, "remote_mode": "type", "keep_audio_hours": 24, "keep_call_hours": 168,
                    **load_json(STATE, {})}
        w.move(*self.cfg["pos"])
        self.capsule.anchor = self.cfg.get("anchor", "left")
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                     | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        w.connect("button-press-event", self.on_click)
        w.connect("motion-notify-event", self.on_motion)
        w.connect("button-release-event", self.on_release)
        self.pressed = None  # where the left button went down, until it's a drag or a click
        w.connect("configure-event", self.on_moved)
        w.connect("enter-notify-event", lambda *_: self.hover(True))
        w.connect("leave-notify-event", lambda *_: self.hover(False))
        w.connect("destroy", lambda _: self.quit("the icon's window was destroyed"))
        if not osio.WINDOWS:  # quit cleanly so exit hooks (e.g. unloading the KWin script) run
            for sig in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda sig=sig: self.quit(f"got {sig.name}"))

        self.menu = Gtk.Menu()
        home = Gtk.MenuItem(label="Open Dictate")
        home.connect("activate", lambda _: self.open_hub("dictations"))
        self.menu.append(home)
        self.menu.append(Gtk.SeparatorMenuItem())
        self.refine_item = Gtk.CheckMenuItem(label="Refine text", active=self.cfg["refine"])
        self.refine_item.connect("toggled", lambda t: self.save_state(refine=t.get_active()))
        self.menu.append(self.refine_item)
        default = Gtk.MenuItem(label="Default refinement")
        self.default_menu = Gtk.Menu()
        default.set_submenu(self.default_menu)
        self.menu.append(default)
        for label, cb in (("Dictations", self.show_dictations), ("Refinements…", lambda: self.open_hub("refinements")),
                          ("Settings…", lambda: self.open_hub("settings")), (None, None)):
            item = Gtk.MenuItem(label=label) if label else Gtk.SeparatorMenuItem()
            if cb:
                item.connect("activate", lambda _, cb=cb: cb())
            self.menu.append(item)
        if osio.HEARS_SPEAKERS:
            self.transcribe_item = Gtk.MenuItem(label=self.TRANSCRIBE)
            self.transcribe_item.connect("activate", lambda _: self.toggle_transcribing())
            browse = Gtk.MenuItem(label="Transcripts")
            browse.connect("activate", lambda _: self.show_transcripts())
            for item in (self.transcribe_item, browse, Gtk.SeparatorMenuItem()):
                self.menu.append(item)
        away = Gtk.MenuItem(label="When another computer has the keyboard")  # e.g. through Synergy
        away_menu, group, self.remote_items = Gtk.Menu(), None, []
        for mode, label in REMOTE_MODES:
            item = Gtk.RadioMenuItem(label=label, group=group, active=mode == self.cfg["remote_mode"])
            group = group or item
            self.remote_items.append(item)
            away_menu.append(item)
        for item, (mode, _) in zip(away_menu.get_children(), REMOTE_MODES):  # connected after ticking,
            item.connect("toggled", lambda i, m=mode: i.get_active() and self.save_state(remote_mode=m))  # so setup isn't saved
        away_menu.append(Gtk.SeparatorMenuItem())
        remote_refinement = Gtk.MenuItem(label="Default refinement there")  # per-app refinements can't apply: we can't see its apps
        self.remote_refinement_menu = Gtk.Menu()
        remote_refinement.set_submenu(self.remote_refinement_menu)
        away_menu.append(remote_refinement)
        away.set_submenu(away_menu)
        self.menu.append(away)
        self.startup_item = Gtk.CheckMenuItem(label="Run at startup", active=osio.autostart_enabled())
        self.startup_item.connect("toggled", lambda t: osio.set_autostart(t.get_active()))
        self.menu.append(self.startup_item)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: self.quit("Quit chosen from the menu"))
        self.menu.append(quit_item)
        self.menu.show_all()
        self.build_default_menu()

        self.state, self.rec, self.wav, self.save_id, self.since = "idle", None, None, None, None
        self.session = self.cancelled = None  # transcribe mode; a dictation to drop
        self.hub = None  # the Dictate window, while open
        self.reminder = None  # the reminder that a transcript is still being recorded, while it's shown
        self.reminded_quiet = False  # about this stretch of quiet already
        self.tray = tray.Tray(self.menu, self.render_icon, self.build_default_menu, self.status)  # same menu in the tray
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.app = activewin.snapshot()
        # the menu is an XWayland popup: a click on a Wayland app never reaches it, so it can't tell it
        # should close. KWin tells us when another app gets focus instead.
        activewin.on_switch.append(lambda: self.menu.get_visible() and self.menu.popdown())
        activewin.start()
        remote.start()
        self.hotkey = osio.Hotkey(self.on_hotkey, self.on_again, self.on_other_shortcut,
                                  lambda: {s["key"] for s in refine.load_refinements()["refinements"]})
        self.hotkey.start()
        self.loader = threading.Thread(target=stt.load, daemon=True)  # warm up so first dictation is fast
        self.loader.start()
        self.paster = osio.Paster()  # created after Hotkey so we don't listen to ourselves
        # plays recordings back in Dictations; not to be transcribed off the speakers
        self.player = osio.Player(lambda playing: self.session and self.session.mute("them", playing))
        self.prune_audio()
        GLib.timeout_add_seconds(600, self.prune_audio)  # and every 10 minutes
        w.show_all()

    # --- the capsule ---
    def set_state(self, s):
        self.state = s
        self.show_state()

    def show_state(self):
        """Tell the capsule and the tray what's happening."""
        level = lambda: capsule.wav_level(self.wav) if self.wav and self.rec else 0.0
        self.capsule.update(self.state, self.session, self.since, level)
        self.tray.update()

    def status(self):
        """What Dictate's doing, for the tray icon's tooltip: while transcribing, for how long, and the topic."""
        session = self.session
        if not session:
            return "Hold Ctrl+Win to dictate"
        text = f"{'Transcribing, paused' if session.paused else 'Transcribing'} · {transcript.length(session.now())}"
        found = session.topics
        if found.now is not None and found.now < len(found.topics):
            text += f"\nNow: {found.topics[found.now]['title']}"
        return text

    def hover(self, on):
        self.capsule.hover(on)

    def render_icon(self, px):
        """The tray icon in the current state, px by px."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        capsule.draw_tray(cairo.Context(surface), px, self.state, self.session)
        return surface

    # --- move / menu ---
    def on_click(self, w, ev):
        """Left: drag to move, or (while transcribing) click to see the recording. Right: the menu."""
        if ev.button == 1:
            self.pressed = (ev.x_root, ev.y_root)
        elif ev.button == 3:
            self.build_default_menu()
            self.menu.popup_at_pointer(ev)
        return True

    def on_motion(self, w, ev):
        if self.pressed and max(abs(ev.x_root - self.pressed[0]), abs(ev.y_root - self.pressed[1])) > 3:
            x, y = self.pressed
            self.pressed = None
            w.begin_move_drag(1, int(x), int(y), ev.time)
        return True

    def on_release(self, w, ev):
        if ev.button == 1 and self.pressed:  # didn't move: a click
            self.pressed = None
            if self.session:
                self.show_transcripts(recording=True)
        return True

    def build_default_menu(self):
        """Refresh the two "default refinement" radio lists (here, and on the other computer), and the settings'
        ticks (they can change in Settings too). Called whenever the menu opens, as refinements may have changed."""
        for item, on in ((self.refine_item, self.cfg["refine"]), (self.startup_item, osio.autostart_enabled()),
                         *((i, m == self.cfg["remote_mode"]) for i, (m, _) in zip(self.remote_items, REMOTE_MODES))):
            if item.get_active() != on:
                item.set_active(on)
        data = refine.load_refinements()
        names = [s["name"] for s in data["refinements"]]
        here = refine.default_refinement()
        self.fill_refinement_menu(self.default_menu, [(None, "None (cleanup only)")] + [(n, n) for n in names],
                             here and here["name"], refine.set_default)
        remote = data.get("remote_default", SAME)
        self.fill_refinement_menu(self.remote_refinement_menu,
                             [(SAME, "Same as here"), (None, "None (cleanup only)")] + [(n, n) for n in names],
                             remote if remote in [SAME, None, *names] else None,
                             lambda v: refine.set_remote_default(v, same=v is SAME))

    def fill_refinement_menu(self, menu, choices, current, pick):
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
        self.save_id = GLib.timeout_add(500, self.moved)

    def moved(self):
        """Settled after a move: the capsule grows away from the nearer edge; remember where it is."""
        self.capsule.settle()
        self.save_state(pos=list(self.win.get_position()), anchor=self.capsule.anchor)
        return False

    def save_state(self, **changes):
        self.cfg.update(changes)
        STATE.write_text(json.dumps(self.cfg))
        self.save_id = None

    def set_refine(self, on):
        self.save_state(refine=on)
        self.refine_item.set_active(on)

    def autostart(self):
        return osio.autostart_enabled()

    def set_autostart(self, on):
        if self.startup_item.get_active() != on:
            self.startup_item.set_active(on)  # (which sets it)

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
            self.since = time.time()
            self.set_state("rec")
            log(f"recording: {(time.time() - pressed) * 1000:.0f} ms after the key was pressed" if pressed else "recording")
        if down and (self.cfg["refine"] or alt):
            refine.warm()  # load the model while the user is still speaking
        elif not down and self.rec:
            if self.session:
                self.session.mute("me", False)
            rec, self.rec = self.rec, None
            self.set_state("busy")
            refining = self.cfg["refine"] or alt  # Alt asks for a refinement, which always includes cleanup
            threading.Thread(target=self.process, args=(rec, self.live, self.wav, refining, alt, letter, self.app),
                             daemon=True).start()

    def on_other_shortcut(self):
        """Another key pressed with Ctrl+Win (e.g. Ctrl+Win+→ switching desktops): another app's shortcut,
        not a dictation. Drop the recording, so nothing said meanwhile is pasted."""
        if not self.rec:
            return
        if self.session:
            self.session.mute("me", False)
        rec, live, wav, self.rec = self.rec, self.live, self.wav, None
        refine.release()
        self.set_state("idle")
        log("recording dropped: Ctrl+Win was part of another shortcut")

        def drop():
            rec.stop()
            try:
                live.finish()
            except Exception:
                pass
            Path(wav).unlink(missing_ok=True)
        threading.Thread(target=drop, daemon=True).start()

    def process(self, rec, live, wav, refining, alt, letter, app):
        """Stop recording → transcribe → cleanup → a refinement: Alt+letter's, or (Alt alone, or a refinement's letter
        since deleted) ask which, or (no Alt) the refinement matching the focused app, else the default refinement."""
        raw = text = cleaned = refinement = ""
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
            cleaned = text
            if alt and raw:
                refinement = letter and refine.refinement_for_key(letter)
                if not refinement:
                    return GLib.idle_add(self.pick_refinement, text, raw, app, wav)
            elif refining and raw and app.get("remote"):  # we can't see its apps: its own default refinement
                refinement = refine.default_refinement(remote=True)
            elif refining and raw:
                refinement = refine.refinement_for_app(f"{app['cls']} {app['title']}") or refine.default_refinement()
            if refinement:
                text = refine.apply(text, refinement, ctx)
        except Exception as err:  # never leave the icon stuck on "busy"
            print("transcription failed:", err)
        finally:
            if refining:
                refine.release()
        GLib.idle_add(lambda: self.paste(text, raw, app, refinement and refinement["name"], audio=wav, cleanup=refining,
                                         cleaned=cleaned))

    def paste(self, text, raw, app, refinement=None, paste=True, delay=150, audio=None, cleanup=False, cleaned=None):
        """Keep it in Dictations (with the recording, and each step: what was heard, cleaned up, refined), then
        paste or type the text. cleaned: the text after cleanup, before the refinement."""
        if audio and self.hotkey.chord.may_go_again():  # this hold may be the start of Ctrl+Win, Win again
            GLib.timeout_add(50, lambda: self.paste(text, raw, app, refinement, paste, delay, audio, cleanup, cleaned) and False)
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
            entry["title"] = app["title"]  # what per-app refinements matched against
        if raw != text:
            entry["raw"] = raw
        if refinement:
            entry["refinement"] = refinement
            entry["cleaned"] = cleaned  # (so what the refinement changed can be seen, apart from cleanup)
        if audio and self.cfg["keep_audio_hours"] == 0:  # recordings aren't being kept
            Path(audio).unlink(missing_ok=True)
        elif audio:
            entry["audio"] = Path(audio).name
        with DICTATIONS.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self.copy(text)
        if paste and app.get("remote") and remote.on_remote_screen():
            # the other computer has no access to our clipboard paste, so type it; Synergy forwards the keys
            threading.Thread(target=self.paster.type_text, args=(text,), daemon=True).start()
        elif paste:  # wait for the clipboard to reach Wayland (and, after the picker, for focus to return)
            terminal = osio.LINUX and any(t in app["cls"].lower() for t in TERMINALS)
            GLib.timeout_add(delay, self.paster.paste, terminal)

    def prune_audio(self):
        """Delete recordings older than their setting: dictations' (keep_audio_hours) and calls' (keep_call_hours).
        Their text stays, in Dictations and Transcripts."""
        recording = {Path(self.wav or ""), *map(Path, self.session.recordings if self.session else [])}
        for hours, files in ((self.cfg["keep_audio_hours"], AUDIO.glob("*.wav")),
                             (self.cfg["keep_call_hours"], [*transcript.FOLDER.glob("*.ogg"), *transcript.FOLDER.glob("*.wav")])):
            if hours is None:
                continue
            cutoff = time.time() - hours * 3600
            for wav in files:
                if wav.stat().st_mtime < cutoff and wav not in recording:  # never one being recorded
                    wav.unlink(missing_ok=True)
        return True  # keep the 10-minute timer going

    def set_keep_calls(self, hours):
        self.save_state(keep_call_hours=hours)
        self.prune_audio()
        self.transcripts_changed()  # (Play, for those whose recordings just went)

    def set_keep_audio(self, hours):
        self.save_state(keep_audio_hours=hours)
        self.prune_audio()
        if self.hub and not self.hub.closed and "dictations" in self.hub.pages:
            self.hub.pages["dictations"].recordings_changed()  # recordings may just have gone: no Play for them

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
        self.session, self.reminded_quiet = session, False
        session.on_change = lambda: (self.transcripts_changed(), self.show_state())
        GLib.timeout_add(int(QUIET_CHECK * 1000), self.check_quiet, session)
        self.transcribe_item.set_label("Stop transcribing")
        self.show_transcripts(focus=False)  # started from the keyboard, mid-conversation: leave focus where it is
        session.on_change()
        log(f"transcribing: {session.path.name}")

    def stop_transcribing(self):
        session, self.session = self.session, None
        if not session:
            return
        if self.reminder:
            self.reminder.close()

        def saved():
            if self.cfg["keep_call_hours"] == 0:
                for path in session.recordings:
                    Path(path).unlink(missing_ok=True)
            self.transcripts_changed()
            log(f"transcribing: stopped, {len(session.paragraphs())} paragraphs saved to {session.path.name}")
        session.stop(saved)
        self.transcribe_item.set_label(self.TRANSCRIBE)
        self.transcripts_changed()
        self.show_state()

    def open_hub(self, page, focus=True, **kw):
        """Open the Dictate window on page (or bring it forward), passing kw to the page."""
        if not (self.hub and not self.hub.closed):
            self.hub = hub.Hub(self)
            self.hub.win.connect("delete-event", lambda *_: self.transcripts_closed())
        return self.hub.show(page, focus, **kw)

    def show_transcripts(self, focus=True, recording=False):
        """Open Transcripts; with recording, showing the one being recorded."""
        self.open_hub("transcripts", focus, recording=recording)

    def transcripts_closed(self):
        """The Dictate window was closed: if a transcript's being recorded, say it still is, once a day."""
        today = datetime.now().date().isoformat()
        if self.session and self.cfg.get("reminded_closed") != today:
            self.save_state(reminded_closed=today)
            GLib.idle_add(lambda: self.remind("closed") and False)

    def check_quiet(self, session):
        """While transcribing: if nothing's been added for QUIET seconds, say it's still going (once until
        something is heard again)."""
        if session is not self.session:
            return False
        self.tray.update()  # how long it's been going, in its tooltip
        quiet = session.quiet_for() >= QUIET
        if quiet and not self.reminded_quiet:
            self.remind("quiet")
        self.reminded_quiet = quiet
        return True

    def remind(self, why):
        """Say a transcript is still being recorded, and how to stop it: beside the icon, or, if the icon isn't on
        screen, as a desktop notification."""
        if not self.session:
            return
        if self.reminder and self.reminder.open:
            self.reminder.close()
        minutes = round(QUIET / 60)
        log(f"reminding that it's still transcribing ({why})")
        if self.icon_on_screen():
            self.reminder = huds.StillTranscribing(why, minutes, self.capsule.picture(), self.capsule.rect(),
                                                   self.stop_transcribing)
        else:
            heading, body = huds.reminder_text(why, minutes)
            image = Path(GLib.get_user_cache_dir()) / "dictate" / "transcribing.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            self.render_icon(128).write_to_png(str(image))
            ways = "".join(f"\n• {w}" for w in huds.STOP_WAYS)
            osio.notify(f"⚠ {heading}", f"{body}\n\nA capsule with a red dot and a timer means it's transcribing. "
                                        f"To stop it:{ways}", [("stop", "Stop now"), ("show", "Show transcript")],
                        lambda key: self.stop_transcribing() if key == "stop" else self.show_transcripts(recording=True),
                        image)

    def icon_on_screen(self):
        """Whether the capsule is shown, on one of the screens."""
        if not self.win.get_mapped():
            return False
        x, y, w, h = self.capsule.dot_rect()
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            area = display.get_monitor(i).get_geometry()
            if area.x <= x + w // 2 < area.x + area.width and area.y <= y + h // 2 < area.y + area.height:
                return True
        return False

    def transcripts_changed(self):
        if self.hub and not self.hub.closed and "transcripts" in self.hub.pages:
            self.hub.pages["transcripts"].changed()

    # --- windows ---
    def show_dictations(self):
        self.open_hub("dictations")

    def pick_refinement(self, text, raw, app, audio):
        def chosen(refinement, paste):
            if not refinement:
                return self.paste(text, raw, app, paste=paste, delay=400, audio=audio, cleanup=True)
            self.set_state("busy")
            def run():
                refined = refine.apply(text, refinement, activewin.describe(app))
                GLib.idle_add(lambda: self.paste(refined, raw, app, refinement["name"], True, 400, audio=audio, cleanup=True,
                                                 cleaned=text))
            threading.Thread(target=run, daemon=True).start()
        huds.RefinementPicker(text, chosen, on_new=lambda: self.open_hub("refinements", new=True))

    def quit(self, reason):
        """Every way out goes through here, so the log says why Dictate stopped."""
        log(f"quitting: {reason}")
        if self.rec:  # mid-dictation: don't leave the microphone recording
            self.rec.stop()
            self.rec = None
        if self.session:  # save what's still to be transcribed
            session, self.session = self.session, None
            return session.stop(Gtk.main_quit, last_topics=False)
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

