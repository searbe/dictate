"""Knows when your keyboard is controlling another computer (Synergy, Deskflow, Input Leap...),
so the hotkey can be ignored then: Dictate reads keys straight from the keyboard, so it sees Ctrl+Win
even while they're being forwarded to a remote screen.

Two sources, because in testing neither caught every switch on its own:
- KWin (KDE Wayland): these apps capture input through KWin, which broadcasts each capture on D-Bus
  (activated = input is going elsewhere, deactivated = it's back), but not for every switch. A capture only
  counts once it has lasted SETTLE seconds: when Synergy can't reach the other computer it grabs and
  releases every few milliseconds.
- Synergy's log records every switch ('switch from "a" to "b"', or 'jump from' when it brings the keyboard
  home because the other computer dropped off); on each hotkey press we read the lines
  added since last time. It could go stale if Synergy died while away, so KWin's "back" resets it.
Remote if either says so."""
import configparser
import json
import re
import sys
import time
from pathlib import Path

SETTLE = 0.2  # seconds a KWin input capture must last to count
ROOTS = [Path.home() / ".var/app/com.symless.synergy", Path.home()]  # Flatpak, then a native install
SWITCH = re.compile(r'(?:switch|jump) from "[^"]*" to "([^"]*)"')  # jump: back home when the other computer drops off


class SynergyLog:
    """Which screen Synergy last switched the keyboard to, from its log (only the lines added since last time
    are read)."""

    def __init__(self, roots=ROOTS):
        self.roots = roots
        self.path = None  # the log, once found
        self.local = None  # this computer's name in Synergy's config
        self.pos = 0  # how far the log has been read
        self.screen = None  # the screen the keyboard is on, as far as the log says

    def _find(self):
        for root in self.roots:
            log, conf = root / ".local/state/Synergy/synergy.jsonl", root / ".config/Synergy/synergy-core.conf"
            if not conf.exists():
                conf = root / "config/Synergy/synergy-core.conf"  # Flatpak keeps config here
            if log.exists() and conf.exists():
                parser = configparser.ConfigParser()
                parser.read(conf)
                self.path, self.local = log, parser.get("core", "computerName", fallback=None)
                return

    def remote(self):
        """Whether the log says the keyboard is on another computer now."""
        if self.path is None:
            self._find()
        if not self.path or not self.local:
            return False
        try:
            with open(self.path, "rb") as f:
                if f.seek(0, 2) < self.pos:  # the log was rotated
                    self.pos = 0
                f.seek(self.pos)
                new = f.read()
                new = new[:new.rfind(b"\n") + 1]  # complete lines only; a half-written one is read next time
                self.pos += len(new)
        except OSError:
            return False
        for line in new.decode(errors="replace").splitlines():
            try:
                msg = json.loads(line).get("msg", "")
            except ValueError:
                continue
            if match := SWITCH.search(msg):
                self.screen = match.group(1)
            elif msg.startswith("starting core"):  # Synergy (re)started: the keyboard is back on this computer
                self.screen = self.local
        return self.screen is not None and self.screen != self.local

    def back_here(self):
        """Something else knows the keyboard is back here: lines not read yet can't say otherwise."""
        self.remote()
        self.screen = self.local


_synergy = SynergyLog()
_captures = {}  # KWin input capture object path -> when it was activated (monotonic)


def start():
    """Listen for KWin's input-capture signals (Linux only; harmless if KWin isn't there)."""
    if not sys.platform.startswith("linux"):
        return
    from gi.repository import Gio

    def on_signal(conn, sender, path, iface, signal, params):
        if signal == "activated":
            _captures.setdefault(path, time.monotonic())
        else:  # deactivated or disabled: input is definitely back here, whatever the log last said
            _captures.pop(path, None)
            _synergy.back_here()

    Gio.bus_get_sync(Gio.BusType.SESSION).signal_subscribe(
        "org.kde.KWin", "org.kde.KWin.EIS.InputCapture", None, None, None, Gio.DBusSignalFlags.NONE, on_signal)


def on_remote_screen():
    """True if the keyboard is currently driving another computer."""
    kwin = any(time.monotonic() - since >= SETTLE for since in _captures.values())
    return _synergy.remote() or kwin
