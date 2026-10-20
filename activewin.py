"""Knows which window has focus (KDE Wayland): a tiny KWin script, loaded at runtime, reports each
activation over D-Bus. Dictate's own windows are ignored, so this stays the app you were typing in."""
import atexit, os
from pathlib import Path
from gi.repository import Gio, GLib

SCRIPT, PLUGIN = Path(__file__).parent / "kwin_active.js", "dictate-active"
XML = """<node><interface name="local.dictate"><method name="Active">
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="i" direction="in"/></method></interface></node>"""
current = {"cls": "", "title": ""}


def describe(app):
    """e.g. 'general - Acme - Slack (Slack)'; empty if unknown."""
    return f"{app['title']} ({app['cls']})" if app["cls"] else ""


def _on_call(conn, sender, path, iface, method, params, invocation):
    cls, title, pid = params.unpack()
    if pid != os.getpid():
        current.update(cls=cls, title=title)
    invocation.return_value(None)


def _on_bus(conn, _name):
    conn.register_object_with_closures2("/", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], _on_call, None, None)
    try:
        kwin = Gio.DBusProxy.new_sync(conn, 0, None, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", None)
        if kwin.isScriptLoaded("(s)", PLUGIN):  # left over from a crash
            kwin.unloadScript("(s)", PLUGIN)
        kwin.loadScript("(ss)", str(SCRIPT), PLUGIN)
        kwin.start()
        atexit.register(lambda: kwin.unloadScript("(s)", PLUGIN))
    except GLib.Error as err:  # not KDE, or KWin scripting unavailable: just no app context
        print("activewin: unavailable:", err.message)


def start():
    Gio.bus_own_name(Gio.BusType.SESSION, "local.dictate", 0, _on_bus, None, None)
