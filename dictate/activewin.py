"""Knows which window has focus, so text can be refined for (and pasted into) the right app.

KDE (Linux): a tiny KWin script, loaded at runtime, reports each activation over D-Bus.
Windows: asks the OS for the foreground window. macOS: asks for the frontmost app.
Dictate's own windows are ignored, so this stays the app you were typing in."""
import atexit
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import osio

log = logging.getLogger(__name__)



@dataclass(frozen=True)
class Window:
    """Where a dictation's text goes: an app here (its window class and title), or another computer (remote:
    your keyboard is driving it through Synergy or similar, so its apps can't be seen)."""
    cls: str = ""
    title: str = ""
    remote: bool = False

    def describe(self) -> str:
        """e.g. 'general - Acme - Slack (Slack)', for the model's context; empty if unknown."""
        return f"{self.title} ({self.cls})" if self.cls else ""

    def matches(self) -> str:
        """What per-app refinements are matched against."""
        return f"{self.cls} {self.title}"


OTHER_COMPUTER = Window(remote=True)
current = {"cls": "", "title": ""}
on_switch = []  # callbacks run when another app gets focus (KDE only)


if sys.platform.startswith("linux"):
    from gi.repository import Gio, GLib

    SCRIPT, PLUGIN = Path(__file__).parent / "kwin_active.js", "dictate-active"
    XML = """<node><interface name="local.dictate"><method name="Active">
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="i" direction="in"/><arg type="b" direction="in"/>
</method></interface></node>"""

    def snapshot() -> Window:
        return Window(**current)

    def _on_call(conn, sender, path, iface, method, params, invocation):
        cls, title, pid, switched = params.unpack()  # switched: focus moved here, not just a new title
        if pid != os.getpid():
            current.update(cls=cls, title=title)
            for callback in on_switch if switched else ():
                callback()
        invocation.return_value(None)

    def _on_bus(conn, _name):
        osio.dbus_register(conn, "/", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], _on_call)
        try:
            kwin = Gio.DBusProxy.new_sync(conn, 0, None, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", None)
            if kwin.isScriptLoaded("(s)", PLUGIN):  # left over from a crash
                kwin.unloadScript("(s)", PLUGIN)
            kwin.loadScript("(ss)", str(SCRIPT), PLUGIN)
            kwin.start()
            atexit.register(lambda: kwin.unloadScript("(s)", PLUGIN))
        except GLib.Error as err:  # not KDE, or KWin scripting unavailable: just no app context
            log.info("unavailable: %s", err.message)

    def start():
        Gio.bus_own_name(Gio.BusType.SESSION, "local.dictate", 0, _on_bus, None, None)

else:
    def start():
        pass

    def snapshot():
        """Ask the OS which app is in front; keep the previous answer if it's one of our own windows."""
        try:
            pid, cls, title = _frontmost()
            if pid != os.getpid():
                current.update(cls=cls, title=title)
        except Exception as err:  # no app context is fine; never break dictation over it
            log.info("unavailable: %s", err)
        return Window(**current)

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        def _frontmost():
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            user32.GetWindowTextW(hwnd, title, len(title))
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe, size = ctypes.create_unicode_buffer(260), wintypes.DWORD(260)
            proc = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            kernel32.QueryFullProcessImageNameW(proc, 0, exe, ctypes.byref(size))
            kernel32.CloseHandle(proc)
            return pid.value, Path(exe.value).stem, title.value  # e.g. "slack", "general - Acme - Slack"

    else:  # macOS: AppKit and Quartz come with pynput's dependencies
        import Quartz
        from AppKit import NSWorkspace

        def _frontmost():
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            pid, title = app.processIdentifier(), ""
            # window titles are only visible with the Screen Recording permission; without it we just get the app
            windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
            for w in windows or []:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
                    title = w.get("kCGWindowName") or ""
                    break
            return pid, app.localizedName(), title
