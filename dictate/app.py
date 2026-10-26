"""The app: the capsule (capsule.py) and its menu (menu.py), the Dictate window (hub.py), the dictation
pipeline (record → transcribe → cleanup → refinement → paste or type) and transcribe mode (transcript.py).

Started by dictate.py, after dictate.bootstrap(). Hold Ctrl+Win to dictate; Ctrl+Win, lift Win, Win again starts
or stops transcribe mode. So a call isn't left being transcribed by mistake, closing the Dictate window while it
is (the first time each day) brings up a reminder beside the capsule, and nothing being added to it for QUIET
seconds pauses it and says so (desktop notifications if the capsule isn't on screen). How it all looks:
docs/design/DESIGN.md."""

import logging
import os
import signal
import socket
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import (  # noqa: E402
    DATA,
    activewin,
    capsule,
    design,
    history,
    hub,
    huds,
    llm,
    osio,
    playback,
    refine,
    refinements,
    remote,
    store,
    stt,
    transcript,
    tray,
    waiting,
)
from .history import Dictation  # noqa: E402
from .menu import Menu  # noqa: E402
from .settings import Settings  # noqa: E402

log = logging.getLogger(__name__)

QUIET = 300  # seconds with nothing added to a transcript before it's paused
FLASH = 3.0  # seconds the icons flash for after a sound while a transcript is paused for being quiet
QUIET_CHECK = 30  # seconds between checks (and updates of the tray icon's tooltip)
PRUNE_EVERY = 600  # seconds between deletions of recordings older than their setting
TERMINALS = ("konsole", "terminal", "kitty", "alacritty", "wezterm", "foot", "ghostty", "yakuake")  # Linux paste
LOCK_PORT = 47613  # held by the running Dictate (only_instance)


class App:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        design.install()
        self.settings = Settings()
        self.mic = None  # the microphone recorded last (its name), to log when it changes
        self.state = "idle"  # what the capsule shows: "idle", "rec" (dictating) or "busy" (the model's working)
        self.rec = self.live = self.wav = None  # the dictation being recorded: its recorder, transcriber and file
        self.since = None  # when it started
        self.cancelled = None  # the recording of a dictation to drop (it was the start of Ctrl+Win, Win again)
        self.session = None  # the call being transcribed
        self.hub = None  # the Dictate window, while open
        self.reminder = None  # the reminder that a transcript is still being recorded, while it's shown
        self.flash_until = 0.0  # while the icons flash: until when

        self.capsule = capsule.Capsule()
        self.capsule.place(self.settings["pos"], self.settings["anchor"])
        self.capsule.interact(on_click=self.capsule_clicked, on_menu=lambda event: self.menu.popup(event),
                              on_settled=self.capsule_moved)
        self.capsule.win.connect("destroy", lambda _: self.quit("the icon's window was destroyed"))
        if not osio.WINDOWS:  # quit cleanly so exit hooks (e.g. unloading the KWin script) run
            for sig in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda sig=sig: self.quit(f"got {sig.name}"))
        self.menu = Menu(self)
        self.waiting = waiting.Waiting(self.waiting_changed)  # stopped calls' final passes, waiting for the GPU
        self.waiting_hud = None  # what's waiting, and Use the CPU, while it's shown
        self.tray = tray.Tray(self.menu.widget, self.render_icon, self.menu.refresh, self.status)  # the same menu
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        # the menu is an XWayland popup: a click on a Wayland app never reaches it, so it can't tell it
        # should close. KWin tells us when another app gets focus instead.
        activewin.on_switch.append(self.menu.close)
        activewin.start()
        remote.start()
        self.hotkey = osio.Hotkey(self.on_hotkey, self.on_again, self.on_other_shortcut, refinements.letters)
        self.hotkey.start()
        self.loader = threading.Thread(target=stt.load, daemon=True)  # warm up so first dictation is fast
        self.loader.start()
        self.paster = osio.Paster()  # created after Hotkey so we don't listen to ourselves
        # plays recordings back in Dictations; not to be transcribed off the speakers
        self.player = osio.Player(lambda playing: self.session and self.session.mute("them", playing))
        self.playback = playback.Playback(self.player)  # what's playing: everything plays and stops through it
        self.prune_audio()
        GLib.timeout_add_seconds(PRUNE_EVERY, self.prune_audio)
        self.capsule.win.show_all()

    # --- the capsule and the tray icon ---
    def set_state(self, state):
        self.state = state
        self.show_state()

    def show_state(self):
        """Tell the capsule and the tray what's happening."""
        if self.capsule.waiting != bool(self.waiting.jobs):
            self.capsule.waiting = bool(self.waiting.jobs)
            self.capsule.win.queue_draw()
        level = lambda: capsule.wav_level(self.wav) if self.wav and self.rec else 0.0
        self.capsule.update(self.state, self.session, self.since, level)
        self.tray.update()

    def status(self):
        """What Dictate's doing, for the tray icon's tooltip: while transcribing, for how long, and the topic."""
        session, n = self.session, len(self.waiting.jobs)
        if not session and n:
            return f"Waiting for the graphics card to summarise {n} call{'s' if n > 1 else ''}"
        if not session:
            return "Hold Ctrl+Win to dictate"
        text = f"{'Transcribing, paused' if session.paused else 'Transcribing'} · {transcript.length(session.now())}"
        topic = session.topics.current()
        return f"{text}\nNow: {topic}" if topic else text

    def render_icon(self, px):
        """The tray icon in the current state, px by px."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        capsule.draw_tray(cairo.Context(surface), px, self.state, self.session, self.capsule.flashing,
                          bool(self.waiting.jobs))
        return surface

    def capsule_clicked(self):
        """While transcribing, a click shows the transcript; while it's paused for being quiet, the alert."""
        if self.paused_alert():
            self.draw_attention(focus=True)
        elif self.session:
            self.show_transcripts(recording=True)
        elif self.waiting.jobs:
            self.show_waiting()

    def show_waiting(self):
        """What's waiting for the graphics card, and how long it's been, with Use the CPU and Keep waiting."""
        if self.waiting_hud and self.waiting_hud.open:
            self.waiting_hud.close()
        calls = [(datetime.strptime(j.path.stem, transcript.STAMP), self.waiting.waited(j)) for j in self.waiting.jobs]
        self.waiting_hud = huds.WaitingForGpu(calls, self.capsule.rect(), self.waiting.use_cpu)

    def waiting_changed(self):
        """A final pass started waiting for the GPU, or stopped waiting."""
        if self.waiting_hud and self.waiting_hud.open and not self.waiting.jobs:
            self.waiting_hud.close()
        self.show_state()
        self.transcripts_changed()
        if self.hub and not self.hub.closed and "transcripts" in self.hub.pages:
            self.hub.pages["transcripts"].waiting_changed()

    def capsule_moved(self):
        self.settings.update(pos=self.capsule.position(), anchor=self.capsule.anchor)

    # --- settings (also changed from the Settings page) ---
    def set_refine(self, on):
        self.settings.update(refine=on)

    def autostart(self):
        return osio.autostart_enabled()

    def set_autostart(self, on):
        if osio.autostart_enabled() != on:
            osio.set_autostart(on)

    def set_keep_audio(self, hours):
        self.settings.update(keep_audio_hours=hours)
        self.prune_audio()
        if self.hub and not self.hub.closed and "dictations" in self.hub.pages:
            self.hub.pages["dictations"].recordings_changed()  # recordings may just have gone: no Play for them

    def set_keep_calls(self, hours):
        self.settings.update(keep_call_hours=hours)
        self.prune_audio()
        self.transcripts_changed()  # (Play, for those whose recordings just went)

    def microphone(self):
        """The name of the microphone to record: the first connected one in the order set on the Settings page
        (those seen for the first time are added to its end, the default one first), or None: the default."""
        connected, order = dict(osio.microphones()), self.settings["microphones"]
        new = [[name, label] for name, label in connected.items() if name not in {n for n, _ in order}]
        if new:
            self.settings.update(microphones=order + new)
        mic = next((name for name, _ in self.settings["microphones"] if name in connected), None)
        if mic != self.mic:
            log.info("microphone: %s", connected.get(mic, "the default"))
            self.mic = mic
        return mic

    def set_microphones(self, order):
        self.settings.update(microphones=order)

    def prune_audio(self):
        """Delete recordings older than their setting: dictations' (keep_audio_hours) and calls' (keep_call_hours).
        Their text stays, in Dictations and Transcripts. Never one being recorded."""
        recording = {Path(self.wav or ""), *map(Path, self.session.recordings if self.session else [])}
        store.prune(history.AUDIO.glob("*.wav"), self.settings["keep_audio_hours"], recording)
        calls = [*transcript.FOLDER.glob("*.ogg"), *transcript.FOLDER.glob("*.wav")]
        store.prune(calls, self.settings["keep_call_hours"], recording)
        transcript.forget_mixes()  # (the copies played back from, of those deleted)
        return True  # keep the timer going

    # --- dictating ---
    def on_hotkey(self, down, alt, letter):
        """Ctrl+Win pressed or let go (or Alt pressed mid-hold). alt: Alt was touched during the hold; letter:
        a refinement's letter pressed with it."""
        if down and not self.rec:
            if remote.on_remote_screen() and self.settings["remote_mode"] == "ignore":
                return  # e.g. the other computer runs its own Dictate
            if self.paused_alert():
                log.info("not dictating: the paused transcript needs resuming or stopping first")
                self.reminder.asked_to_dictate()
                self.draw_attention(focus=True)
                return
            self.start_recording()
        if down and (self.settings["refine"] or alt):
            llm.server.warm()  # load the model while the user is still speaking
        elif not down and self.rec:
            self.stop_recording(alt, letter)

    def start_recording(self):
        pressed = self.hotkey.chord.pressed_at
        history.AUDIO.mkdir(parents=True, exist_ok=True)
        self.wav = str(history.AUDIO / f"{datetime.now():%Y%m%d-%H%M%S-%f}.wav")
        self.rec = osio.Recorder()
        self.rec.start(self.wav, mic=self.microphone())
        self.live = stt.Live(self.wav)  # transcribes each stretch of speech as soon as you pause
        if self.session:
            self.session.mute("me", True)  # a dictation isn't part of the conversation
        self.since = time.time()
        self.set_state("rec")
        if pressed:
            log.info("recording: %.0f ms after the key was pressed", (time.time() - pressed) * 1000)
        else:
            log.info("recording")

    def stop_recording(self, alt, letter):
        if self.session:
            self.session.mute("me", False)
        rec, self.rec = self.rec, None
        # where the text will go, decided now you've stopped: the other computer if Synergy has the keyboard
        # (typed there; started here, its own Dictate never saw the press), else the focused app here (our own
        # windows are ignored, so this is still the app you're in)
        window = activewin.OTHER_COMPUTER if remote.on_remote_screen() else activewin.snapshot()
        self.set_state("busy")
        refining = self.settings["refine"] or alt  # Alt asks for a refinement, which always includes cleanup
        dictation = Dictation(window, self.wav, cleanup=refining)
        threading.Thread(target=self.process, args=(dictation, rec, self.live, alt, letter), daemon=True).start()

    def on_other_shortcut(self):
        """Another key pressed with Ctrl+Win (e.g. Ctrl+Win+→ switching desktops): another app's shortcut,
        not a dictation. Drop the recording, so nothing said meanwhile is pasted."""
        if not self.rec:
            return
        if self.session:
            self.session.mute("me", False)
        rec, live, wav, self.rec = self.rec, self.live, self.wav, None
        llm.server.release()
        self.set_state("idle")
        log.info("recording dropped: Ctrl+Win was part of another shortcut")

        def drop():
            rec.stop()
            try:
                live.finish()
            except Exception:  # (whatever it heard is being thrown away anyway)
                log.debug("dropped recording's transcription failed", exc_info=True)
            Path(wav).unlink(missing_ok=True)
        threading.Thread(target=drop, daemon=True).start()

    def process(self, dictation, rec, live, alt, letter):
        """On a worker thread: stop recording → transcribe → cleanup → a refinement: Alt+letter's, or (Alt alone,
        or a refinement's letter since deleted) ask which, or (no Alt) the refinement matching the focused app,
        else the default refinement. Then paste (on the GTK thread)."""
        d, context = dictation, dictation.window.describe()
        try:
            rec.stop()  # here, not on the GTK thread: pw-record takes ~0.35 s to finish the file
            try:
                d.raw = live.finish()  # most of it was transcribed while you were speaking
            except Exception as err:
                log.warning("live transcription failed (%s), transcribing the whole recording", err)
                d.raw = stt.transcribe(d.audio)
            d.text = d.cleaned = refine.cleanup(d.raw, context) if d.cleanup and d.raw else d.raw
            refinement = None
            if alt and d.raw:
                refinement = letter and refinements.for_key(letter)
                if not refinement:
                    return GLib.idle_add(self.pick_refinement, d)
            elif d.cleanup and d.raw and d.window.remote:  # we can't see its apps: its own default refinement
                refinement = refinements.default(remote=True)
            elif d.cleanup and d.raw:
                refinement = refinements.for_app(d.window.matches()) or refinements.default()
            if refinement:
                d.text, d.refinement = refine.apply(d.text, refinement, context), refinement["name"]
        except Exception:  # never leave the icon stuck on "busy"
            log.exception("transcription failed")
        finally:
            if d.cleanup:
                llm.server.release()
        GLib.idle_add(self.paste, d)

    def pick_refinement(self, dictation):
        """Alt was tapped without a refinement's letter: ask which (or none) and paste the result."""
        def chosen(refinement, paste):
            if not refinement:
                return self.paste(dictation, paste=paste, delay=400)
            self.set_state("busy")

            def run():
                text = refine.apply(dictation.cleaned, refinement, dictation.window.describe())
                GLib.idle_add(self.paste, replace(dictation, text=text, refinement=refinement["name"]), True, 400)
            threading.Thread(target=run, daemon=True).start()
        huds.RefinementPicker(dictation.cleaned, chosen, on_new=lambda: self.open_hub("refinements", new=True))

    def paste(self, dictation, paste=True, delay=150):
        """Keep it in Dictations (with the recording, and each step: what was heard, cleaned up, refined), then
        paste or type the text. delay: ms for the clipboard to reach Wayland (and, after the picker, for focus
        to return) before pasting."""
        d = dictation
        if self.hotkey.chord.may_go_again():  # this hold may be the start of Ctrl+Win, Win again: wait and see
            GLib.timeout_add(50, lambda: self.paste(d, paste, delay) and False)
            return False
        self.set_state("idle")
        if d.audio == self.cancelled or not d.text:  # it was the start of Ctrl+Win, Win again; or nothing was heard
            Path(d.audio).unlink(missing_ok=True)
            return False
        keep_audio = self.settings["keep_audio_hours"] != 0
        if not keep_audio:
            Path(d.audio).unlink(missing_ok=True)
        history.add(d.entry(keep_audio))
        self.copy(d.text)
        if paste and d.window.remote and remote.on_remote_screen():
            # the other computer has no access to our clipboard paste, so type it; Synergy forwards the keys
            threading.Thread(target=self.paster.type_text, args=(d.text,), daemon=True).start()
        elif paste:
            terminal = osio.LINUX and any(t in d.window.cls.lower() for t in TERMINALS)
            GLib.timeout_add(delay, self.paster.paste, terminal)
        return False

    def copy(self, text):
        self.clip.set_text(text, -1)
        self.clip.store()

    # --- transcribe mode ---
    def on_again(self):
        """Ctrl+Win, lift Win, Win again: start or stop transcribing. The first hold of the gesture was
        reported as a (very short) dictation; drop it."""
        self.cancelled = self.wav
        if not osio.HEARS_SPEAKERS:
            log.info("transcribe mode: not available on this computer yet")
            return
        self.toggle_transcribing()

    def toggle_transcribing(self):
        if self.session:
            self.stop_transcribing()
        else:
            self.start_transcribing()

    def start_transcribing(self):
        try:
            session = transcript.Session(mic=self.microphone())
        except OSError as err:  # e.g. pw-record missing
            log.warning("transcribe mode: can't record (%s)", err)
            return
        self.session = session
        session.on_change = lambda: (self.transcripts_changed(), self.show_state())
        session.on_sound = self.sound_while_paused
        GLib.timeout_add(int(QUIET_CHECK * 1000), self.check_quiet, session)
        self.menu.transcribing(True)
        self.show_transcripts(focus=False)  # started from the keyboard, mid-conversation: leave focus where it is
        session.on_change()
        log.info("transcribing: %s", session.path.name)

    def stop_transcribing(self):
        session, self.session = self.session, None
        if not session:
            return
        if self.reminder:
            self.reminder.close()

        def saved(kept):
            if kept:
                self.waiting.add(session)  # its final pass: now, or once the graphics card is free
            if self.settings["keep_call_hours"] == 0:
                for path in session.recordings:
                    Path(path).unlink(missing_ok=True)
                transcript.forget_mixes()
            self.transcripts_changed()
            log.info("transcribing: stopped, %d paragraphs saved to %s", len(session.paragraphs()), session.path.name)
        session.stop(saved)
        self.menu.transcribing(False)
        self.transcripts_changed()
        self.show_state()

    def transcripts_changed(self):
        if self.hub and not self.hub.closed and "transcripts" in self.hub.pages:
            self.hub.pages["transcripts"].changed()

    def check_quiet(self, session):
        """While transcribing: if nothing's been added for QUIET seconds (since it started or was last resumed),
        pause it and say so."""
        if session is not self.session:
            return False
        self.tray.update()  # how long it's been going, in its tooltip
        if isinstance(self.reminder, huds.Paused) and self.reminder.open and not session.paused:
            self.reminder.close()  # resumed some other way
        if not session.paused and session.quiet_for() >= QUIET:
            session.pause(True)
            log.info("transcribing: paused, nothing added for %d s", QUIET)
            self.say_paused()
        return True

    def say_paused(self):
        """Say a transcript has been paused for being quiet, with Resume and Stop now: beside the capsule, or in
        the middle of the screen if it isn't on screen."""
        if self.reminder and self.reminder.open:
            self.reminder.close()
        heading, body = huds.paused_text(round(QUIET / 60))
        self.reminder = huds.Paused(heading, body, self.capsule.rect() if self.capsule.on_screen() else None,
                                    lambda: self.session and self.session.pause(False), self.stop_transcribing)

    def paused_alert(self):
        """Whether the alert that the transcript is paused for being quiet is up, waiting for Resume or Stop now."""
        return isinstance(self.reminder, huds.Paused) and self.reminder.open

    def sound_while_paused(self):
        """Something was heard while the transcript is paused: if it was paused for being quiet, draw attention
        to the alert."""
        if self.paused_alert():
            self.draw_attention()

    def draw_attention(self, focus=False):
        """Flash the capsule and the tray icon for FLASH seconds, and bring the paused alert back above other
        windows (focus: and to the front, for the keyboard: you've just reached for Dictate)."""
        if focus:
            self.reminder.bring_up(focus=True)
        if not self.flash_until:
            if not focus:
                self.reminder.bring_up()
            GLib.timeout_add(300, self.flash)
        self.flash_until = time.monotonic() + FLASH

    def flash(self):
        on = (time.monotonic() < self.flash_until and self.session and self.session.paused
              and self.paused_alert())
        self.capsule.flash(bool(on) and not self.capsule.flashing)
        self.tray.update()
        if not on:
            self.flash_until = 0.0
        return bool(on)

    def remind(self, why):
        """Say a transcript is still being recorded, and how to stop it: beside the capsule, or, if it isn't on
        screen, as a desktop notification. why: "closed" (the Dictate window)."""
        if not self.session or (isinstance(self.reminder, huds.Paused) and self.reminder.open):
            return  # (the alert that it's paused stays until it's resumed or stopped)
        if self.reminder and self.reminder.open:
            self.reminder.close()
        minutes = round(QUIET / 60)
        log.info("reminding that it's still transcribing (%s)", why)
        if self.capsule.on_screen():
            self.reminder = huds.StillTranscribing(why, minutes, self.capsule.picture(), self.capsule.rect(),
                                                   self.stop_transcribing)
            return
        heading, body = huds.reminder_text(why, minutes)
        image = Path(GLib.get_user_cache_dir()) / "dictate" / "transcribing.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        self.render_icon(128).write_to_png(str(image))
        ways = "".join(f"\n• {w}" for w in huds.STOP_WAYS)
        osio.notify(f"⚠ {heading}", f"{body}\n\nA capsule with a red dot and a timer means it's transcribing. "
                                    f"To stop it:{ways}", [("stop", "Stop now"), ("show", "Show transcript")],
                    lambda key: self.stop_transcribing() if key == "stop" else self.show_transcripts(recording=True),
                    image)

    # --- the Dictate window ---
    def open_hub(self, page, focus=True, **kw):
        """Open the Dictate window on page (or bring it forward), passing kw to the page."""
        if not (self.hub and not self.hub.closed):
            self.hub = hub.Hub(self)
            self.hub.win.connect("delete-event", lambda *_: self.hub_closed())
        return self.hub.show(page, focus, **kw)

    def show_transcripts(self, focus=True, recording=False):
        """Open Transcripts; with recording, showing the one being recorded."""
        self.open_hub("transcripts", focus, recording=recording)

    def hub_closed(self):
        """The Dictate window was closed: if a transcript's being recorded, say it still is, once a day."""
        today = datetime.now().date().isoformat()
        if self.session and self.settings.get("reminded_closed") != today:
            self.settings.update(reminded_closed=today)
            GLib.idle_add(lambda: self.remind("closed") and False)

    # --- running ---
    def quit(self, reason):
        """Every way out goes through here, so the log says why Dictate stopped."""
        log.info("quitting: %s", reason)
        if self.rec:  # mid-dictation: don't leave the microphone recording
            self.rec.stop()
            self.rec = None
        if self.session:  # save what's still to be transcribed
            session, self.session = self.session, None
            session.stop(lambda kept: Gtk.main_quit())  # (its final pass, next time: it's saved as waiting)
            return
        Gtk.main_quit()

    def run(self):
        log.info("started (pid %d)", os.getpid())
        Gtk.main()
        self.loader.join()  # exiting while the speech model is still loading crashes inside onnxruntime
        log.info("exited")


def only_instance():
    """Claim a fixed local port: only one process can hold it, and the OS frees it even after a crash.
    Two copies would both hear the hotkey and paste everything twice."""
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        sys.exit("Dictate is already running.")
    return lock
