"""Knows when your keyboard is controlling another computer (Synergy, Deskflow, Input Leap...),
so the hotkey can be ignored then: Dictate reads keys straight from the keyboard, so it sees Ctrl+Win
even while they're being forwarded to a remote screen.

Two sources, because in testing neither caught every switch on its own:
- KWin (KDE Wayland): these apps capture input through KWin, which broadcasts each capture on D-Bus
  (activated = input is going elsewhere, deactivated = it's back), but not for every switch. A capture only
  counts once it has lasted SETTLE seconds: when Synergy can't reach the other computer it grabs and
  releases every few milliseconds.
- Synergy's log records every switch ('switch from "a" to "b"'); on each hotkey press we read the lines
  added since last time. It could go stale if Synergy died while away, so KWin's "back" resets it.
Remote if either says so."""
import configparser, json, re, sys, time
from pathlib import Path

SETTLE = 0.2
_active = {}  # KWin capture object path -> when it was activated


def start():
    """Listen for KWin's input-capture signals (Linux only; harmless if KWin isn't there)."""
    if not sys.platform.startswith("linux"):
        return
    from gi.repository import Gio

    def on_signal(conn, sender, path, iface, signal, params):
        global _screen
        if signal == "activated":
            _active.setdefault(path, time.monotonic())
        else:  # deactivated or disabled: input is definitely back here, whatever the log last said
            _active.pop(path, None)
            _synergy_log_says_remote()  # consume pending lines first, so they can't override this
            _screen = _local

    Gio.bus_get_sync(Gio.BusType.SESSION).signal_subscribe(
        "org.kde.KWin", "org.kde.KWin.EIS.InputCapture", None, None, None, Gio.DBusSignalFlags.NONE, on_signal)


def on_remote_screen():
    """True if the keyboard is currently driving another computer."""
    kwin = any(time.monotonic() - since >= SETTLE for since in _active.values())
    return _synergy_log_says_remote() or kwin


# --- fallback: Synergy's log ---
ROOTS = [Path.home() / ".var/app/com.symless.synergy", Path.home()]  # Flatpak, then a native install
SWITCH = re.compile(r'switch from "[^"]*" to "([^"]*)"')
_log, _local, _pos, _screen = None, None, 0, None


def _find():
    global _log, _local
    for root in ROOTS:
        log, conf = root / ".local/state/Synergy/synergy.jsonl", root / ".config/Synergy/synergy-core.conf"
        if not conf.exists():
            conf = root / "config/Synergy/synergy-core.conf"  # Flatpak keeps config here
        if log.exists() and conf.exists():
            parser = configparser.ConfigParser()
            parser.read(conf)
            _log, _local = log, parser.get("core", "computerName", fallback=None)
            return


def _synergy_log_says_remote():
    global _pos, _screen
    if _log is None:
        _find()
    if not _log or not _local:
        return False
    try:
        with open(_log, "rb") as f:
            if f.seek(0, 2) < _pos:  # the log was rotated
                _pos = 0
            f.seek(_pos)
            new = f.read()
            new = new[:new.rfind(b"\n") + 1]  # complete lines only; a half-written one is read next time
            _pos += len(new)
    except OSError:
        return False
    for line in new.decode(errors="replace").splitlines():
        try:
            msg = json.loads(line).get("msg", "")
        except ValueError:
            continue
        if match := SWITCH.search(msg):
            _screen = match.group(1)
        elif msg.startswith("starting core"):  # Synergy (re)started: the keyboard is back on this computer
            _screen = _local
    return _screen is not None and _screen != _local
