"""Toasts: a moment's notice from the capsule (e.g. a dictation copied, not pasted), in a small card beside it with a
pointer at it, that doesn't take focus and goes by itself; a desktop notification if the capsule isn't on screen.
Desktop notifications: without buttons they go by themselves; with buttons they stay; each is forgotten once
closed."""
import threading
import time

from gi.repository import Gio, GLib

from conftest import needs_session
from dictate import osio
from harness.client import eventually

pytestmark = needs_session


def copied_not_pasted(app, speech="a thought cut short"):
    """Dictate, then press another key with Ctrl+Win: a toast says it was copied, not pasted."""
    mark = app.mark()
    app.send("say", text=speech)
    app.send("keys", down=["ctrl", "meta"])
    app.wait_for("recording", after=mark)
    app.send("keys", down=["right"], up=["right"])
    app.send("keys", up=["meta", "ctrl"])
    return mark


def test_a_toast_points_at_the_capsule_without_taking_focus(start):
    app = start(refinements=[], settings={"refine": False})

    copied_not_pasted(app)

    eventually(lambda: app.send("toast")["open"])
    toast = app.send("toast")
    (x, y, w, h), (tx, ty) = toast["dot"], toast["tip"]
    assert x <= tx <= x + w  # the pointer's over (or under) the dot
    assert 0 < (ty - (y + h) if toast["side"] == "top" else y - ty) <= 8  # and just off it
    assert not toast["focus"]
    assert "Another key was pressed with Ctrl+Win" in " ".join(app.read("Copied, not pasted"))


def test_a_toast_goes_by_itself(start):
    app = start(refinements=[], settings={"refine": False}, env={"DICTATE_TEST_TOAST": "1"})
    copied_not_pasted(app)
    eventually(lambda: app.send("toast")["open"])

    eventually(lambda: not app.send("toast")["open"], timeout=4)
    assert "Copied, not pasted" not in app.send("windows")["titles"]


def test_without_the_capsule_on_screen_it_is_a_desktop_notification(start):
    app = start(refinements=[], settings={"refine": False})
    app.send("hide_icon")

    mark = copied_not_pasted(app)

    note = app.wait_for("notified", after=mark)
    assert note["title"] == "Copied, not pasted" and note["actions"] == []
    assert not app.send("toast")["open"]


class Notifications:
    """A stand-in for the desktop's notification service on the session bus: remembers each Notify call, and can
    close a notification or click its button, as the desktop would."""
    XML = """<node><interface name="org.freedesktop.Notifications">
      <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/>
        <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
        <arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
        <arg type="u" direction="out"/></method>
      <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
      <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    </interface></node>"""

    def __init__(self):
        self.calls, self.ready = [], threading.Event()
        self.loop = GLib.MainLoop(GLib.MainContext.new())
        threading.Thread(target=self.serve, daemon=True).start()
        assert self.ready.wait(5)

    def serve(self):
        ctx = self.loop.get_context()
        ctx.push_thread_default()
        self.bus = Gio.DBusConnection.new_for_address_sync(
            Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION), Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        info = Gio.DBusNodeInfo.new_for_xml(self.XML).interfaces[0]
        osio.dbus_register(self.bus, "/org/freedesktop/Notifications", info, self.call)
        Gio.bus_own_name_on_connection(self.bus, "org.freedesktop.Notifications", Gio.BusNameOwnerFlags.REPLACE
                                       | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
                                       lambda *_: self.ready.set(), None)
        self.loop.run()

    def call(self, conn, sender, path, interface, method, params, invocation):
        self.calls.append(params.unpack())
        invocation.return_value(GLib.Variant("(u)", (len(self.calls),)))

    def emit(self, signal, args):
        self.bus.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications", signal, args)

    def click(self, nid, key):
        self.emit("ActionInvoked", GLib.Variant("(us)", (nid, key)))
        self.emit("NotificationClosed", GLib.Variant("(uu)", (nid, 2)))

    def close(self, nid):
        self.emit("NotificationClosed", GLib.Variant("(uu)", (nid, 1)))


def settle(seconds=0.3):
    """Let signals reach this thread's main context (where osio listens)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.01)


def test_desktop_notifications_go_by_themselves_unless_they_ask_something():
    service = Notifications()

    osio.notify("Copied, not pasted", "It's on the clipboard.")
    osio.notify("Still transcribing", "Stop it?", [("stop", "Stop now")])

    (*_, quiet_timeout), (*_, asking_timeout) = service.calls
    assert quiet_timeout == osio.NOTICE > 0
    assert asking_timeout == 0  # (stays until it's answered)


def test_a_button_works_once_and_closed_notifications_are_forgotten():
    service = Notifications()
    clicked = []
    for i in range(3):
        osio.notify(f"Asking {i}", "Stop it?", [("stop", "Stop now")], clicked.append)
    first, second, third = range(len(service.calls) - 2, len(service.calls) + 1)

    service.close(first)
    service.click(second, "stop")
    service.click(second, "stop")  # (again: it's gone)
    service.close(third)
    settle()

    assert clicked == ["stop"]
    assert osio._notified == {}  # nothing kept for notifications that are gone
