"""Everything that differs between Linux, Windows and macOS: the global hotkey, recording, and pasting.

Linux reads keyboards with evdev, records with pw-record and pastes through uinput (works on Wayland).
Windows and macOS use pynput for keys and sounddevice for the microphone.
"""
import subprocess, sys, threading, wave
from gi.repository import GLib

LINUX, WINDOWS, MAC = sys.platform.startswith("linux"), sys.platform == "win32", sys.platform == "darwin"
RATE = 16000
# macOS virtual key codes (ANSI layout) for A–Z; Option changes the typed character, so match the key itself
MAC_LETTERS = dict(zip((0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46, 45, 31, 35, 12, 15, 1, 17, 32, 9, 13, 7, 16, 6),
                       "abcdefghijklmnopqrstuvwxyz"))


class Chord:
    """Ctrl+Win (Ctrl+Cmd on a Mac) state machine. Calls callback(down, alt, letter) on the GTK thread:
    on press, on release (alt = Alt was touched during the hold, letter = any A–Z pressed with Alt),
    and once when Alt is first pressed mid-hold (so the app can start loading the model)."""

    def __init__(self, callback):
        self.callback, self.held, self.active, self.alt, self.letter = callback, {}, False, False, None

    def key(self, ident, kind, down):
        """ident: a stable id for the physical key; kind: "ctrl", "meta", "alt", a letter, or None."""
        if down:
            if ident in self.held:
                return  # auto-repeat
            self.held[ident] = kind
        else:
            self.held.pop(ident, None)
        kinds = set(self.held.values())
        if self.active and down and kind == "alt":
            self.alt = True
            GLib.idle_add(self.callback, True, True, None)
        elif self.active and down and kind and len(kind) == 1 and "alt" in kinds:
            self.letter = kind
        on = {"ctrl", "meta"} <= kinds
        if on != self.active:
            self.active = on
            if on:
                self.alt, self.letter = "alt" in kinds, None
            GLib.idle_add(self.callback, on, self.alt, self.letter)


if LINUX:
    import selectors
    import evdev
    from evdev import ecodes as e

    KINDS = {e.KEY_LEFTCTRL: "ctrl", e.KEY_RIGHTCTRL: "ctrl", e.KEY_LEFTMETA: "meta", e.KEY_RIGHTMETA: "meta",
             e.KEY_LEFTALT: "alt", e.KEY_RIGHTALT: "alt",
             **{getattr(e, f"KEY_{c}"): c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}}

    class Hotkey(threading.Thread):
        """Watches every keyboard via evdev (global, works on Wayland)."""

        def __init__(self, callback):
            super().__init__(daemon=True)
            self.chord, self.sel = Chord(callback), selectors.DefaultSelector()
            for path in evdev.list_devices():
                dev = evdev.InputDevice(path)
                if e.KEY_LEFTCTRL in dev.capabilities().get(e.EV_KEY, []):
                    self.sel.register(dev, selectors.EVENT_READ)

        def run(self):
            while True:
                for key, _ in self.sel.select():
                    for ev in key.fileobj.read():
                        if ev.type == e.EV_KEY and ev.value != 2:
                            self.chord.key(ev.code, KINDS.get(ev.code), ev.value == 1)

    class Recorder:
        def start(self, path):
            self.proc = subprocess.Popen(["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", path])

        def stop(self):
            self.proc.terminate()
            self.proc.wait()

    class Paster:
        """Types the paste shortcut through a virtual keyboard. Create it after Hotkey, so Hotkey doesn't see it."""

        def __init__(self):
            self.kbd = evdev.UInput()

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

        def __init__(self, callback):
            chord = Chord(callback)
            self.listener = keyboard.Listener(on_press=lambda k: chord.key(*_ident_kind(k), True),
                                              on_release=lambda k: chord.key(*_ident_kind(k), False))

        def start(self):
            self.listener.start()

    class Recorder:
        def start(self, path):
            self.wav = wave.open(path, "wb")
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)
            self.wav.setframerate(RATE)
            self.stream = sounddevice.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                                     callback=lambda data, *_: self.wav.writeframes(bytes(data)))
            self.stream.start()

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
