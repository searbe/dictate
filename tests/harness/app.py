"""Runs the real Dictate app with only its hardware swapped out, driven by a test over stdin/stdout.

Replaced: the keyboard (osio.Hotkey), the microphone (osio.Recorder), the speech model (stt), the virtual
keyboard that pastes (osio.Paster) and the speaker (osio.Player). The test also swaps llama-server for
fake_llama.py (DICTATE_TEST_LLAMA). Everything in between is the real app, so the tests describe what a
user sees, and keep passing however the inside is reorganised.

With DICTATE_TEST_SPEECH (a 16 kHz WAV), the microphone "records" that file every time and the real speech
model transcribes it; with DICTATE_TEST_LLAMA pointing at the real llama-server, refining is real too.

Commands arrive as JSON lines on stdin (see COMMANDS); each gets a "done" reply with the same id.
Events go to stdout as lines starting with "EVENT "; anything else on stdout is the app's own log.
"""
import json, os, sys, time, wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import dictate  # noqa: E402
dictate.bootstrap()
from dictate import osio, refine, stt  # noqa: E402
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


def event(kind, **fields):
    print("EVENT " + json.dumps({"type": kind, **fields}), flush=True)


# --- the hardware, as test doubles ---
speech = {"next": None}  # what the user will say during the next recording
heard = {}  # recording path -> what was said during it


class Hotkey:
    """The real Ctrl+Win state machine (osio.Chord), fed by the test instead of a keyboard."""

    def __init__(self, callback):
        self.chord = osio.Chord(callback)

    def start(self):
        pass


REAL_SPEECH = os.environ.get("DICTATE_TEST_SPEECH")


class Recorder:
    def start(self, path):
        with wave.open(path, "wb") as w:  # a real recording, as the microphone would leave: silent, or the speech
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            if REAL_SPEECH:
                with wave.open(REAL_SPEECH) as sample:
                    w.writeframes(sample.readframes(sample.getnframes()))
            else:
                w.writeframes(bytes(3200))
        heard[path], speech["next"] = speech["next"], None
        event("recording", path=path)

    def stop(self):
        event("recording_stopped")


class Live:
    def __init__(self, path):
        self.path = path

    def finish(self):
        return heard.get(self.path) or ""


class Paster:
    def paste(self, terminal):
        event("pasted", terminal=terminal, text=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text())
        return False

    def type_text(self, text):
        event("typed", text=text)


class Player:
    def __init__(self):
        self.done = None

    def play(self, path, on_done):
        self.stop()
        self.done = on_done
        event("playing", path=path)

    def stop(self):
        if self.done:
            GLib.idle_add(self.done)
            self.done = None
            event("stopped")


osio.Hotkey, osio.Recorder, osio.Paster, osio.Player = Hotkey, Recorder, Paster, Player
if not REAL_SPEECH:
    stt.Live, stt.load = Live, lambda: None
    stt.transcribe = lambda path: heard.get(str(path)) or ""
refine.SERVER = Path(os.environ["DICTATE_TEST_LLAMA"])
refine.IDLE = float(os.environ.get("DICTATE_TEST_IDLE", refine.IDLE))

from dictate import app as dictate_app  # noqa: E402  (after the swaps, like the real launcher's order)

_set_state = dictate_app.App.set_state
dictate_app.App.set_state = lambda self, s: (_set_state(self, s), event("icon", state=s))[0]  # what the icon shows


# --- finding things on screen, the way a user would: by window title and visible text ---
def pump():
    for _ in range(3):
        while Gtk.events_pending():
            Gtk.main_iteration()


def windows():
    return [w for w in Gtk.Window.list_toplevels() if w.get_mapped()]


def window(title):
    """The open window with this title; None means the open dialog (e.g. a confirmation)."""
    for w in windows():
        if (isinstance(w, Gtk.Dialog) if title is None else w.get_title() == title):
            return w
    raise LookupError(f"no window {title!r} open: {[w.get_title() for w in windows()]}")


def descendants(widget):
    """widget and everything inside it, including parts GTK builds itself (header bars, button labels)."""
    yield widget
    if isinstance(widget, Gtk.Container):
        kids = []
        widget.forall(kids.append)
        for kid in kids:
            yield from descendants(kid)


def shown(widget):
    return widget.get_mapped()


def texts(root):
    out = []
    for w in descendants(root):
        if isinstance(w, Gtk.Label) and shown(w) and w.get_text():
            out.append(w.get_text())
        elif isinstance(w, Gtk.Entry) and shown(w) and w.get_text():
            out.append(w.get_text())
    return out


def labelled(root, kind, label):
    """Shown widgets of kind whose own text, or any text inside them, is label."""
    return [w for w in descendants(root) if isinstance(w, kind) and shown(w) and
            ((hasattr(w, "get_label") and w.get_label() == label) or label in texts(w))]


def field(root, name):
    """An input by what the user sees next to it: its placeholder, the grid label above it, or "text" for
    the big text box."""
    if name == "text":
        return next(w for w in descendants(root) if isinstance(w, Gtk.TextView) and shown(w))
    for w in descendants(root):
        if isinstance(w, Gtk.Entry) and shown(w) and w.get_placeholder_text() == name:
            return w
        if isinstance(w, Gtk.Grid):
            for kid in w.get_children():
                if isinstance(kid, Gtk.Label) and kid.get_text() == name:
                    left, top = w.child_get(kid, "left-attach", "top-attach")
                    return w.get_child_at(left, top + 1)
    raise LookupError(f"no field {name!r}")


def menu_root():
    """The floating icon's right-click menu, opened as a user would. Retried for a moment: straight after
    choosing an item, GTK is still closing the previous menu and closes the new one too."""
    for _ in range(20):
        ev = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        ev.button, ev.window, ev.time = 3, app.win.get_window(), Gtk.get_current_event_time()
        app.win.emit("button-press-event", ev)
        pump()
        roots = [m for m in open_menus() if not m.get_attach_widget()]  # submenus hang off an item
        if roots:
            return roots[0]
        time.sleep(0.05)
    raise LookupError("right-click opened no menu")


def open_menus():
    return [w.get_child() for w in Gtk.Window.list_toplevels() if isinstance(w.get_child(), Gtk.Menu) and w.get_mapped()]


def close_menus():
    for menu in open_menus():
        menu.popdown()
    pump()


def menu_item(menu, label):
    items = [m for m in menu.get_children() if isinstance(m, Gtk.MenuItem) and m.get_label()]
    for item in items:
        if item.get_label() == label:
            return item
    raise LookupError(f"no menu item {label!r}: {[m.get_label() for m in items]}")


# --- commands ---
def cmd_say(text):
    speech["next"] = text


def cmd_keys(down=(), up=()):
    for name in down:
        app.hotkey.chord.key(name, name, True)
    for name in up:
        app.hotkey.chord.key(name, name, False)


def cmd_menu(path):
    menu = menu_root()
    for label in path[:-1]:
        menu = menu_item(menu, label).get_submenu()
    menu_item(menu, path[-1]).activate()
    close_menus()


def cmd_menu_items(path=()):
    menu = menu_root()
    for label in path:
        menu = menu_item(menu, label).get_submenu()
    items = [{"label": m.get_label(), **({"ticked": m.get_active()} if isinstance(m, Gtk.CheckMenuItem) else {})}
             for m in menu.get_children() if isinstance(m, Gtk.MenuItem) and m.get_label()]
    close_menus()
    return {"items": items}


def cmd_windows():
    return {"titles": [w.get_title() for w in windows() if w.get_title()]}


def cmd_read(window_title=None):
    return {"texts": texts(window(window_title))}


def cmd_click(label, window_title=None, nth=0):
    labelled(window(window_title), Gtk.Button, label)[nth].clicked()


def cmd_fill(name, text, window_title=None):
    w = field(window(window_title), name)
    if isinstance(w, Gtk.TextView):
        w.get_buffer().set_text(text)
    else:
        w.set_text(text)


def cmd_field(name, window_title=None):
    w = field(window(window_title), name)
    return {"text": w.get_buffer().props.text if isinstance(w, Gtk.TextView) else w.get_text()}


def cmd_select(row, window_title=None):
    lb = next(w for w in descendants(window(window_title)) if isinstance(w, Gtk.ListBox) and labelled(w, Gtk.ListBoxRow, row))
    lb.select_row(labelled(lb, Gtk.ListBoxRow, row)[0])


def cmd_choose(option, window_title=None):
    combo = next(w for w in descendants(window(window_title)) if isinstance(w, Gtk.ComboBoxText) and shown(w))
    model = [r[0] for r in combo.get_model()]
    combo.set_active(model.index(option))


def cmd_press(key, window_title=None):
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.keyval = Gdk.keyval_from_name(key)
    window(window_title).emit("key-press-event", ev)


def cmd_close(window_title):
    window(window_title).close()


def cmd_clipboard():
    return {"text": Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()}


COMMANDS = {name[4:]: f for name, f in globals().items() if name.startswith("cmd_")}
buffer = b""


def on_input(fd, condition):
    global buffer
    chunk = os.read(fd, 65536)
    if not chunk:
        app.quit("the test closed stdin")
        return False
    buffer += chunk
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        GLib.idle_add(run, json.loads(line))  # not here: a command may open a dialog that waits for the next one
    return True


def run(msg):
    cid, name, replied = msg.pop("id"), msg.pop("cmd"), []

    def reply(**result):
        if not replied:
            replied.append(True)
            event("done", id=cid, **result)

    if name == "click":  # a click that opens a confirmation dialog only returns once it's answered
        GLib.timeout_add(200, lambda: reply() or False)
    try:
        result = COMMANDS[name](**msg) or {}
        pump()
        reply(**result)
    except Exception as err:  # report it to the test rather than dying
        reply(error=f"{type(err).__name__}: {err}")
    return False


app = dictate_app.App()
GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, on_input)
GLib.idle_add(lambda: event("ready", pid=os.getpid()))
app.run()
