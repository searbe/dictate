"""A stand-in for another app's window (e.g. a browser): python window.py <app class> <title>.

Prints "focused" each time it gets keyboard focus. Lines on stdin: "title <new title>" renames it
(like a browser switching tabs), "focus" asks for focus back, "quit" closes it."""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk

GLib.set_prgname(sys.argv[1])  # becomes the window's class, which KWin reports
win = Gtk.Window(title=sys.argv[2], default_width=400, default_height=300)
win.connect("focus-in-event", lambda *_: print("focused", flush=True) or False)
win.connect("destroy", Gtk.main_quit)


def on_input(source, _):
    line = source.readline()
    if not line or line.strip() == "quit":
        Gtk.main_quit()
        return False
    cmd, _, arg = line.rstrip("\n").partition(" ")
    if cmd == "title":
        win.set_title(arg)
        print("titled", flush=True)
    elif cmd == "focus":
        win.present()
    return True


GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, on_input)
win.show_all()
win.present()
Gtk.main()
