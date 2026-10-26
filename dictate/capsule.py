"""The capsule: Dictate's one always-present control (docs/design/DESIGN.md, "The capsule"). A 36 px dot while
idle; while you dictate it grows into a capsule with a recording dot, a live level meter and a timer; while the
model works, the meter dims and three dots pulse; while a call is transcribed, it shows a recording dot, how long
it's been going and the topic now.

It's drawn in cairo inside one fixed, transparent window (resizing a window every frame jitters under XWayland),
growing away from the nearer screen edge; only the capsule's own shape takes clicks, the rest passes through.
It can be dragged anywhere; the app is told about clicks (interact()) and tells the capsule what's happening
(update())."""
import math
import os
import time

import cairo
from gi.repository import Gdk, GLib, Gtk

from . import design as d
from . import transcript

H, DOT = 36, 36  # the capsule's height, and the idle dot's size
PAD = 10  # around the capsule, for its shadow
W = 280  # the window: room for the widest capsule
BARS, BAR_W, BAR_GAP = 11, 3, 2
PROFILE = (0.35, 0.5, 0.65, 0.8, 0.92, 1.0, 0.92, 0.8, 0.65, 0.5, 0.35)  # the middle bars taller


def wav_level(path):
    """How loud the last 50 ms of a WAV being recorded are, 0–1 (roughly −55 to −15 dBFS)."""
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size < 44 + 1600:
                return 0.0
            f.seek(max(44, size - 1600) // 2 * 2)
            data = f.read(1600)
    except OSError:
        return 0.0
    import numpy as np
    samples = np.frombuffer(data[:len(data) // 2 * 2], np.int16).astype(np.float32) / 32768
    rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
    return min(max((20 * math.log10(max(rms, 1e-6)) + 55) / 40, 0.0), 1.0)


class Capsule:
    """win: the window to show and move. update(state, session, since, level) says what's happening: state
    "idle", "rec" (dictating) or "busy" (the model's working); session: the transcript being recorded, or
    None; since: when the dictation started; level(): the microphone's loudness now."""

    def __init__(self):
        self.win = Gtk.Window(type_hint=Gdk.WindowTypeHint.UTILITY, decorated=False, skip_taskbar_hint=True,
                              skip_pager_hint=True, app_paintable=True, resizable=False)
        visual = self.win.get_screen().get_rgba_visual()
        if visual:
            self.win.set_visual(visual)  # per-pixel transparency
        d.grayscale(self.win)
        self.win.set_keep_above(True)
        self.win.set_size_request(W, H + 2 * PAD)
        self.win.connect("draw", lambda w, cr: self.draw(cr))
        self.win.connect("size-allocate", lambda *_: self.shape())
        self.state, self.session, self.since, self.level = "idle", None, None, lambda: 0.0
        self.hovered, self.anchor = False, "left"
        self.flashing = False  # the paused dot lit up (see flash)
        self.width = self.start_width = self.target = float(DOT)
        self.morph_at, self.loud, self.t0, self.ticking = 0.0, 0.0, time.monotonic(), None
        d.on_scheme.append(self.win.queue_draw)

    # --- what it shows ---
    def flash(self, on):
        """Light the paused dot up (on) or not: flashed on and off to draw attention to something."""
        self.flashing = on
        self.win.queue_draw()

    def update(self, state, session=None, since=None, level=None):
        self.state, self.session, self.since = state, session, since
        if level:
            self.level = level
        self.retarget()
        self.tick_on()

    def hover(self, on):
        self.hovered = on
        self.win.queue_draw()

    def retarget(self):
        target = self.wanted()
        if abs(target - self.target) > 0.5:
            self.start_width, self.target, self.morph_at = self.width, target, time.monotonic()
            if not d.animations():
                self.width = target
            self.shape()

    def wanted(self):
        """The capsule's width for what it's showing now."""
        if self.state in ("rec", "busy"):
            return 12 + 8 + 8 + BARS * BAR_W + (BARS - 1) * BAR_GAP + 10 + self.measure("0:00") + 14
        if self.session:
            return min(16 + 8 + 8 + self.measure(self.session_words()) + 16, W - 2 * PAD)
        return float(DOT)

    def measure(self, words):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        return float(d.layout(cairo.Context(surface), words, "caption", tabular=True)[1])

    def session_words(self):
        clock, topic = transcript.clock(self.session.now()), self.session.topics.current()
        return f"{clock} · {topic}" if topic else clock

    def tick_on(self):
        """Redraw every frame while something moves (a morph, the meter, the pulse), every second while a call's
        timer runs, and not at all while idle."""
        if not self.ticking and (self.state != "idle" or self.session or self.width != self.target):
            self.ticking = GLib.timeout_add(16, self.tick)

    def tick(self):
        now = time.monotonic()
        if self.width != self.target:
            p = (now - self.morph_at) / d.MORPH
            self.width = self.target if p >= 1 else self.start_width + (self.target - self.start_width) * d.ease(p)
            self.shape()
        if self.state == "rec":
            level = self.level()
            self.loud = level if level > self.loud else self.loud * 0.85 + level * 0.15  # quick to rise, slow to fall
        elif self.session and self.state == "idle":
            self.retarget()  # the timer's text grows
        self.win.queue_draw()
        moving = self.width != self.target or self.state != "idle"
        if moving:
            return True
        if self.session:  # once a second is enough for a timer
            self.ticking = GLib.timeout_add(1000 - int(now * 1000) % 1000, self.tick)
            return False
        self.ticking = None
        return False

    # --- moving it, and clicks on it ---
    DRAG = 3  # px the pointer moves with the button down before it's a drag, not a click
    SETTLE = 500  # ms after the last move before it counts as put down

    def interact(self, on_click, on_menu, on_settled):
        """Take the window's events: drag to move it (on_settled() once it's been put down), click it
        (on_click()), or right-click it (on_menu(event))."""
        self.on_click, self.on_menu, self.on_settled = on_click, on_menu, on_settled
        self.pressed = None  # where the left button went down, until it's a drag or a click
        self.settling = None
        w = self.win
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                     | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                     | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        w.connect("button-press-event", self._press)
        w.connect("motion-notify-event", self._motion)
        w.connect("button-release-event", self._release)
        w.connect("configure-event", self._moved)
        w.connect("enter-notify-event", lambda *_: self.hover(True))
        w.connect("leave-notify-event", lambda *_: self.hover(False))

    def _press(self, w, ev):
        if ev.button == 1:
            self.pressed = (ev.x_root, ev.y_root)
        elif ev.button == 3:
            self.on_menu(ev)
        return True

    def _motion(self, w, ev):
        if self.pressed and max(abs(ev.x_root - self.pressed[0]), abs(ev.y_root - self.pressed[1])) > self.DRAG:
            x, y = self.pressed
            self.pressed = None
            w.begin_move_drag(1, int(x), int(y), ev.time)
        return True

    def _release(self, w, ev):
        if ev.button == 1 and self.pressed:  # didn't move: a click
            self.pressed = None
            self.on_click()
        return True

    def _moved(self, *_):
        if self.settling:
            GLib.source_remove(self.settling)
        self.settling = GLib.timeout_add(self.SETTLE, self._settled)

    def _settled(self):
        """Put down after a move: grow away from the nearer edge, and say where it is now."""
        self.settling = None
        self.settle()
        self.on_settled()
        return False

    # --- where it is ---
    def place(self, pos, anchor):
        """Put it where it was left: the window at pos, its dot at the anchor end."""
        self.win.move(*pos)
        self.anchor = anchor

    def position(self):
        return list(self.win.get_position())

    def on_screen(self):
        """Whether it's shown, on one of the screens."""
        if not self.win.get_mapped():
            return False
        x, y, w, h = self.dot_rect()
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            area = display.get_monitor(i).get_geometry()
            if area.x <= x + w // 2 < area.x + area.width and area.y <= y + h // 2 < area.y + area.height:
                return True
        return False

    def left(self):
        """The capsule's x within the window."""
        return PAD if self.anchor == "left" else W - PAD - self.width

    def dot_rect(self):
        """Where the dot (the capsule's fixed end) is on screen: (x, y, w, h)."""
        x, y = self.win.get_position()
        return (x + (PAD if self.anchor == "left" else W - PAD - DOT), y + PAD, DOT, H)

    def rect(self):
        """Where the whole capsule is on screen now."""
        x, y = self.win.get_position()
        return (int(x + self.left()), y + PAD, int(self.width), H)

    def settle(self):
        """After a move: grow away from the nearer screen edge (the dot stays where it was put)."""
        x, y = self.win.get_position()
        dx, dy, dw, dh = self.dot_rect()
        area = Gdk.Display.get_default().get_monitor_at_point(dx + dw // 2, dy + dh // 2).get_geometry()
        want = "right" if dx + dw / 2 > area.x + area.width / 2 else "left"
        if want != self.anchor:
            self.anchor = want
            self.win.move(x - (W - 2 * PAD - DOT) if want == "right" else x + (W - 2 * PAD - DOT), y)
            self.shape()
            self.win.queue_draw()
            return True
        return False

    def shape(self):
        """Only the capsule takes clicks; the rest of the window passes them through."""
        gdk = self.win.get_window()
        if gdk:
            region = cairo.Region(cairo.RectangleInt(int(self.left()), PAD, math.ceil(self.width), H))
            gdk.input_shape_combine_region(region, 0, 0)

    # --- drawing ---
    def draw(self, cr, clear=True):
        """Draw the capsule (on a cleared window, unless not clear: e.g. over a picture of a desktop)."""
        if clear:
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
        x, y, w = self.left(), PAD, self.width
        t = time.monotonic() - self.t0
        for i in range(6):  # a soft shadow
            spread = 6 - i
            d.round_rect(cr, x - spread / 2, y + 3 - spread / 2 + 1, w + spread, H + spread, (H + spread) / 2)
            cr.set_source_rgba(0, 0, 0, 0.035 if d.scheme == "dark" else 0.02)
            cr.fill()
        body = d.rgba("surface-1", 0.94)
        d.round_rect(cr, x + 0.5, y + 0.5, w - 1, H - 1, (H - 1) / 2)
        cr.set_source_rgba(body.red, body.green, body.blue, body.alpha)
        cr.fill_preserve()
        line = d.rgba("line-strong")
        cr.set_source_rgba(line.red, line.green, line.blue, line.alpha)
        cr.set_line_width(1)
        cr.stroke()
        if self.hovered and self.state == "idle":
            d.round_rect(cr, x + 0.5, y + 0.5, w - 1, H - 1, (H - 1) / 2)
            hi = d.rgba("text", 0.05)
            cr.set_source_rgba(hi.red, hi.green, hi.blue, hi.alpha)
            cr.fill()

        grown = min(max((w - DOT) / max(self.target - DOT, 1), 0), 1) if self.target > DOT else 0
        cy = y + H / 2
        if self.state in ("rec", "busy"):
            self.draw_dot(cr, x + 16, cy, "record", 1.0 if self.state == "rec" else 0.4)
            bx = x + 28
            for i in range(BARS):
                wobble = 0.7 + 0.3 * math.sin(t * 7 + i * 1.3)
                level = self.loud if self.state == "rec" else 0.15
                h = 4 + 16 * level * PROFILE[i] * wobble
                d.round_rect(cr, bx + i * (BAR_W + BAR_GAP), cy - h / 2, BAR_W, h, BAR_W / 2)
                c = d.rgba("text", (0.85 if self.state == "rec" else 0.3) * grown)
                cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
                cr.fill()
            tx = bx + BARS * BAR_W + (BARS - 1) * BAR_GAP + 10
            if self.state == "rec":
                seconds = int(time.time() - self.since) if self.since else 0
                self.draw_words(cr, f"{seconds // 60}:{seconds % 60:02d}", tx, cy, "text-2", grown)
            else:
                for k in range(3):  # three dots, pulsing in turn
                    a = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / d.PULSE * 1.5 - k * 0.9))
                    c = d.rgba("text-2", a * grown)
                    cr.arc(tx + 4 + k * 8, cy, 1.8, 0, 2 * math.pi)
                    cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
                    cr.fill()
        elif self.session:
            self.draw_dot(cr, x + 18, cy, "text-3" if self.session.paused and not self.flashing else "record", 1.0)
            cr.save()
            cr.rectangle(x, y, w - 14, H)
            cr.clip()
            self.draw_words(cr, self.session_words(), x + 30, cy, "text-2", grown)
            cr.restore()
        else:
            ic = d.rgba("text" if self.hovered else "text-2")
            d.draw_icon(cr, "mic", x + (DOT - 16) / 2, y + (H - 16) / 2, 16, ic)

    def draw_dot(self, cr, cx, cy, colour, alpha):
        c = d.rgba(colour, alpha)
        cr.arc(cx, cy, 4, 0, 2 * math.pi)
        cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
        cr.fill()

    def draw_words(self, cr, words, x, cy, colour, alpha):
        lay, w, h = d.layout(cr, words, "caption", tabular=True)
        c = d.rgba(colour, alpha)
        cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
        cr.move_to(x, cy - h / 2)
        from gi.repository import PangoCairo
        PangoCairo.show_layout(cr, lay)

    def picture(self):
        """The capsule as it looks now, as a pixbuf (e.g. to show in the still-transcribing reminder)."""
        width, height = int(self.left() + self.width + PAD), H + 2 * PAD
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        self.draw(cairo.Context(surface))
        return Gdk.pixbuf_get_from_surface(surface, int(self.left() - PAD), 0, int(self.width + 2 * PAD), height)


def draw_tray(cr, px, state, session, flashing=False):
    """The tray icon: the app icon while idle; a dot with the mic, red while recording, ringed in the accent while
    transcribing a call (grey while it's paused, red when flashing)."""
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    if state == "idle" and not session:
        return d.draw_app_icon(cr, px)
    cr.scale(px / 32, px / 32)
    fill = d.rgba("record") if state == "rec" else d.rgba("surface-3") if d.scheme == "dark" else d.rgba("#2a2c33")
    cr.arc(16, 16, 13, 0, 2 * math.pi)
    cr.set_source_rgba(fill.red, fill.green, fill.blue, 1)
    cr.fill()
    if session:
        ring = d.rgba("record") if flashing else d.rgba("text-3") if session.paused else d.rgba("accent")
        cr.arc(16, 16, 14.5, 0, 2 * math.pi)
        cr.set_source_rgba(ring.red, ring.green, ring.blue, 1)
        cr.set_line_width(3)
        cr.stroke()
    if state == "busy":
        a = time.monotonic() * 5
        acc = d.rgba("accent")
        cr.arc(16, 16, 10, a, a + 2.4)
        cr.set_source_rgba(acc.red, acc.green, acc.blue, 1)
        cr.set_line_width(2.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()
    d.draw_icon(cr, "mic", 8, 8, 16, Gdk.RGBA(1, 1, 1, 0.95))
