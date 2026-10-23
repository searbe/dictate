"""Keyboards coming and going while Dictate runs (Linux): one unplugged, or a USB hub dropping out for a
moment, mustn't stop Ctrl+Win working, or leave it held; one plugged in works from then on. The keyboards here
are stand-ins (no key reaches your desktop), but the hotkey watching them is the real one (osio.Hotkey)."""
import glob
import os
import sys
import time

import pytest
from gi.repository import GLib

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="evdev is Linux's")
if sys.platform.startswith("linux"):
    from evdev import InputEvent
    from evdev import ecodes as e

    from dictate import osio


class Keyboard:
    """A stand-in keyboard at path: keys pressed on it are read as from a real one."""

    def __init__(self, folder, n, name="USB keyboard",
                 keys=(e.KEY_LEFTCTRL,) if sys.platform.startswith("linux") else ()):
        self.path, self.name, self.keys, self.queued, self.gone = str(folder / f"event{n}"), name, keys, [], False
        self.r, self.w = os.pipe()
        open(self.path, "w").close()  # the device's node appearing

    def fileno(self):
        return self.r

    def capabilities(self):
        return {e.EV_KEY: list(self.keys)}

    def read(self):  # a generator, like evdev's: an unplugged keyboard's error comes when it's iterated
        os.read(self.r, 1)
        if self.gone:
            raise OSError(19, "No such device")
        yield self.queued.pop(0)

    def close(self):
        pass

    def key(self, code, down):
        self.queued.append(InputEvent(int(time.time()), 0, e.EV_KEY, code, 1 if down else 0))
        os.write(self.w, b".")

    def unplug(self):
        self.gone = True
        os.unlink(self.path)
        os.write(self.w, b".")


@pytest.fixture
def plugged(tmp_path, monkeypatch):
    """plugged(n, ...) plugs in a stand-in keyboard; returns (it, the hotkey's presses and releases)."""
    devices = {}

    def device(path):
        if path not in devices:  # (another test's)
            raise OSError(2, "No such device")
        return devices[path]
    monkeypatch.setattr(osio.evdev, "InputDevice", device)
    monkeypatch.setattr(osio.evdev, "list_devices",
                        lambda folder: sorted(glob.glob(f"{folder}/event*")))  # (not real devices)

    def plug(n, **kw):
        kb = Keyboard(tmp_path, n, **kw)
        devices[kb.path] = kb
        os.utime(tmp_path, ns=(time.time_ns(), time.time_ns() + n))  # (a new node changes the folder)
        return kb
    plug.folder = str(tmp_path)
    return plug


def hotkey(plugged):
    """The real hotkey, watching plugged's keyboards; returns it and the list its presses (True), releases
    (False) and other apps' shortcuts ("other") go to. (Each test's has its own folder: the hotkeys of earlier tests are
    still running.)"""
    class Hotkey(osio.Hotkey):
        DIR, RESCAN = plugged.folder, 0.05
    calls = []
    hk = Hotkey(lambda down, alt, letter: calls.append(down), on_other=lambda: calls.append("other"))
    hk.start()
    return hk, calls


def eventually(check, timeout=3):
    deadline = time.monotonic() + timeout
    while not check():
        GLib.MainContext.default().iteration(False)  # the hotkey reports on the GTK thread
        assert time.monotonic() < deadline, "never happened"
        time.sleep(0.01)


def chord(kb, down):
    for code in (e.KEY_LEFTCTRL, e.KEY_LEFTMETA) if down else (e.KEY_LEFTMETA, e.KEY_LEFTCTRL):
        kb.key(code, down)


def test_ctrl_win_still_works_after_a_keyboard_is_unplugged(plugged):
    gone, kept = plugged(1), plugged(2)
    _, calls = hotkey(plugged)

    gone.unplug()
    time.sleep(0.2)
    chord(kept, True)
    chord(kept, False)

    eventually(lambda: calls == [True, False])


def test_a_keyboard_plugged_in_later_works(plugged):
    plugged(1)
    _, calls = hotkey(plugged)

    new = plugged(2)
    time.sleep(0.3)
    chord(new, True)

    eventually(lambda: calls == [True])


def test_a_keyboard_that_drops_out_and_comes_back_works_again(plugged):
    """A USB hub dropping out for a moment: the same keyboard, gone, then back (as a new device)."""
    kb = plugged(1)
    _, calls = hotkey(plugged)
    kb.unplug()
    time.sleep(0.2)

    back = plugged(1)
    time.sleep(0.3)
    chord(back, True)
    chord(back, False)

    eventually(lambda: calls == [True, False])


def test_unplugged_mid_dictation_it_counts_as_let_go(plugged):
    kb = plugged(1)
    _, calls = hotkey(plugged)
    chord(kb, True)
    eventually(lambda: calls == [True])

    kb.unplug()

    eventually(lambda: calls == [True, False])  # not left recording, with Ctrl+Win held for ever


def test_dictates_own_virtual_keyboard_is_not_watched(plugged):
    plugged(1, name=osio.VIRTUAL, keys=(e.KEY_LEFTCTRL, e.KEY_LEFTMETA))
    hk, _ = hotkey(plugged)

    assert hk.watching == {}


def test_clicking_the_mouse_while_dictating_is_not_another_apps_shortcut(plugged):
    """A mouse's buttons come as keys too (and some mice are keyboards as well): clicking around while holding
    Ctrl+Win carries on dictating."""
    kb = plugged(1)
    _, calls = hotkey(plugged)
    chord(kb, True)

    for button in (e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE, e.BTN_SIDE):
        kb.key(button, True)
        kb.key(button, False)
    chord(kb, False)

    eventually(lambda: calls == [True, False])


def test_another_key_while_dictating_is_still_another_apps_shortcut(plugged):
    kb = plugged(1)
    _, calls = hotkey(plugged)
    chord(kb, True)

    kb.key(e.KEY_RIGHT, True)

    eventually(lambda: calls == [True, "other"])
