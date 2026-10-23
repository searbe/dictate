"""Dictate: hold Ctrl+Win (Ctrl+Cmd on a Mac) to record, release to transcribe and paste.

app.py ties it together: the dictation pipeline and transcribe mode. The modules are listed, by what they do,
in docs/TECHNICAL.md ("Code"); each explains itself at the top.
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the project folder: .venv, bin/ and models/ live here
DATA = Path(os.environ.get("DICTATE_DATA") or ROOT / "data")  # history, settings, refinements (the tests use their own)


def setup_logging(level=logging.INFO):
    """Log to stdout, a line each, flushed at once (stdout is buffered when launched from the desktop):
    e.g. "14:02:07.315 app: quitting: Quit chosen from the menu". On Linux, see journalctl."""
    if sys.stdout is None:  # Windows' pythonw: no console to log to
        logging.basicConfig(handlers=[logging.NullHandler()], force=True)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(module)s: %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=level, handlers=[handler], force=True)


def bootstrap(gui=True):
    """Call before importing anything else from the package: switches to our .venv if launched with the
    system Python, points GTK at the right display / runtime, and sets up logging. gui: on Windows, run
    without a console."""
    venv_py = ROOT / (".venv/Scripts/" + ("pythonw.exe" if gui else "python.exe") if sys.platform == "win32"
                      else ".venv/bin/python")
    if sys.prefix == sys.base_prefix and venv_py.exists():  # launched with system python → use ours
        os.execv(venv_py, [str(venv_py), *sys.argv])
    if sys.platform.startswith("linux"):
        os.environ["GDK_BACKEND"] = "x11"  # KDE Wayland: XWayland lets the icon stay on top and be positioned
    elif sys.platform == "win32":  # GTK runtime unpacked into ./gtk by setup-windows.ps1
        gtk = ROOT / "gtk"
        os.add_dll_directory(gtk / "bin")
        os.environ["PATH"] = str(gtk / "bin") + os.pathsep + os.environ["PATH"]
        os.environ["GI_TYPELIB_PATH"] = str(gtk / "lib/girepository-1.0")
        os.environ["XDG_DATA_DIRS"] = str(gtk / "share")
    setup_logging()
    if gui:
        import gi
        gi.require_version("Gtk", "3.0")  # before any module imports Gtk or Gdk, which would otherwise pick 4
        gi.require_version("Gdk", "3.0")
        from gi.repository import GLib
        GLib.set_prgname("dictate")  # its windows' class: matches dictate.desktop, for the desktop's icon and name
        GLib.set_application_name("Dictate")
