"""Runs the real Dictate app with only its hardware swapped out, driven by a test over stdin/stdout.

Replaced: the keyboard (osio.Hotkey), the microphone (osio.Recorder), the speech model (stt), the virtual
keyboard that pastes (osio.Paster) and the speaker (osio.Player). The test also swaps llama-server for
fake_llama.py (DICTATE_TEST_LLAMA). Everything in between is the real app, so the tests describe what a
user sees, and keep passing however the inside is reorganised.

With DICTATE_TEST_SPEECH (a 16 kHz WAV), the microphone "records" that file every time and the real speech
model transcribes it; DICTATE_TEST_SPEAKERS does the same for what the speakers play (transcribe mode).
With DICTATE_TEST_LLAMA pointing at the real llama-server, refining is real too.

Commands arrive as JSON lines on stdin (see COMMANDS); each gets a "done" reply with the same id.
Events go to stdout as lines starting with "EVENT "; anything else on stdout is the app's own log.
"""
import json, os, sys, time, wave, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import dictate  # noqa: E402
dictate.bootstrap()
from dictate import osio, refine, stt, summary, topics, voices  # noqa: E402
import numpy as np  # noqa: E402
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


def event(kind, **fields):
    print("EVENT " + json.dumps({"type": kind, **fields}), flush=True)


# --- the hardware, as test doubles ---
speech = {"next": None}  # what the user will say during the next recording
heard = {}  # recording path -> what was said during it
ears = []  # the transcriptions following a recording as it's made (transcribe mode), newest last


class Hotkey:
    """The real Ctrl+Win state machine (osio.Chord), fed by the test instead of a keyboard."""

    def __init__(self, callback, on_again=None, on_other=lambda: None, letters=None):
        self.chord = osio.Chord(callback, on_again, on_other, letters)

    def start(self):
        pass


REAL_SPEECH, REAL_SPEAKERS = os.environ.get("DICTATE_TEST_SPEECH"), os.environ.get("DICTATE_TEST_SPEAKERS")


class Recorder:
    def start(self, path, speakers=False, on_audio=None, echo_cancel=False):
        real = REAL_SPEAKERS if speakers else REAL_SPEECH
        audio = bytes(3200)  # what the microphone or speakers give: silence, or the speech
        if real:
            with wave.open(real) as sample:
                audio = sample.readframes(sample.getnframes())
        if on_audio:  # streamed as it's recorded (transcribe mode)
            if ears:  # (not when it's the real stt.Live)
                ears[-1].source = "speakers" if speakers else "mic"  # the stt.Live it streams to: the newest
            on_audio(audio)
            Path(path).write_bytes(b"recording")
        else:
            with wave.open(path, "wb") as w:  # a real recording, as the microphone would leave
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
                w.writeframes(audio)
            heard[path], speech["next"] = speech["next"], None
        event("recording", path=path, speakers=speakers, echo_cancel=echo_cancel)

    def stop(self):
        event("recording_stopped")


class Live:
    def __init__(self, path=None, on_text=None, on_preview=None, pause=None):
        self.path, self.on_text, self.on_preview, self.t0 = path, on_text, on_preview, time.monotonic()
        if on_text:
            ears.append(self)

    def push(self, samples):
        pass

    def finish(self):
        if self in ears:
            ears.remove(self)  # the recording has stopped: nothing more is heard
        return heard.get(self.path) or ""


class Paster:
    def paste(self, terminal):
        event("pasted", terminal=terminal, text=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text())
        return False

    def type_text(self, text):
        event("typed", text=text)


class Player:
    def __init__(self, on_playing=lambda playing: None):
        self.done, self.on_playing = None, on_playing

    def play(self, path, on_done):
        self.stop()
        self.done = on_done
        self.on_playing(True)
        event("playing", path=path)

    def stop(self):
        if self.done:
            GLib.idle_add(self.done)
            self.done = None
            self.on_playing(False)
            event("stopped")


notifications = []  # on_action of each desktop notification shown, newest last


def notify(title, body, actions=(), on_action=lambda key: None, image=None):
    notifications.append(on_action)
    event("notified", title=title, body=body, actions=[label for _, label in actions], image=bool(image))


osio.Hotkey, osio.Recorder, osio.Paster, osio.Player, osio.notify = Hotkey, Recorder, Paster, Player, notify
if not REAL_SPEECH and not REAL_SPEAKERS:
    stt.Live, stt.load = Live, lambda: None
    stt.transcribe = lambda path: heard.get(str(path)) or ""
refine.SERVER = Path(os.environ["DICTATE_TEST_LLAMA"])


def fake_voiceprint(name, size=192):
    """The same voiceprint for the same voice, unrelated ones for different voices."""
    v = np.random.default_rng(zlib.crc32(name.encode())).standard_normal(size).astype(np.float32)
    return v / np.linalg.norm(v)


_voiceprint, _narrowband = voices.voiceprint, voices.narrowband  # the real ones, for real recordings
voices.voiceprint = lambda s: fake_voiceprint(s[1]) if isinstance(s, tuple) else _voiceprint(s)
voices.narrowband = lambda s=None, power=None: False if isinstance(s, tuple) else _narrowband(s, power)
voices.available = lambda: not os.environ.get("DICTATE_TEST_NO_VOICES")
refine.IDLE = float(os.environ.get("DICTATE_TEST_IDLE", refine.IDLE))
topics.TICK, topics.EVERY, topics.MOST, topics.FREE_FOR = 0.2, 0, 0, 0.6  # topics as soon as anything is said
topics.MERGE = 0.5
summary.EVERY, summary.WORDS = 0.5, 1  # a summary as soon as anything's said
gpu = {"state": os.environ.get("DICTATE_TEST_GPU", "free")}  # the graphics card: "free", "busy" or "none"
refine.gpu_ok = lambda: gpu["state"] == "free"
refine.gpu_present = lambda: gpu["state"] != "none"

from dictate import app as dictate_app  # noqa: E402  (after the swaps, like the real launcher's order)

dictate_app.QUIET = float(os.environ.get("DICTATE_TEST_QUIET", dictate_app.QUIET))
dictate_app.QUIET_CHECK = 0.2

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
    """What can be read: labels, entries' text, and icon buttons' tooltips (what hovering one says)."""
    out = []
    for w in descendants(root):
        if isinstance(w, Gtk.Label) and shown(w) and w.get_text():
            out.append(w.get_text())
        elif isinstance(w, Gtk.Entry) and shown(w) and w.get_text():
            out.append(w.get_text())
        elif isinstance(w, Gtk.Button) and shown(w) and w.get_tooltip_text() and not any(
                isinstance(k, Gtk.Label) for k in descendants(w)):
            out.append(w.get_tooltip_text())
    return out


def labelled(root, kind, label):
    """Shown widgets of kind whose own text, tooltip, or any text inside them, is label."""
    return [w for w in descendants(root) if isinstance(w, kind) and shown(w) and
            ((hasattr(w, "get_label") and w.get_label() == label) or w.get_tooltip_text() == label
             or label in texts(w))]


def field(root, name):
    """An input by what the user sees next to it: its placeholder, the grid label above it, or "text" for
    the big text box."""
    if name == "text":
        return next(w for w in descendants(root) if isinstance(w, Gtk.TextView) and shown(w))
    for w in descendants(root):
        if isinstance(w, Gtk.Entry) and shown(w) and w.get_placeholder_text() == name:
            return w
        if getattr(w, "label", None) == name and shown(w):  # design.field: the label above its input
            return next(k for k in descendants(w) if isinstance(k, (Gtk.Entry, Gtk.TextView)))
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


def now():
    """Seconds into the transcript being recorded, by its own clock (as a real recording's samples are)."""
    return time.monotonic() - app.session.t0


def cmd_hear(text, source, length=1.0, voice="them"):
    """Someone (voice) says text through the speakers (source "speakers"), or into the microphone ("mic"),
    while Dictate is transcribing: it's heard as a stretch of speech that has just ended."""
    for live in reversed(ears):
        if getattr(live, "source", None) == source:
            end = now()
            return live.on_text(end - length, end, text, ("voice", voice))  # may have begun before the recording


def cmd_hear_so_far(text, source, length=1.0):
    """Someone is saying text through the speakers (or into the microphone, "mic") and hasn't paused yet."""
    for live in reversed(ears):
        if getattr(live, "source", None) == source:
            return live.on_preview(now() - length, text)


def cmd_gpu(state):
    """The graphics card becomes "free" or "busy" (a game starts or stops)."""
    gpu["state"] = state


def cmd_hide_icon():
    """The floating icon isn't on screen."""
    app.win.hide()


def cmd_notification(button):
    """Click a button on the newest desktop notification."""
    notifications.pop()(button)


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


def cmd_opacity(label, window_title=None, hover=None):
    """How opaque the button with this label (or tooltip) looks, 0–1, with its list row hovered (hover=True) or
    not (False): what CSS makes of it, as a user sees it."""
    button = labelled(window(window_title), Gtk.Button, label)[0]
    row = next((w for w in iter(lambda b=[button]: (b.append(b[-1].get_parent()), b[-1])[1], None)
                if isinstance(w, Gtk.ListBoxRow)), None)
    if row and hover is not None:
        (row.set_state_flags if hover else row.unset_state_flags)(Gtk.StateFlags.PRELIGHT, *(() if not hover else (False,)))
        for _ in range(30):  # (let the fade finish)
            pump()
            time.sleep(0.01)
    opacity, w = 1.0, button
    while w:
        ctx = w.get_style_context()
        opacity *= ctx.get_property("opacity", ctx.get_state())
        w = w.get_parent()
    return {"opacity": opacity}


def cmd_has_icon(label, window_title=None):
    """Whether the icon button with this tooltip shows its icon."""
    button = labelled(window(window_title), Gtk.Button, label)[0]
    return {"shown": bool(button.get_child() and button.get_child().get_mapped())}


def cmd_resize(width, height, window_title=None):
    """Make the window this size, as dragging its edge would."""
    window(window_title).resize(width, height)
    for _ in range(30):
        pump()
        time.sleep(0.01)


def cmd_panes(window_title=None):
    """Where the split panes' dividers are: [{"x", "y", "height", "position"}] on screen, left to right."""
    out = []
    for w in descendants(window(window_title)):
        if isinstance(w, Gtk.Paned) and shown(w):
            gdk = w.get_window()
            ox, oy = gdk.get_origin()[1:]
            a = w.get_allocation()
            out.append({"x": ox + a.x + w.get_position(), "y": oy + a.y, "height": a.height, "position": w.get_position()})
    return {"panes": sorted(out, key=lambda p: p["x"])}


def cmd_click_icon():
    """Click the floating icon (press and release without moving)."""
    for kind in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
        ev = Gdk.Event.new(kind)
        ev.button, ev.window, ev.x_root, ev.y_root = 1, app.win.get_window(), 120.0, 120.0
        app.win.emit("button-press-event" if kind == Gdk.EventType.BUTTON_PRESS else "button-release-event", ev)


def cmd_click(label, window_title=None, nth=0):
    """Click the button with this label (or tooltip); or flip the switch of the setting with this title."""
    buttons = labelled(window(window_title), Gtk.Button, label)
    if buttons:
        return buttons[nth].clicked()
    rows = [w for w in descendants(window(window_title)) if isinstance(w, Gtk.Box) and shown(w)
            and label in texts(w) and any(isinstance(k, Gtk.Switch) for k in descendants(w))]
    switch = next(k for k in descendants(rows[-1]) if isinstance(k, Gtk.Switch))
    switch.set_active(not switch.get_active())


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


def cmd_choose(option, window_title=None, setting=None):
    """Choose option in the dropdown (of the setting with this title, if there are several)."""
    root = window(window_title)
    if setting:
        root = [w for w in descendants(root) if isinstance(w, Gtk.Box) and shown(w) and setting in texts(w)
                and any(isinstance(k, Gtk.ComboBoxText) for k in descendants(w))][-1]
    combo = next(w for w in descendants(root) if isinstance(w, Gtk.ComboBoxText) and shown(w))
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
