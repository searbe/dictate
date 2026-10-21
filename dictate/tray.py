"""System tray icon, showing the floating icon's artwork and the very same right-click menu.

KDE/Linux: a StatusNotifierItem over D-Bus, with the GTK menu mirrored by dbusmenu.
Windows: GTK's built-in status icon. macOS: none (GTK 3 has no menu-bar icon); the floating icon remains."""
import os, sys
import gi
from . import osio
from gi.repository import Gdk, Gio, GLib, Gtk

SIZES = (32, 64)  # pixel sizes offered to the tray


class Tray:
    """menu: the Gtk.Menu to show; render(px): a cairo ARGB32 surface of the current icon;
    before_show(): called before the menu opens (to refresh dynamic items)."""

    def __init__(self, menu, render, before_show):
        self.menu, self.render, self.before_show = menu, render, before_show
        if sys.platform.startswith("linux"):
            self._sni_start()
        elif sys.platform == "win32":
            self.icon = Gtk.StatusIcon(tooltip_text="Dictate: hold Ctrl+Win to dictate")
            for signal in ("activate", "popup-menu"):  # left or right click: show the menu
                self.icon.connect(signal, self._win_popup)
            self.update()

    def update(self):
        """Redraw the tray icon (call when the dictation state changes)."""
        if sys.platform.startswith("linux") and hasattr(self, "conn"):
            self.pixmaps = None  # re-rendered when Plasma next asks for the image
            self.conn.emit_signal(None, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewIcon", None)
        elif sys.platform == "win32":
            surface = self.render(SIZES[0])
            self.icon.set_from_pixbuf(Gdk.pixbuf_get_from_surface(surface, 0, 0, SIZES[0], SIZES[0]))

    # --- Windows ---
    def _win_popup(self, icon, button=1, time=None):
        self.before_show()
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button,
                        Gtk.get_current_event_time() if time is None else time)

    # --- KDE StatusNotifierItem ---
    XML = """<node><interface name="org.kde.StatusNotifierItem">
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="IconName" type="s" access="read"/><property name="IconPixmap" type="a(iiay)" access="read"/>
<property name="ToolTip" type="(sa(iiay)ss)" access="read"/><property name="ItemIsMenu" type="b" access="read"/>
<property name="Menu" type="o" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewStatus"><arg type="s"/></signal>
</interface></node>"""

    def _sni_start(self):
        try:
            gi.require_version("Dbusmenu", "0.4")
            gi.require_version("DbusmenuGtk3", "0.4")
            from gi.repository import Dbusmenu, DbusmenuGtk3
        except (ValueError, ImportError):
            return print("tray: dbusmenu not available, no tray icon")
        self.dbusmenu = Dbusmenu.Server.new("/MenuBar")  # mirrors the GTK menu, kept in sync as it changes
        root = DbusmenuGtk3.gtk_parse_menu_structure(self.menu)
        root.connect("about-to-show", lambda *_: self.before_show() or True)
        self.dbusmenu.set_root(root)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        Gio.bus_own_name(Gio.BusType.SESSION, self.name, 0, self._sni_bus, None, None)

    def _sni_bus(self, conn, _name):
        self.conn = conn
        osio.dbus_register(conn, "/StatusNotifierItem", Gio.DBusNodeInfo.new_for_xml(self.XML).interfaces[0],
                           lambda *a: a[-1].return_value(None), self._sni_property)
        # register with the tray host now, and again whenever Plasma restarts
        Gio.bus_watch_name(Gio.BusType.SESSION, "org.kde.StatusNotifierWatcher", 0, self._sni_register, None)

    def _sni_register(self, conn, *_):
        conn.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                  "RegisterStatusNotifierItem", GLib.Variant("(s)", (self.name,)), None, 0, -1, None, None)

    def _sni_property(self, conn, sender, path, iface, prop):
        # Plasma asks for each property separately (~9 calls per icon change), on our GTK thread:
        # render the image only when it's asked for, once per state, or the red dot can't repaint
        if prop == "IconPixmap":
            if getattr(self, "pixmaps", None) is None:
                self.pixmaps = GLib.Variant.new_array(None, [self._pixmap(px) for px in SIZES])
            return self.pixmaps
        return {
            "Category": GLib.Variant("s", "ApplicationStatus"), "Id": GLib.Variant("s", "dictate"),
            "Title": GLib.Variant("s", "Dictate"), "Status": GLib.Variant("s", "Active"), "IconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "Dictate", "Hold Ctrl+Win to dictate")),
            "ItemIsMenu": GLib.Variant("b", True),  # any click opens the menu
            "Menu": GLib.Variant("o", "/MenuBar"),
        }.get(prop)

    def _pixmap(self, px):
        """The icon as SNI wants it: (w, h, non-premultiplied ARGB32 bytes in network byte order).
        The bytes are wrapped in one go: GLib.Variant("ay", ...) would build them one by one (~30 ms)."""
        import numpy as np
        surface = self.render(px)
        surface.flush()
        bgra = np.frombuffer(surface.get_data(), np.uint8).reshape(px, px, 4).astype(np.float32)  # cairo: BGRA, premultiplied
        alpha = bgra[..., 3:4]
        bgra[..., :3] = np.where(alpha > 0, bgra[..., :3] * 255 / np.maximum(alpha, 1), 0)
        argb = GLib.Bytes.new(bgra[..., ::-1].astype(np.uint8).tobytes())
        return GLib.Variant.new_tuple(GLib.Variant("i", px), GLib.Variant("i", px),
                                      GLib.Variant.new_from_bytes(GLib.VariantType("ay"), argb, True))
