"""Everything that differs between Linux, Windows and macOS: the global hotkey, recording, and pasting.

Linux reads keyboards with evdev, records with pw-record and pastes through uinput (works on Wayland).
Windows and macOS use pynput for keys and sounddevice for the microphone.
"""
import ctypes
import itertools
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import unicodedata
import wave
from pathlib import Path

from gi.repository import GLib

from . import ROOT

log = logging.getLogger(__name__)

LINUX, WINDOWS, MAC = sys.platform.startswith("linux"), sys.platform == "win32", sys.platform == "darwin"
HEARS_SPEAKERS = LINUX  # Recorder can record what the computer plays (transcribe mode)


def _die_with_us():  # Linux, in the child: if Dictate exits or crashes, the recorder (or player) stops too
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG; pw-record finishes its file on SIGTERM


TIED = {"preexec_fn": _die_with_us} if LINUX else {}  # (it's the starting *thread* that counts: start these
# from the GTK thread, which lasts as long as Dictate)
RATE = 16000
SCRIPT = ROOT / "dictate.py"
# macOS virtual key codes (ANSI layout) for A–Z; Option changes the typed character, so match the key itself
MAC_LETTERS = dict(zip((0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46, 45, 31, 35, 12, 15, 1, 17, 32, 9, 13, 7, 16, 6),
                       "abcdefghijklmnopqrstuvwxyz"))


PLAIN = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
                      "\u2026": "...", "\u00a0": " ", "\u2022": "-"})


def plain(text):
    """Text that a plain keyboard can type: typographic quotes/dashes become ASCII, accents are dropped."""
    text = unicodedata.normalize("NFKD", text.translate(PLAIN))
    return "".join(c for c in text if not unicodedata.combining(c))


_notified = {}  # notification id: on_action, for the buttons of the ones still showing


def notify(title, body, actions=(), on_action=lambda key: None, image=None):
    """A desktop notification that stays until it's dismissed, with buttons (actions: [(key, label)]);
    on_action(key) runs on the GTK thread when one's clicked; image: a PNG's path. Linux only (the
    freedesktop Notifications service); elsewhere, or if there's none, it's only logged."""
    log.info("notification: %s - %s", title, body)
    if not LINUX:
        return
    from gi.repository import Gio
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        if not _notified:
            bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked",
                                 "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE,
                                 lambda *a: _clicked(*a[5].unpack()))
        hints = {"image-path": GLib.Variant("s", str(image))} if image else {}
        reply = bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                              "org.freedesktop.Notifications", "Notify",
                              GLib.Variant("(susssasa{sv}i)", ("Dictate", 0, str(ROOT / "dictate/icon.png"), title,
                                                               body, [x for a in actions for x in a], hints, 0)),
                              None, Gio.DBusCallFlags.NONE, 2000, None)
        _notified[reply.unpack()[0]] = on_action
    except GLib.Error as err:
        log.warning("notification: couldn't show it: %s", err.message)


def _clicked(nid, key):
    if nid in _notified:
        _notified.pop(nid)(key)


def dbus_register(conn, path, interface, method_call, get_property=None):
    """Export a D-Bus object. register_object_with_closures2 needs GLib 2.84+; older GLib (e.g. Ubuntu 24.04)
    has register_object, which PyGObject gives the same arguments."""
    register = getattr(conn, "register_object_with_closures2", None) or conn.register_object
    return register(path, interface, method_call, get_property, None)


class Chord:
    """Ctrl+Win (Ctrl+Cmd on a Mac) state machine. Calls callback(down, alt, letter) on the GTK thread:
    on press, on release (alt = Alt was touched during the hold, letter = any A–Z pressed with Alt),
    and once when Alt is first pressed mid-hold (so the app can start loading the model).

    Lifting Win and pressing it again within AGAIN seconds, with Ctrl held throughout, calls on_again()
    instead of starting another hold (transcribe mode). The first hold has already been reported by then.

    Any other key with Ctrl+Win (Ctrl+Win+→, Shift, Alt and a letter that's no refinement's: letters() gives the
    refinements' letters) makes it another app's shortcut, not a dictation: on_other() is called, if the hold has
    been reported, and nothing more is said about it. So is Ctrl+Win pressed while another key's held."""
    AGAIN = 1.0
    MODIFIERS = {"ctrl", "meta", "alt"}

    def __init__(self, callback, on_again=None, on_other=lambda: None, letters=None):
        self.callback, self.on_again, self.held = callback, on_again, {}
        self.active, self.alt, self.letter = False, False, None
        self.on_other, self.letters = on_other, letters  # letters None: any letter is a refinement's
        self.pressed_at = None  # when the chord's key was physically pressed (wall clock), for latency logs
        self.lifted = None  # when Win was let go with Ctrl still down (monotonic), until Ctrl is let go too
        self.again = False  # this hold is the "again" press: report nothing about it
        self.other = False  # this hold is another app's shortcut: report nothing more about it

    def key(self, ident, kind, down, at=None):
        """ident: a stable id for the physical key; kind: "ctrl", "meta", "alt", a letter, or None;
        at: when the key was physically pressed, if the OS says (else now)."""
        if down:
            if ident in self.held:
                return  # auto-repeat
            self.held[ident] = kind
        else:
            self.held.pop(ident, None)
        kinds = set(self.held.values())
        if "ctrl" not in kinds:
            self.lifted = None
        if self.active and down and not (self.again or self.other):
            if kind == "alt":
                self.alt = True
                GLib.idle_add(self.callback, True, True, None)
            elif kind and len(kind) == 1 and "alt" in kinds and (self.letters is None or kind in self.letters()):
                self.letter = kind
            elif kind not in self.MODIFIERS:
                self.other = True
                GLib.idle_add(self.on_other)
        on = {"ctrl", "meta"} <= kinds
        if on == self.active:
            return
        self.active = on
        if not on:
            if self.again:
                self.again = False  # the next Win press is an ordinary hold again
            elif self.other:
                self.other, self.lifted = False, None  # (pressing Win again isn't Ctrl+Win, Win again either)
            else:
                self.lifted = time.monotonic() if "ctrl" in kinds else None
                GLib.idle_add(self.callback, False, self.alt, self.letter)
        elif self.on_again and self.may_go_again():
            self.again, self.lifted = True, None
            GLib.idle_add(self.on_again)
        elif kinds - self.MODIFIERS:  # another key was already down: its shortcut, never reported
            self.other = True
        else:
            self.alt, self.letter, self.pressed_at = "alt" in kinds, None, at or time.time()
            GLib.idle_add(self.callback, True, self.alt, self.letter)

    def release_all(self):
        """Every key counts as let go (the keyboard holding them was unplugged)."""
        for ident, kind in list(self.held.items()):
            self.key(ident, kind, False)

    def may_go_again(self):
        """Whether pressing Win now would still be "again": Win was lifted moments ago, Ctrl is still down."""
        return bool(self.lifted) and time.monotonic() - self.lifted < self.AGAIN


if LINUX:
    import selectors

    import evdev
    from evdev import ecodes as e

    KINDS = {e.KEY_LEFTCTRL: "ctrl", e.KEY_RIGHTCTRL: "ctrl", e.KEY_LEFTMETA: "meta", e.KEY_RIGHTMETA: "meta",
             e.KEY_LEFTALT: "alt", e.KEY_RIGHTALT: "alt",
             **{getattr(e, f"KEY_{c}"): c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}}

    VIRTUAL = "Dictate virtual keyboard"  # the one Paster types with: not one to watch

    class Hotkey(threading.Thread):
        """Watches every keyboard via evdev (global, works on Wayland). The kernel timestamps each key.
        Keyboards come and go (unplugged, a USB hub dropping out): one that goes is let go of, with any keys it
        held; one that comes is watched from then on (looked for whenever DIR changes). One not ours to read yet
        (just after login, before logind lets this session read them) is tried again: DIR doesn't change for that."""
        DIR = "/dev/input"
        RESCAN = 1.0  # seconds between looks at whether DIR has changed
        RETRY = 1.0, 30.0  # seconds between tries of those not ours to read: while none is watched, and otherwise

        def __init__(self, callback, on_again=None, on_other=lambda: None, letters=None):
            super().__init__(daemon=True)
            self.chord, self.sel = Chord(callback, on_again, on_other, letters), selectors.DefaultSelector()
            self.watching, self.denied = {}, set()
            self.changed = self.stamp()
            self.scan()

        def stamp(self):
            try:
                return os.stat(self.DIR).st_mtime_ns
            except OSError:
                return None

        def scan(self):
            """Watch every keyboard not watched yet."""
            self.tried, paths = time.monotonic(), evdev.list_devices(self.DIR)
            self.denied &= set(paths)
            for path in paths:
                if path in self.watching:
                    continue
                try:
                    dev = evdev.InputDevice(path)
                    keyboard = e.KEY_LEFTCTRL in dev.capabilities().get(e.EV_KEY, []) and dev.name != VIRTUAL
                except PermissionError:  # not ours to read (yet)
                    if path not in self.denied:
                        log.info("hotkey: not allowed to read %s yet", path)
                        self.denied.add(path)
                    continue
                except OSError:  # gone again already
                    continue
                self.denied.discard(path)
                if keyboard:
                    self.sel.register(dev, selectors.EVENT_READ)
                    self.watching[path] = dev
                    log.info("hotkey: watching %s", dev.name)
                else:
                    dev.close()

        def lost(self, dev):
            self.sel.unregister(dev)
            self.watching.pop(dev.path, None)
            try:
                dev.close()
            except OSError:
                pass
            log.info("hotkey: keyboard gone: %s", dev.name)
            self.chord.release_all()  # its keys can't be let go of now: don't leave Ctrl+Win held

        def run(self):
            while True:
                for key, _ in self.sel.select(self.RESCAN):
                    try:
                        events = list(key.fileobj.read())  # (read() is a generator: it raises when iterated)
                    except OSError:  # unplugged
                        self.lost(key.fileobj)
                        continue
                    for ev in events:  # (not mouse buttons: clicking while dictating isn't another shortcut)
                        if ev.type == e.EV_KEY and ev.value != 2 and ev.code not in e.BTN:
                            self.chord.key(ev.code, KINDS.get(ev.code), ev.value == 1, ev.timestamp())
                if self.stamp() != self.changed:  # a device was added or removed
                    self.changed = self.stamp()
                    self.scan()
                elif self.denied and time.monotonic() - self.tried >= self.RETRY[bool(self.watching)]:
                    self.scan()

    _cancellers = itertools.count()

    def microphones():
        """The microphones connected now, the default one first: [(name, description)]. Names are PipeWire's,
        which stay the same when a microphone is plugged in again. A wireless headset that's off doesn't count,
        though its dongle's still plugged in, where its dongle can say so (headsets.py)."""
        try:
            sources = json.loads(subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True,
                                                text=True, timeout=2).stdout)
            default = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True,
                                     timeout=2).stdout.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []
        from . import headsets
        off = {}  # sound card: whether it's a wireless headset's dongle, and the headset's off

        def connected(s):
            card = s.get("properties", {}).get("alsa.card")
            if card is None:
                return True
            if card not in off:
                off[card] = headsets.off(card)
            return not off[card]
        mics = [(s["name"], s.get("description") or s["name"]) for s in sources
                if s.get("properties", {}).get("media.class") == "Audio/Source"
                and not s["name"].startswith("dictate-")  # (not our echo canceller's)
                and connected(s)]  # (a headset that's off, its dongle still plugged in, isn't: headsets.py)
        return sorted(mics, key=lambda m: m[0] != default)

    _recordings = itertools.count()

    class Recorder:
        def start(self, path, speakers=False, on_audio=None, echo_cancel=False, mic=None, hush=None,
                  on_move=lambda: None):
            """Record the microphone (mic: its name from microphones(); None, the default one), or (speakers)
            whatever this computer is playing: PipeWire's monitor of the default output (still heard while the
            output is muted). Into a WAV file; or, with on_audio, into an Ogg Opus file (about a tenth of the
            size) while passing each chunk of 16-bit samples to on_audio as it's recorded (on the recorder's
            thread). echo_cancel: the microphone with what the speakers are playing taken out of it (see
            _echo_cancelled), where PipeWire can. hush(chunk), with on_audio: True to save and pass on silence
            instead of that chunk (it's still heard by hush). A microphone's recording can be moved to another
            microphone as it's recorded (move); on_move() then, on the thread that moved it."""
            self.canceller, self.stream = None, None  # self.stream: the PipeWire node that reads the microphone
            self.on_move = on_move
            if speakers:
                source = ["-P", "{ stream.capture.sink=true }"]
            elif echo_cancel and (found := _echo_cancelled(mic)):
                self.canceller, name = found
                source, self.stream = ["--target", name], f"{name}-capture"
            else:
                self.stream = f"dictate-recording-{os.getpid()}-{next(_recordings)}"
                source = ["-P", f"{{ node.name = {self.stream} }}", *(["--target", mic] if mic else [])]
            cmd = ["pw-record", *source, "--rate", str(RATE), "--channels", "1", "--format", "s16"]
            if not on_audio:
                self.proc, self.reader = subprocess.Popen([*cmd, path], **TIED), None
                return
            import numpy as np
            import soundfile
            out = soundfile.SoundFile(path, "w", RATE, 1, format="OGG", subtype="OPUS")
            self.proc = subprocess.Popen([*cmd, "--raw", "-"], stdout=subprocess.PIPE, **TIED)

            def pump():
                with out:
                    while chunk := self.proc.stdout.read(RATE // 5):  # 0.1 s of samples
                        chunk = chunk[:len(chunk) // 2 * 2]
                        if hush and hush(chunk):
                            chunk = bytes(len(chunk))
                        out.write(np.frombuffer(chunk, np.int16))
                        on_audio(chunk)
            self.reader = threading.Thread(target=pump, daemon=True)
            self.reader.start()

        def move(self, mic):
            """Record mic from now on (slow: not on the GTK thread): PipeWire moves the stream that reads the
            microphone (pw-record's, or the echo canceller's) to it, as it's recorded, as moving it in a volume
            control would. Returns whether it did."""
            if not self.stream:
                return False
            for _ in range(10):  # (just started, it may not be listed yet)
                try:
                    found = json.loads(subprocess.run(["pactl", "-f", "json", "list", "source-outputs"],
                                                      capture_output=True, text=True, timeout=2).stdout)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    return False
                index = next((o["index"] for o in found if o.get("properties", {}).get("node.name") == self.stream),
                             None)
                if index is not None:
                    moved = subprocess.run(["pactl", "move-source-output", str(index), mic], capture_output=True,
                                           timeout=2).returncode == 0
                    log.info("recording: moved to %s%s", mic, "" if moved else " (couldn't)")
                    if moved:
                        self.on_move()
                    return moved
                time.sleep(0.1)
            return False

        def stop(self):
            self.proc.terminate()
            self.proc.wait()
            if self.reader:
                self.reader.join()  # everything recorded has been passed on and saved
            if self.canceller:
                self.canceller.terminate()  # which unloads the echo canceller
                self.canceller.wait()

    def _echo_cancelled(mic=None):
        """(process, node name) of a microphone (mic, else the default one) with the speakers taken out of it, or
        None if PipeWire can't: its WebRTC echo canceller, comparing it with what the default output plays. Without
        it, the microphone hears the speakers too (unless it's headphones), as if you'd said it. Loaded by a
        pw-cli that keeps it loaded until it's stopped (or Dictate is), so nothing is left behind."""
        name = f"dictate-echo-cancel-{os.getpid()}-{next(_cancellers)}"
        args = (f'{{ library.name = aec/libspa-aec-webrtc monitor.mode = true audio.rate = {RATE} audio.channels = 1 '
                f'source.props = {{ node.name = "{name}" node.description = "Dictate: microphone without the speakers" '
                f'node.passive = true }} capture.props = {{ node.name = "{name}-capture" '
                + (f'target.object = "{mic}" ' if mic else "") + "} }")
        try:
            proc = subprocess.Popen(["pw-cli", "-m", "load-module", "libpipewire-module-echo-cancel", args],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    **TIED)
        except OSError:
            return None
        for _ in range(30):  # it's there within a few tenths of a second
            if proc.poll() is not None:
                return None
            if "id:" in subprocess.run(["pw-cli", "info", name], capture_output=True, text=True).stdout:
                return proc, name
            time.sleep(0.1)
        proc.terminate()
        return None

    def _layout():
        """The first keyboard layout KDE is set to (e.g. "gb"), else "us"."""
        try:
            for line in (Path.home() / ".config/kxkbrc").read_text().splitlines():
                if line.startswith("LayoutList="):
                    return line.split("=", 1)[1].split(",")[0].strip() or "us"
        except OSError:
            pass
        return "us"

    def _keymap(layout):
        """char -> (key code, needs Shift) for typing on this machine's layout (US, with UK differences)."""
        keys = {}
        for c in "abcdefghijklmnopqrstuvwxyz":
            code = getattr(e, f"KEY_{c.upper()}")
            keys[c], keys[c.upper()] = (code, False), (code, True)
        for row, shifted in (("1234567890", "!@#$%^&*()"), ("-=[];',./`\\", '_+{}:"<>?~|')):
            names = {"-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE", ";": "SEMICOLON",
                     "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH", "`": "GRAVE", "\\": "BACKSLASH"}
            for plain_c, shift_c in zip(row, shifted):
                code = getattr(e, f"KEY_{names.get(plain_c, plain_c)}")
                keys[plain_c], keys[shift_c] = (code, False), (code, True)
        if layout == "gb":  # where UK keyboards differ from US ones
            keys.update({'"': (e.KEY_2, True), "@": (e.KEY_APOSTROPHE, True), "#": (e.KEY_BACKSLASH, False),
                         "~": (e.KEY_BACKSLASH, True), "\\": (e.KEY_102ND, False), "|": (e.KEY_102ND, True),
                         "\u00a3": (e.KEY_3, True), "\u00ac": (e.KEY_GRAVE, True)})
        keys[" "], keys["\t"], keys["\n"] = (e.KEY_SPACE, False), (e.KEY_TAB, False), (e.KEY_ENTER, True)
        return keys  # Enter is Shift+Enter: a new line without sending a chat message

    class Paster:
        """Types the paste shortcut (or whole text) through a virtual keyboard (named VIRTUAL, so Hotkey
        doesn't watch it)."""

        def __init__(self):
            self.kbd = evdev.UInput(name=VIRTUAL)
            self.keys = _keymap(_layout())

        def type_text(self, text):
            """Type text key by key (e.g. into another computer through Synergy). Skips untypeable characters."""
            for c in plain(text):
                if c not in self.keys:
                    continue
                code, shift = self.keys[c]
                for k, v in (([(e.KEY_LEFTSHIFT, 1)] if shift else []) + [(code, 1), (code, 0)]
                             + ([(e.KEY_LEFTSHIFT, 0)] if shift else [])):
                    self.kbd.write(e.EV_KEY, k, v)
                    self.kbd.syn()
                    time.sleep(0.003)  # let the forwarding (e.g. Synergy over the network) keep up

        def paste(self, terminal):
            mods = (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT) if terminal else (e.KEY_LEFTCTRL,)  # terminals: Ctrl+Shift+V
            for code, val in [(k, 1) for k in mods] + [(e.KEY_V, 1), (e.KEY_V, 0)] + [(k, 0) for k in reversed(mods)]:
                self.kbd.write(e.EV_KEY, code, val)
                self.kbd.syn()

else:
    import sounddevice
    from pynput import keyboard

    K = keyboard.Key
    KINDS = {K.ctrl: "ctrl", K.ctrl_l: "ctrl", K.ctrl_r: "ctrl", K.cmd: "meta", K.cmd_l: "meta", K.cmd_r: "meta",
             K.alt: "alt", K.alt_l: "alt", K.alt_r: "alt", getattr(K, "alt_gr", K.alt_r): "alt"}

    def _ident_kind(key):
        if isinstance(key, keyboard.KeyCode):
            vk = key.vk
            letter = MAC_LETTERS.get(vk) if MAC else (chr(vk).lower() if vk and 65 <= vk <= 90 else None)
            return ("vk", vk), letter
        return key, KINDS.get(key)

    class Hotkey:
        """Global key listener via pynput (on macOS this needs Input Monitoring permission)."""

        def __init__(self, callback, on_again=None, on_other=lambda: None, letters=None):
            self.chord = chord = Chord(callback, on_again, on_other, letters)
            self.listener = keyboard.Listener(on_press=lambda k: chord.key(*_ident_kind(k), True),
                                              on_release=lambda k: chord.key(*_ident_kind(k), False))

        def start(self):
            self.listener.start()

    def microphones():
        """The microphones connected now, the default one first: [(name, name)]."""
        try:
            default = sounddevice.default.device[0]
            mics = [(d["name"], i) for i, d in enumerate(sounddevice.query_devices()) if d["max_input_channels"]]
        except sounddevice.PortAudioError:
            return []
        return [(name, name) for name, _ in sorted(mics, key=lambda m: m[1] != default)]

    class Recorder:
        def start(self, path, speakers=False, on_audio=None, echo_cancel=False, mic=None, hush=None,
                  on_move=None):
            if speakers or on_audio:  # (so echo_cancel doesn't arise)
                raise NotImplementedError("recording the speakers is Linux-only for now")
            self.wav = wave.open(path, "wb")  # noqa: SIM115 (open until stop())
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)
            self.wav.setframerate(RATE)
            self.stream = sounddevice.RawInputStream(samplerate=RATE, channels=1, dtype="int16", device=mic,
                                                     callback=lambda data, *_: self.wav.writeframes(bytes(data)))
            self.stream.start()

        def move(self, mic):
            return False  # (sounddevice can't: it carries on with the one it started with)

        def stop(self):
            self.stream.stop()
            self.stream.close()
            self.wav.close()

    class Paster:
        """Presses Ctrl+V (Cmd+V on a Mac; on macOS this needs Accessibility permission)."""

        def __init__(self):
            self.kbd = keyboard.Controller()

        def paste(self, terminal):
            with self.kbd.pressed(K.cmd if MAC else K.ctrl):
                self.kbd.tap("v")

        def type_text(self, text):
            """Type text key by key (e.g. into another computer through Synergy). New lines are Shift+Enter."""
            for i, line in enumerate(plain(text).split("\n")):
                if i:
                    with self.kbd.pressed(K.shift):
                        self.kbd.tap(K.enter)
                self.kbd.type(line)


class Player:
    """Plays one WAV recording at a time (pw-play on Linux, sounddevice elsewhere).
    on_done() runs on the GTK thread when playback ends, whether it finished or was stopped;
    on_playing(True / False) when something starts playing and when nothing is any more."""

    def __init__(self, on_playing=lambda playing: None):
        self.proc, self.on_playing, self.current = None, on_playing, None

    def play(self, path, on_done):
        self.stop()
        self.current = turn = object()
        self.on_playing(True)
        def ended():
            if self.current is turn:  # not replaced by another recording meanwhile
                self.current = None
                self.on_playing(False)
            on_done()
        if LINUX:
            proc = self.proc = subprocess.Popen(["pw-play", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                **TIED)
            wait = proc.wait
        else:
            import numpy as np
            with wave.open(path) as w:
                samples, rate = np.frombuffer(w.readframes(w.getnframes()), np.int16), w.getframerate()
            sounddevice.play(samples, rate)
            wait = sounddevice.wait
        threading.Thread(target=lambda: (wait(), GLib.idle_add(ended)), daemon=True).start()

    def stop(self):
        if LINUX and self.proc and self.proc.poll() is None:
            self.proc.terminate()
        elif not LINUX:
            sounddevice.stop()


# --- run at startup: KDE/XDG autostart entry, the Windows Run registry key, or a macOS LaunchAgent ---
if LINUX:
    AUTOSTART = Path.home() / ".config/autostart/dictate.desktop"

    def autostart_enabled():
        return AUTOSTART.exists()

    def set_autostart(on):
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(f'[Desktop Entry]\nType=Application\nName=Dictate\n'
                                 f'Exec="{sys.executable}" "{SCRIPT}"\nIcon={ROOT / "dictate/icon.png"}\n'
                                 f'StartupWMClass=dictate\n')
        else:
            AUTOSTART.unlink(missing_ok=True)

elif WINDOWS:
    import winreg
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def autostart_enabled():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                winreg.QueryValueEx(key, "Dictate")
                return True
            except FileNotFoundError:
                return False

    def set_autostart(on):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                pythonw = Path(sys.executable).with_name("pythonw.exe")  # no console window
                winreg.SetValueEx(key, "Dictate", 0, winreg.REG_SZ, f'"{pythonw}" "{SCRIPT}"')
            else:
                try:
                    winreg.DeleteValue(key, "Dictate")
                except FileNotFoundError:
                    pass

else:
    import plistlib
    AGENT = Path.home() / "Library/LaunchAgents/local.dictate.plist"

    def autostart_enabled():
        return AGENT.exists()

    def set_autostart(on):
        if on:
            AGENT.parent.mkdir(parents=True, exist_ok=True)
            AGENT.write_bytes(plistlib.dumps({"Label": "local.dictate", "RunAtLoad": True,
                                              "ProgramArguments": [sys.executable, str(SCRIPT)]}))
        else:
            AGENT.unlink(missing_ok=True)
