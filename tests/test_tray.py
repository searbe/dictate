"""The system tray icon, seen from the tray's side: the D-Bus StatusNotifierItem protocol that Plasma speaks."""
import sys, threading, time
import pytest
from conftest import needs_session

pytestmark = [needs_session, pytest.mark.skipif(not sys.platform.startswith("linux"), reason="KDE tray protocol")]
WATCHER = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method></interface></node>"""


@pytest.fixture
def tray():
    """A stand-in for Plasma's tray: owns the watcher name and records which items register."""
    from gi.repository import Gio, GLib
    ctx = GLib.MainContext.new()
    loop, items, ready, connections = GLib.MainLoop.new(ctx, False), [], threading.Event(), []

    def serve():
        ctx.push_thread_default()
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION)
        bus = Gio.DBusConnection.new_for_address_sync(  # its own: gone when the test ends
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        connections.append(bus)
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER).interfaces[0]

        def call(conn, sender, path, iface, method, params, invocation):
            items.append((sender, params.unpack()[0]))
            invocation.return_value(None)
        bus.register_object("/StatusNotifierWatcher", info, call, None, None)
        Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher", 0, lambda *_: ready.set(), None)
        loop.run()

    threading.Thread(target=serve, daemon=True).start()
    ready.wait(5)
    yield items
    loop.quit()
    connections[0].close_sync(None)


def item_call(service, iface, method, args, signature):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    path = "/StatusNotifierItem" if iface.startswith("org.freedesktop.DBus.Properties") else "/MenuBar"
    return bus.call_sync(service, path, iface, method, GLib.Variant(signature, args), None, 0, 5000, None).unpack()


def prop(service, name):
    return item_call(service, "org.freedesktop.DBus.Properties", "Get", ("org.kde.StatusNotifierItem", name), "(ss)")[0]


def registered(items, timeout=10):
    deadline = time.monotonic() + timeout
    while not items:
        assert time.monotonic() < deadline, "Dictate never registered a tray icon"
        time.sleep(0.05)
    return items[0][1]


def labels(node):
    _id, props, children = node
    return [props.get("label", "")] + [l for c in children for l in labels(c)]


def redness(pixmaps):
    """How much of the largest icon image is strongly red (ARGB bytes)."""
    w, h, data = max(pixmaps, key=lambda p: p[0])
    px = [data[i:i + 4] for i in range(0, len(data), 4)]
    return sum(1 for a, r, g, b in px if a > 128 and r > 180 and g < 120) / len(px)


def test_dictate_shows_a_tray_icon_with_the_same_menu(start, tray):
    start(styles=[])
    service = registered(tray)

    assert prop(service, "Title") == "Dictate"
    _rev, layout = item_call(service, "com.canonical.dbusmenu", "GetLayout", (0, -1, ["label"]), "(iias)")
    assert {"Refine text", "Default style", "History", "Refinement styles…", "Run at startup", "Quit"} <= set(labels(layout))


def test_the_tray_icon_turns_red_while_recording(start, tray):
    app = start(styles=[])
    service = registered(tray)
    idle = redness(prop(service, "IconPixmap"))

    app.send("keys", down=["ctrl", "meta"])
    app.wait_for("icon", state="rec")
    recording = redness(prop(service, "IconPixmap"))
    app.send("keys", up=["meta", "ctrl"])

    assert idle < 0.01 and recording > 0.2


def test_the_tray_icons_tooltip_says_how_long_it_has_been_transcribing_and_the_topic(start, tray, model):
    import json
    model.rules({"prompt": "live list of the topics", "text": "budget", "reply": json.dumps(
        {"topics": [{"topic": 0, "title": "The budget", "said": "Speaker 1 asked about it.", "lines": [1]}]})})
    app = start(styles=[])
    service = registered(tray)
    assert prop(service, "ToolTip")[3] == "Hold Ctrl+Win to dictate"

    app.ctrl_win_win()
    app.wait_window("Transcripts")
    app.hear("Shall we look at the budget?")

    deadline = time.monotonic() + 5
    while prop(service, "ToolTip")[3] != "Transcribing · under a minute\nNow: The budget":
        assert time.monotonic() < deadline, prop(service, "ToolTip")[3]
        time.sleep(0.1)
    app.click("Pause", "Transcripts")
    deadline = time.monotonic() + 5
    while not prop(service, "ToolTip")[3].startswith("Transcribing, paused · under a minute"):
        assert time.monotonic() < deadline, prop(service, "ToolTip")[3]
        time.sleep(0.1)
