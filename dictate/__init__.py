"""Dictate: hold Ctrl+Win (Ctrl+Cmd on a Mac) to record, release to transcribe and paste.

The dictation pipeline is in app.py, the capsule in capsule.py, the hotkey, recording and paste in osio.py,
transcription in stt.py, clean-up / restyling in refine.py, the Dictate window in hub.py (and
transcripts_page.py), its HUDs in huds.py, and how all of it looks in design.py (docs/design/DESIGN.md).
"""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the project folder: .venv, bin/ and models/ live here
DATA = Path(os.environ.get("DICTATE_DATA") or ROOT / "data")  # history, settings, styles (the tests use their own)


def bootstrap(gui=True):
    """Call before importing anything else from the package: switches to our .venv if launched with the
    system Python, and points GTK at the right display / runtime. gui: on Windows, run without a console."""
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
    if gui:
        import gi
        gi.require_version("Gtk", "3.0")  # before any module imports Gtk or Gdk, which would otherwise pick 4
        gi.require_version("Gdk", "3.0")
