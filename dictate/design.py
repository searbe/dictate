"""Dictate's design system in code: the tokens of docs/design/DESIGN.md, the CSS made from them (dark or light,
following the desktop's preference, live), a small icon set drawn in cairo, and the components every surface is
built from. Use these names, never raw colours or sizes; add to DESIGN.md first."""
import math
from pathlib import Path
from string import Template

import cairo
import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

# --- tokens ---
SCHEMES = {
    "dark": {
        "bg": "#111214", "surface-1": "#17181b", "surface-2": "#1d1f23", "surface-3": "#25272c", "surface-4": "#2e3137",
        "raised": "#3a3d45",
        "line": "rgba(255,255,255,0.07)", "line-strong": "rgba(255,255,255,0.14)",
        "text": "#ececef", "text-2": "#a4a7b0", "text-3": "#6f727b",
        "accent": "#7c8cff", "accent-hover": "#96a3ff", "accent-weak": "rgba(124,140,255,0.16)", "on-accent": "#ffffff",
        "record": "#ff5a5f", "danger": "#ff7a7a", "danger-weak": "rgba(255,122,122,0.14)",
        "warning": "#ffb547", "warning-weak": "rgba(255,181,71,0.13)",
        "hud": "rgba(23,24,27,0.88)", "highlight": "rgba(255,255,255,0.06)", "shadow": "rgba(0,0,0,0.35)",
        "topics": ("#8b9bff", "#ffa95c", "#3fd6a8", "#ff7aa8", "#f2cf5b", "#b79bff", "#6fcfff", "#a6e36f"),
    },
    "light": {
        "bg": "#f6f6f7", "surface-1": "#efeff1", "surface-2": "#ffffff", "surface-3": "#e9e9ec", "surface-4": "#dfdfe4",
        "raised": "#ffffff",
        "line": "rgba(0,0,0,0.08)", "line-strong": "rgba(0,0,0,0.16)",
        "text": "#1b1c1f", "text-2": "#5d6068", "text-3": "#8b8e96",
        "accent": "#5b6cff", "accent-hover": "#4a5bf0", "accent-weak": "rgba(91,108,255,0.14)", "on-accent": "#ffffff",
        "record": "#e5484d", "danger": "#d93d42", "danger-weak": "rgba(217,61,66,0.10)",
        "warning": "#b86e00", "warning-weak": "rgba(184,110,0,0.14)",
        "hud": "rgba(250,250,251,0.90)", "highlight": "rgba(255,255,255,0.7)", "shadow": "rgba(0,0,0,0.18)",
        "topics": ("#4f5fe0", "#d46a12", "#0f9c74", "#d63f78", "#a88400", "#7e57e0", "#1c8fc7", "#5c9e1e"),
    },
}
FONT = '"Inter", "Noto Sans", "Cantarell", sans-serif'
TYPE = {  # px, weight
    "headline": (20, 600), "title": (15, 600), "body": (13, 400), "body-strong": (13, 600),
    "small": (12, 400), "caption": (11, 400),
}
SPACE = (4, 8, 12, 16, 24, 32)
R_XS, R_SM, R_MD, R_LG, R_FULL = 4, 6, 8, 12, 999
MORPH, FADE, HOVER, PULSE = 0.28, 0.18, 0.12, 1.2  # seconds

scheme = "dark"  # the desktop's preference, kept up to date by install()


def tok(name):
    return SCHEMES[scheme][name]


def topic_colour(n):
    """Topic colour number n (topics keep theirs)."""
    colours = SCHEMES[scheme]["topics"]
    return colours[n % len(colours)]


def rgba(colour, alpha=None):
    """A token's colour (or any CSS colour) as a Gdk.RGBA, optionally with alpha."""
    c = Gdk.RGBA()
    c.parse(tok(colour) if colour in SCHEMES[scheme] else colour)
    if alpha is not None:
        c.alpha = alpha
    return c


def ease(t):
    """cubic-bezier(0.2, 0, 0, 1) for t in 0..1 (the morph curve), solved numerically."""
    t = min(max(t, 0.0), 1.0)
    lo, hi = 0.0, 1.0
    for _ in range(20):  # find u where x(u) = t
        u = (lo + hi) / 2
        x = 3 * (1 - u) ** 2 * u * 0.2 + 3 * (1 - u) * u ** 2 * 0 + u ** 3
        lo, hi = (u, hi) if x < t else (lo, u)
    u = (lo + hi) / 2
    return 3 * (1 - u) ** 2 * u * 0 + 3 * (1 - u) * u ** 2 * 1 + u ** 3


def animations():
    return Gtk.Settings.get_default().get_property("gtk-enable-animations")


STYLE = Template(Path(__file__).with_name("style.css").read_text())


def css():
    """The stylesheet (style.css) for the scheme in use: its $tokens filled in from SCHEMES, TYPE and the radii."""
    t = SCHEMES[scheme]
    values = {name.replace("-", "_"): value for name, value in t.items() if name != "topics"}
    values |= {f"size_{k.replace('-', '_')}": f"font-size: {px}px; font-weight: {weight};"
               for k, (px, weight) in TYPE.items()}
    values |= {"font": FONT, "r_xs": R_XS, "r_sm": R_SM, "r_md": R_MD, "r_lg": R_LG, "r_full": R_FULL}
    values["topics"] = "".join(f".topic-edge-{i} {{ border-left: 3px solid {c}; }}\n.topic-text-{i} {{ color: {c}; }}\n"
                               for i, c in enumerate(t["topics"]))
    return STYLE.substitute(values)


_provider = None


def install():
    """Apply the design to the app's windows (and give them its icon); follow the desktop's light/dark preference
    from now on."""
    global _provider, scheme
    scheme = _desktop_scheme() or "dark"
    _apply()
    Gtk.Window.set_default_icon_list([app_icon(px) for px in ICON_SIZES])  # every window's (title bar, task bar)
    try:  # live changes (the freedesktop portal; KDE and GNOME have it)
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Settings", "SettingChanged",
                             "/org/freedesktop/portal/desktop", None, Gio.DBusSignalFlags.NONE, _changed)
    except GLib.Error:
        pass


def _apply():
    global _provider
    screen = Gdk.Screen.get_default()
    if _provider:
        Gtk.StyleContext.remove_provider_for_screen(screen, _provider)
    _provider = Gtk.CssProvider()
    _provider.load_from_data(css().encode())
    Gtk.StyleContext.add_provider_for_screen(screen, _provider, 600)
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", scheme == "dark")
    for listener in list(on_scheme):
        listener()


on_scheme = []  # called after the scheme changes (e.g. to redraw drawn things)


def _changed(conn, sender, path, iface, signal, params):
    global scheme
    namespace, key, value = params.unpack()
    if namespace == "org.freedesktop.appearance" and key == "color-scheme":
        new = {1: "dark", 2: "light"}.get(value, "dark")
        if new != scheme:
            scheme = new
            _apply()


def _desktop_scheme():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        reply = bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                              "org.freedesktop.portal.Settings", "Read",
                              GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                              None, Gio.DBusCallFlags.NONE, 500, None)
        value = reply.unpack()[0]
        while isinstance(value, GLib.Variant):
            value = value.unpack()
        return {1: "dark", 2: "light"}.get(value)
    except GLib.Error:
        return None


# --- icons ---
def _spokes(inner, outer, n=8):
    """The settings gear's teeth: n lines from radius inner to outer around (8, 8)."""
    out = []
    for k in range(n):
        a = k * math.pi / (n // 2)
        out.append(f"m {8 + inner * math.cos(a)!r} {8 + inner * math.sin(a)!r} "
                   f"l {8 + outer * math.cos(a)!r} {8 + outer * math.sin(a)!r}")
    return " ".join(out)


# Each icon on a 16×16 grid, as path commands: m x y (move), l x y (line), c x1 y1 x2 y2 x y (curve),
# a cx cy r start end (arc; angles in turns), r x y w h radius (rounded rectangle), n (new sub-path), z (close).
ICONS = {
    "mic": "n a 8 4.5 2.5 .5 0 l 10.5 7.5 a 8 7.5 2.5 0 .5 z n a 8 7.5 4.5 0 .5 m 8 12 l 8 14.5",
    "history": "n a 8 8 6 0 1 m 8 4.5 l 8 8 l 10.5 9.5",
    "transcript": "m 3 4 l 13 4 m 3 7 l 11 7 m 3 10 l 13 10 m 3 13 l 9 13",
    "refinements": "m 8 2 c 8.5 5.5 10.5 7.5 14 8 c 10.5 8.5 8.5 10.5 8 14 c 7.5 10.5 5.5 8.5 2 8 "
                   "c 5.5 7.5 7.5 5.5 8 2 z",
    "voices": "n a 8 5.5 2.75 0 1 m 2.75 14 c 3 10.5 5.5 9.5 8 9.5 c 10.5 9.5 13 10.5 13.25 14",
    "settings": f"n a 8 8 2.25 0 1 {_spokes(4.2, 6)} n a 8 8 4.2 0 1",
    "search": "n a 7 7 4.25 0 1 m 10.2 10.2 l 13.5 13.5",
    "copy": "r 5.5 5.5 8 8 1.75 m 3.5 10.5 l 3.5 4.25 c 3.5 3.5 3.5 2.5 4.5 2.5 l 10.5 2.5",
    "play": "m 5 3 l 13 8 l 5 13 z",
    "stop": "r 4 4 8 8 1.5",
    "pause": "m 5.5 3.5 l 5.5 12.5 m 10.5 3.5 l 10.5 12.5",
    "trash": "m 2.5 4.5 l 13.5 4.5 m 6 4.5 l 6 2.5 l 10 2.5 l 10 4.5 m 4 4.5 l 4.75 13.5 l 11.25 13.5 l 12 4.5",
    "undo": "m 5.5 3 l 2.5 6 l 5.5 9 m 2.5 6 l 9.5 6 c 12 6 13.5 7.5 13.5 9.75 c 13.5 12 12 13.5 9.5 13.5 l 6.5 13.5",
    "folder": "m 2 4 l 6 4 l 7.5 5.5 l 14 5.5 l 14 12.5 l 2 12.5 z",
    "open": "m 9 2.5 l 13.5 2.5 l 13.5 7 m 13.5 2.5 l 7.5 8.5 m 11.5 9.5 l 11.5 13.5 l 2.5 13.5 l 2.5 4.5 l 6.5 4.5",
    "plus": "m 8 3 l 8 13 m 3 8 l 13 8",
    "check": "m 3 8.5 l 6.5 12 l 13 4.5",
    "warning": "m 8 2.5 l 14 13 l 2 13 z m 8 6.5 l 8 9.25 m 8 11.25 l 8 11.3",
    "close": "m 4 4 l 12 12 m 12 4 l 4 12",
    "record": "n a 8 8 4 0 1",
}
_ARGS = {"m": 2, "l": 2, "c": 6, "a": 5, "r": 5, "n": 0, "z": 0}  # how many numbers each command takes


def _icon_paths(cr, name):
    """Draw icon name's path (ICONS); the caller strokes and fills it."""
    words = ICONS.get(name, "").split()
    i = 0
    while i < len(words):
        op, n = words[i], _ARGS[words[i]]
        args = [float(w) for w in words[i + 1:i + 1 + n]]
        i += 1 + n
        if op == "m":
            cr.move_to(*args)
        elif op == "l":
            cr.line_to(*args)
        elif op == "c":
            cr.curve_to(*args)
        elif op == "a":
            cx, cy, r, start, end = args
            cr.arc(cx, cy, r, start * 2 * math.pi, end * 2 * math.pi)
        elif op == "r":
            _round_rect(cr, *args)
        elif op == "n":
            cr.new_sub_path()
        else:
            cr.close_path()


FILLED = {"play", "stop", "record"}


def _round_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


round_rect = _round_rect


def draw_icon(cr, name, x, y, size, colour):
    """Draw icon name at (x, y), size px, in colour (a Gdk.RGBA)."""
    cr.save()
    cr.translate(x, y)
    cr.scale(size / 16, size / 16)
    cr.set_source_rgba(colour.red, colour.green, colour.blue, colour.alpha)
    cr.set_line_width(1.5)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.new_path()
    _icon_paths(cr, name)
    if name in FILLED:
        cr.fill_preserve()
    cr.stroke()
    cr.restore()


ICON_TOP, ICON_BOTTOM, ICON_DOT = "#33363d", "#16171a", "#ff5a5f"  # the app icon: charcoal, like the capsule; the
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)                        # same in light and dark


def draw_app_icon(cr, px):
    """Dictate's icon at px by px: a charcoal rounded square, lit along its top edge, with the white microphone
    and a red dot (the capsule as it looks dictating)."""
    pad = px * 0.06  # (room for the edge, as other app icons have)
    side, r = px - 2 * pad, (px - 2 * pad) * 0.24
    top, bottom = rgba(ICON_TOP), rgba(ICON_BOTTOM)
    fill = cairo.LinearGradient(0, pad, 0, px - pad)
    fill.add_color_stop_rgb(0, top.red, top.green, top.blue)
    fill.add_color_stop_rgb(1, bottom.red, bottom.green, bottom.blue)
    _round_rect(cr, pad, pad, side, side, r)
    cr.set_source(fill)
    cr.fill()
    _round_rect(cr, pad + 0.5, pad + 0.5, side - 1, side - 1, r - 0.5)  # its edge: lit at the top, so it shows on
    edge = cairo.LinearGradient(0, pad, 0, px - pad)                      # a dark panel too
    edge.add_color_stop_rgba(0, 1, 1, 1, 0.30)
    edge.add_color_stop_rgba(0.5, 1, 1, 1, 0.06)
    edge.add_color_stop_rgba(1, 1, 1, 1, 0.10)
    cr.set_source(edge)
    cr.set_line_width(1)
    cr.stroke()
    # the microphone, filled (an app icon reads better solid than outlined), on the 16-unit icon grid
    unit = side * 0.62 / 16
    cr.save()
    cr.translate((px - 16 * unit) / 2, (px - 16 * unit) / 2 + side * 0.01)
    cr.scale(unit, unit)
    cr.set_source_rgb(1, 1, 1)
    cr.new_sub_path()
    cr.arc(8, 4.5, 2.75, math.pi, 0)
    cr.arc(8, 7.25, 2.75, 0, math.pi)
    cr.close_path()
    cr.fill()
    cr.set_line_width(2.0 if px <= 24 else 1.6)  # (bolder when small, or it fades)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.new_sub_path()
    cr.arc(8, 7.5, 4.75, 0, math.pi)
    cr.move_to(8, 12.25)
    cr.line_to(8, 14.5)
    cr.stroke()
    dot = rgba(ICON_DOT)
    cr.arc(13.6, 2.6, 2.1 if px <= 24 else 1.7, 0, 2 * math.pi)  # (bigger when small, to be seen)
    cr.set_source_rgb(dot.red, dot.green, dot.blue)
    cr.fill()
    cr.restore()


ICON_FILE = Path(__file__).with_name("icon.png")  # the icon for launchers (dictate.desktop, Run at startup)


def save_app_icon(path=ICON_FILE, px=256):
    """Write the app icon to a PNG (docs/make_screenshots.py keeps ICON_FILE up to date)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    draw_app_icon(cairo.Context(surface), px)
    surface.write_to_png(str(path))
    return path


def app_icon(px):
    """The app icon as a pixbuf, px square."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    draw_app_icon(cairo.Context(surface), px)
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, px, px)


class Icon(Gtk.DrawingArea):
    """An icon from the set, in its widget's CSS colour (so it follows hover and state)."""

    def __init__(self, name, size=16):
        super().__init__(width_request=size, height_request=size, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.name, self.size = name, size
        self.connect("draw", self._draw)

    def set_icon(self, name):
        self.name = name
        self.queue_draw()

    def _draw(self, widget, cr):
        ctx = widget.get_style_context()
        draw_icon(cr, self.name, 0, 0, self.size, ctx.get_color(ctx.get_state()))


# --- components ---
def classes(widget, *names):
    for c in names:
        if c:
            widget.get_style_context().add_class(c)
    return widget


def text(label, kind="body", wrap=False, xalign=0.0, selectable=False, ellipsize=False, max_chars=-1, **kw):
    """A label in a type style: headline, title, body, strong, small or caption."""
    lab = Gtk.Label(label=label, xalign=xalign, wrap=wrap, selectable=selectable, max_width_chars=max_chars, **kw)
    if wrap:
        lab.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
    return classes(lab, kind)


def button(label, cb, kind="secondary", icon=None, keyhint=None, small=False, tooltip=None):
    """A button: kind primary, secondary, quiet or danger; an icon before the label; a key hint after it."""
    b = classes(Gtk.Button(tooltip_text=tooltip), "btn", kind if kind != "secondary" else None,
                "small" if small else None)
    box = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
    if icon:
        box.pack_start(Icon(icon), False, False, 0)
    b.text = Gtk.Label(label=label)
    box.pack_start(b.text, False, False, 0)
    if keyhint:
        box.pack_start(classes(Gtk.Label(label=keyhint), "keyhint"), False, False, 0)
    b.add(box)
    b.set_label_text = b.text.set_text
    b.connect("clicked", lambda _: cb())
    return b


def icon_button(icon, tooltip, cb, danger=False):
    """A 28×28 quiet button with an icon; tooltip names the action (and is how tests find it)."""
    b = classes(Gtk.Button(tooltip_text=tooltip), "btn", "icon", "danger" if danger else None)
    b.icon = Icon(icon)
    b.add(b.icon)
    b.connect("clicked", lambda _: cb())
    return b


def flash(btn, done, label, icon=None):
    """Show done on a button for a moment (e.g. "Copied"), then put it back."""
    if hasattr(btn, "text"):
        btn.text.set_text(done)
        GLib.timeout_add(1200, lambda: btn.text.set_text(label) and False)
    elif hasattr(btn, "icon"):
        btn.icon.set_icon("check")
        btn.set_tooltip_text(done)
        GLib.timeout_add(1200, lambda: (btn.icon.set_icon(icon), btn.set_tooltip_text(label)) and False)


def chip(label, accent=False):
    return classes(Gtk.Label(label=label), "chip", "accent" if accent else None)


def segmented(options, chosen, on_choose):
    """A segmented control: one button per option (label), chosen marked; on_choose(label) when another is
    clicked. .choose(label) marks another."""
    box = classes(Gtk.Box(spacing=2, homogeneous=True), "segmented")
    buttons = {}

    def choose(label):
        for name, b in buttons.items():
            (b.get_style_context().add_class if name == label else b.get_style_context().remove_class)("on")
    for label in options:
        b = buttons[label] = classes(Gtk.Button(label=label), "segment")
        b.connect("clicked", lambda _, lab=label: (choose(lab), on_choose(lab)))
        box.pack_start(b, True, True, 0)
    choose(chosen)
    box.choose = choose
    return box


def step_chip(label, cb, tooltip=None):
    """A chip that can be clicked (e.g. a dictation's step, to see what it did); on() marks it chosen."""
    b = classes(Gtk.Button(label=label, tooltip_text=tooltip, valign=Gtk.Align.CENTER), "chip")
    b.connect("clicked", lambda _: cb())
    b.on = lambda yes: (b.get_style_context().add_class if yes else b.get_style_context().remove_class)("on")
    return b


def diff_markup(before, after):
    """Pango markup of after, with what was taken out of before struck through in danger, and what was put in
    highlighted in the accent: a word at a time (spaces and punctuation are words too)."""
    import difflib
    import re
    from xml.sax.saxutils import escape
    words = lambda s: re.findall(r"\s+|[\w'’-]+|[^\w\s]", s)
    a, b = words(before), words(after)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape("".join(a[i1:i2])))
            continue
        gone, new = "".join(a[i1:i2]), "".join(b[j1:j2])
        if gone.strip():
            out.append(f'<span strikethrough="true" foreground="{tok("danger")}">{escape(gone)}</span>')
            if new.strip():
                out.append(" ")  # (so what replaced it doesn't run into it)
        if new.strip():
            out.append(f'<span background="{tok("accent")}" bgalpha="22%" foreground="{tok("text")}">'
                       f'{escape(new)}</span>')
        elif new:
            out.append(escape(new))
    return "".join(out)


REWRITE = 0.5  # words in common, as a share: below it, a step rewrote the text (show before and after)


def similarity(before, after):
    import difflib
    return difflib.SequenceMatcher(None, before.split(), after.split(), autojunk=False).ratio()


def step_card(title, before, after):
    """What one step did to some text: a heading, then after marked up against before (diff_markup); or, if the
    step rewrote it (word-by-word marks would be unreadable), before and after, one above the other."""
    card = classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "step")
    card.pack_start(classes(Gtk.Label(label=title, xalign=0), "caption", "label-strong"), False, False, 0)
    if before == after:
        card.pack_start(text("Nothing changed.", "small"), False, False, 0)
    elif similarity(before, after) < REWRITE:
        for label, words, kind in (("Before", before, "small"), ("After", after, "body")):
            card.pack_start(classes(Gtk.Label(label=label, xalign=0, margin_top=4), "caption"), False, False, 0)
            card.pack_start(text(words, kind, wrap=True, selectable=True), False, False, 0)
    else:
        words = text("", "body", wrap=True, selectable=True)
        words.set_markup(diff_markup(before, after))
        card.pack_start(words, False, False, 0)
    return card


def key_badge(key):
    return classes(Gtk.Label(label=key.upper(), valign=Gtk.Align.CENTER), "key")


def hairline(vertical=False):
    return classes(Gtk.Box(hexpand=not vertical, vexpand=vertical), "hairline")


def group_header(label):
    return classes(Gtk.Label(label=label, xalign=0), "group-header")


def field(label, widget, help=None):
    """A labelled input: (box, widget). The label is above, help under it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.pack_start(classes(Gtk.Label(label=label, xalign=0), "field-label"), False, False, 0)
    box.pack_start(widget, False, False, 0)
    if help:
        box.pack_start(text(help, "small", wrap=True), False, False, 0)
    box.label = label
    return box


def setting_row(title, description, control):
    """Title and description at left, the control at right."""
    row = classes(Gtk.Box(spacing=16), "setting")
    words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    words.pack_start(text(title, "body"), False, False, 0)
    if description:
        words.pack_start(text(description, "small", wrap=True, max_chars=60), False, False, 0)
    row.pack_start(words, True, True, 0)
    control.set_valign(Gtk.Align.CENTER)
    row.pack_end(control, False, False, 0)
    return row


def empty_state(icon, sentence, hint=None):
    box = classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER,
                          valign=Gtk.Align.CENTER, vexpand=True), "empty-state")
    ic = classes(Icon(icon, 32), "faint")
    box.pack_start(ic, False, False, 0)
    box.pack_start(text(sentence, "body", xalign=0.5, wrap=True, max_chars=50), False, False, 0)
    if hint:
        box.pack_start(text(hint, "small", xalign=0.5, wrap=True, max_chars=50), False, False, 0)
    box.sentence = sentence
    return box


def warning_strip(message):
    box = classes(Gtk.Box(spacing=8), "warning-strip")
    ic = Icon("warning")
    box.pack_start(ic, False, False, 0)
    box.pack_start(Gtk.Label(label=message, xalign=0, wrap=True, max_width_chars=40), True, True, 0)
    return box


def status_pill(label, paused=False):
    """● Recording · 12:34: a pill with a recording (or paused) dot."""
    box = classes(Gtk.Box(spacing=6), "pill")
    dot = classes(Gtk.Box(valign=Gtk.Align.CENTER), "status-dot", "paused" if paused else None)
    box.pack_start(dot, False, False, 0)
    box.text = classes(Gtk.Label(label=label), "tabular")
    box.pack_start(box.text, False, False, 0)
    return box


class Clamp(Gtk.Bin):
    """Its child at most maximum px wide, centred in whatever room there is; narrower if there's less (down to
    what the child needs). So a page reads well in a wide window and still fits a narrow one."""

    def __init__(self, child, maximum):
        super().__init__(hexpand=True)
        self.maximum = maximum
        self.add(child)

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_get_preferred_width(self):
        least, natural = self.get_child().get_preferred_width()
        return least, max(least, min(natural, self.maximum))

    def do_get_preferred_height_for_width(self, width):
        return self.get_child().get_preferred_height_for_width(min(width, self.maximum))

    def do_get_preferred_height(self):
        return self.get_child().get_preferred_height()

    def do_size_allocate(self, room):
        self.set_allocation(room)
        width = max(min(room.width, self.maximum), self.get_child().get_preferred_width()[0])
        box = Gdk.Rectangle()
        box.x, box.y, box.width, box.height = (room.x + max(0, (room.width - width) // 2), room.y,
                                               min(width, room.width), room.height)
        self.get_child().size_allocate(box)


def scrolled(child, h=False):
    s = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC if h else Gtk.PolicyType.NEVER,
                           vexpand=True, hexpand=True)
    s.add(child)
    return s


# --- HUDs ---
def grayscale(widget):
    """Greyscale antialiasing for text on a translucent window (sub-pixel colour fringes show through it)."""
    options = cairo.FontOptions()
    options.set_antialias(cairo.ANTIALIAS_GRAY)
    widget.set_font_options(options)
    return widget


def blur_behind(win, card):
    """Ask KWin to blur what's behind card, a translucent window's card (X11/XWayland: KWin's
    _KDE_NET_WM_BLUR_BEHIND_REGION, rectangles of x, y, width, height; ignored where there's no KWin)."""
    try:
        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11
        gdk_win = win.get_window()
        if not isinstance(gdk_win, GdkX11.X11Window):
            return
        a = card.get_allocation()
        import subprocess
        subprocess.Popen(["xprop", "-id", str(gdk_win.get_xid()), "-f", "_KDE_NET_WM_BLUR_BEHIND_REGION", "32c",
                          "-set", "_KDE_NET_WM_BLUR_BEHIND_REGION", f"{a.x},{a.y},{a.width},{a.height}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (ImportError, ValueError, OSError, AttributeError):
        pass


class Hud:
    """A HUD card in a window of its own: translucent, rounded, floating above other windows. self.box is
    where its content goes; self.win is the window (titled, so it can be found)."""

    def __init__(self, title, width=380, modal_for=None, warning=False):
        self.win = classes(Gtk.Window(title=title, decorated=False, resizable=False, app_paintable=True,
                                      skip_taskbar_hint=True, type_hint=Gdk.WindowTypeHint.DIALOG), "hud-window")
        visual = self.win.get_screen().get_rgba_visual()
        if visual:
            self.win.set_visual(visual)
        grayscale(self.win)
        self.win.set_keep_above(True)
        if modal_for:
            self.win.set_transient_for(modal_for)
            self.win.set_modal(True)
        self.card = classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=width), "hud",
                            "warning-edge" if warning else None)
        self.box = self.card
        self.win.add(self.card)
        self.win.connect("draw", self._clear)
        self.win.connect("map-event", lambda w, _: blur_behind(w, self.card) and False)
        self.win.connect("key-press-event", self._key)
        self.on_escape = self.close

    def _clear(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False

    def _key(self, _, ev):
        if Gdk.keyval_name(ev.keyval) == "Escape":
            self.on_escape()
            return True
        return False

    def heading(self, title, icon=None, warning=False):
        row = Gtk.Box(spacing=8)
        if icon:
            row.pack_start(classes(Icon(icon), "warning-text" if warning else "accent-text"), False, False, 0)
        row.pack_start(text(title, "title", wrap=True, max_chars=40), True, True, 0)
        self.box.pack_start(row, False, False, 0)
        return row

    def buttons(self, *buttons):
        """Buttons at the bottom right: the safe choice first, the primary last."""
        row = Gtk.Box(spacing=8, margin_top=4)
        for b in reversed(buttons):
            row.pack_end(b, False, False, 0)
        self.box.pack_start(row, False, False, 0)
        return row

    def show(self, near=None):
        """Show it beside near (x, y, w, h on screen), else in the middle of the screen."""
        self.win.show_all()
        if near:
            place_beside(self.win, near)
        else:
            self.win.set_position(Gtk.WindowPosition.CENTER)
        self.win.present_with_time(Gtk.get_current_event_time())

    def close(self):
        self.win.destroy()

    @property
    def open(self):
        return self.win.get_mapped()


def place_beside(win, near):
    """Put win beside the rectangle near (x, y, w, h), on its screen: right of it, or left if there's no room."""
    x, y, w, h = near
    width, height = win.get_size()
    area = Gdk.Display.get_default().get_monitor_at_point(x + w // 2, y + h // 2).get_workarea()
    left = x + w + 4 if x + w + 4 + width <= area.x + area.width else x - 4 - width
    top = min(max(y + h // 2 - 40, area.y), area.y + area.height - height)
    win.move(max(left, area.x), top)


# --- drawing text in cairo (the capsule) ---
def layout(cr, words, kind="caption", colour="text", tabular=False):
    """A Pango layout of words in a type style, for drawing with cairo; returns (layout, width, height)."""
    lay = PangoCairo.create_layout(cr)
    size, weight = TYPE[kind]
    desc = Pango.FontDescription()
    desc.set_family("Inter,Noto Sans,Cantarell,sans-serif")
    desc.set_absolute_size(size * Pango.SCALE)
    desc.set_weight(Pango.Weight.SEMIBOLD if weight >= 600 else Pango.Weight.NORMAL)
    lay.set_font_description(desc)
    if tabular:
        attrs = Pango.AttrList()
        try:
            attrs.insert(Pango.attr_font_features_new("tnum"))
            lay.set_attributes(attrs)
        except (AttributeError, TypeError):
            pass
    lay.set_text(words, -1)
    w, h = lay.get_pixel_size()
    return lay, w, h


# --- the Dictate window's pages ---
def page_box():
    return classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "page")


def page_header(title, *actions, subtitle=None, clamp=None):
    """The page's headline at left, its actions at right; at most clamp px wide (the page's column), centred."""
    row = classes(Gtk.Box(spacing=8), "page-header")
    words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    words.pack_start(text(title, "headline", ellipsize=True), False, False, 0)
    if subtitle:
        words.pack_start(subtitle, False, False, 0)
    row.pack_start(words, True, True, 0)
    for a in reversed(actions):
        row.pack_end(a, False, False, 0)
    return Clamp(row, clamp) if clamp else row


def switch(on, changed):
    s = Gtk.Switch(active=on)
    s.connect("notify::active", lambda w, _: changed(w.get_active()))
    return s


def combo(options, current, changed):
    """A dropdown of options [(value, label)] with current chosen; changed(value) when another is."""
    c = Gtk.ComboBoxText()
    for _, label in options:
        c.append_text(label)
    values = [v for v, _ in options]
    c.set_active(values.index(current) if current in values else 0)
    c.connect("changed", lambda w: changed(values[w.get_active()]))
    return c
