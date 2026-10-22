"""Dictate's design system in code: the tokens of docs/design/DESIGN.md, the CSS made from them (dark or light,
following the desktop's preference, live), a small icon set drawn in cairo, and the components every surface is
built from. Use these names, never raw colours or sizes; add to DESIGN.md first."""
import math
import cairo, gi
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo

# --- tokens ---
SCHEMES = {
    "dark": {
        "bg": "#111214", "surface-1": "#17181b", "surface-2": "#1d1f23", "surface-3": "#25272c", "surface-4": "#2e3137",
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


def css():
    t = SCHEMES[scheme]
    size = lambda k: f"font-size: {TYPE[k][0]}px; font-weight: {TYPE[k][1]};"
    topics = "".join(f".topic-edge-{i} {{ border-left: 3px solid {c}; }}\n.topic-text-{i} {{ color: {c}; }}\n"
                     for i, c in enumerate(t["topics"]))
    return f"""
* {{ font-family: {FONT}; }}
window.dictate, window.dictate .page {{ background-color: {t['bg']}; color: {t['text']}; {size('body')} }}
window.dictate headerbar {{ background-color: {t['bg']}; border: none; box-shadow: none; min-height: 40px; padding: 0 8px;
  background-image: linear-gradient(to right, {t['surface-1']} 199px, {t['line']} 199px, {t['line']} 200px, transparent 200px); }}
window.dictate headerbar .title {{ color: {t['text']}; {size('body-strong')} }}
window.dictate headerbar button.titlebutton {{ border: none; box-shadow: none; }}
scrollbar {{ background: transparent; border: none; box-shadow: none; }}
scrollbar trough {{ background: transparent; border: none; box-shadow: none; }}
scrollbar button {{ min-width: 0; min-height: 0; padding: 0; margin: 0; border: none; background: none; box-shadow: none;
  -gtk-icon-source: none; opacity: 0; }}
scrollbar slider {{ border: none; border-radius: {R_FULL}px; background: {t['line-strong']}; margin: 3px;
  transition: min-width 120ms ease-out, min-height 120ms ease-out, background-color 120ms ease-out; }}
scrollbar.vertical slider {{ min-width: 3px; min-height: 32px; }}
scrollbar.horizontal slider {{ min-height: 3px; min-width: 32px; }}
scrollbar.vertical:hover slider, scrollbar.vertical.dragging slider {{ min-width: 6px; background: {t['text-3']}; }}
scrollbar.horizontal:hover slider, scrollbar.horizontal.dragging slider {{ min-height: 6px; background: {t['text-3']}; }}
window.dictate list, window.dictate row {{ background: transparent; }}
window.dictate textview, window.dictate textview text {{ background: transparent; color: {t['text']}; }}
window.dictate selection, window.dictate text selection {{ background: {t['accent-weak']}; color: {t['text']}; }}
window.dictate tooltip, tooltip {{ background: {t['surface-4']}; color: {t['text']}; border-radius: {R_SM}px; border: 1px solid {t['line']}; }}
tooltip * {{ color: {t['text']}; {size('small')} }}

/* type */
.headline {{ {size('headline')} color: {t['text']}; }}
.title {{ {size('title')} color: {t['text']}; }}
.body {{ {size('body')} color: {t['text']}; }}
.strong {{ {size('body-strong')} color: {t['text']}; }}
.small {{ {size('small')} color: {t['text-2']}; }}
.caption {{ {size('caption')} color: {t['text-3']}; }}
.muted {{ color: {t['text-2']}; }}
.faint {{ color: {t['text-3']}; }}
.label-strong {{ font-weight: 600; }}
.tabular {{ font-feature-settings: "tnum"; }}
.danger-text {{ color: {t['danger']}; }}
.accent-text {{ color: {t['accent']}; }}
.warning-text {{ color: {t['warning']}; }}

/* buttons */
button.btn {{ min-height: 28px; padding: 0 12px; border-radius: {R_SM}px; border: none; box-shadow: none;
  background: {t['surface-3']}; color: {t['text']}; {size('body-strong')} -gtk-icon-shadow: none; outline: none;
  transition: background-color 120ms ease-out, color 120ms ease-out, opacity 120ms ease-out; }}
button.btn:hover {{ background: {t['surface-4']}; }}
button.btn label {{ color: inherit; }}
button.btn.primary {{ background: {t['accent']}; color: {t['on-accent']}; }}
button.btn.primary:hover {{ background: {t['accent-hover']}; }}
button.btn.quiet {{ background: transparent; color: {t['text-2']}; }}
button.btn.quiet:hover {{ background: {t['surface-3']}; color: {t['text']}; }}
button.btn.danger {{ background: transparent; color: {t['danger']}; }}
button.btn.danger:hover {{ background: {t['danger-weak']}; }}
button.btn.small {{ min-height: 24px; padding: 0 8px; }}
button.btn.icon {{ min-width: 28px; min-height: 28px; padding: 0; background: transparent; color: {t['text-2']}; }}
button.btn.icon:hover {{ background: {t['surface-3']}; color: {t['text']}; }}
button.btn.icon.danger:hover {{ background: {t['danger-weak']}; color: {t['danger']}; }}
button.btn.icon.on {{ color: {t['accent']}; }}
button.btn .keyhint {{ {size('caption')} color: {t['text-3']}; margin-left: 6px; }}
button.btn.primary .keyhint {{ color: rgba(255,255,255,0.7); }}

/* chips, badges, pills */
.chip {{ {size('caption')} background: {t['surface-3']}; color: {t['text-2']}; border-radius: {R_SM}px; padding: 2px 7px; }}
.chip.accent {{ background: {t['accent-weak']}; color: {t['accent']}; }}
.key {{ {size('caption')} font-weight: 600; background: {t['surface-3']}; color: {t['text']}; border-radius: {R_XS}px;
  min-width: 18px; min-height: 18px; padding: 0 4px; }}
.pill {{ {size('caption')} font-weight: 600; background: {t['surface-3']}; color: {t['text']}; border-radius: {R_FULL}px; padding: 3px 10px; }}

/* rows and lists */
.row-item {{ border-radius: {R_MD}px; padding: 8px 12px; transition: background-color 120ms ease-out; }}
.row-item:hover {{ background: {t['surface-2']}; }}
.row-item .actions {{ opacity: 0; transition: opacity 120ms ease-out; }}
.row-item:hover .actions, .row-item .actions.shown {{ opacity: 1; }}
.group-header {{ {size('caption')} font-weight: 600; color: {t['text-3']}; margin: 16px 12px 4px 12px; }}
.hairline {{ background: {t['line']}; min-height: 1px; min-width: 1px; }}
list.nav, list.pick {{ background: transparent; }}
list.pick row {{ border-radius: {R_SM}px; margin: 1px 8px; padding: 0; transition: background-color 120ms ease-out; }}
list.pick row:hover {{ background: {t['surface-2']}; }}
list.pick row:selected {{ background: {t['surface-3']}; color: {t['text']}; }}

/* the sidebar */
.sidebar {{ background: {t['surface-1']}; border-right: 1px solid {t['line']}; }}
.sidebar .app-name {{ {size('title')} color: {t['text']}; margin: 4px 16px 12px 16px; }}
list.nav row {{ min-height: 32px; border-radius: {R_SM}px; margin: 1px 8px; padding: 0 8px; color: {t['text-2']};
  transition: background-color 120ms ease-out, color 120ms ease-out; }}
list.nav row:hover {{ background: {t['surface-2']}; color: {t['text']}; }}
list.nav row:selected {{ background: {t['surface-3']}; color: {t['text']}; }}
list.nav row label {{ color: inherit; {size('body')} }}
list.nav row:selected label {{ font-weight: 600; }}

/* fields */
.field-label {{ {size('small')} font-weight: 600; color: {t['text-2']}; }}
window.dictate entry, .hud entry {{ min-height: 32px; border-radius: {R_SM}px; background: {t['surface-2']}; color: {t['text']};
  border: 1px solid {t['line']}; box-shadow: none; padding: 0 10px; caret-color: {t['accent']}; }}
window.dictate entry:focus, .hud entry:focus {{ border-color: {t['accent']}; box-shadow: 0 0 0 3px {t['accent-weak']}; }}
window.dictate entry image {{ color: {t['text-3']}; }}
.editor {{ border-radius: {R_SM}px; background: {t['surface-2']}; border: 1px solid {t['line']}; }}
.editor textview, .editor textview text {{ background: {t['surface-2']}; }}
window.dictate combobox button, window.dictate combobox button.combo {{ min-height: 28px; border-radius: {R_SM}px;
  background: {t['surface-3']}; color: {t['text']}; border: none; box-shadow: none; padding: 0 8px; }}
window.dictate combobox button:hover {{ background: {t['surface-4']}; }}
window.dictate switch {{ background: {t['surface-4']}; border: none; border-radius: {R_FULL}px; min-width: 36px; min-height: 20px; }}
window.dictate switch:checked {{ background: {t['accent']}; }}
window.dictate switch slider {{ background: #ffffff; border: none; border-radius: {R_FULL}px; min-width: 16px; min-height: 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.3); margin: 2px; }}
window.dictate check {{ border-radius: {R_XS}px; background: {t['surface-3']}; border: 1px solid {t['line-strong']}; color: {t['on-accent']}; }}
window.dictate check:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

/* setting rows, pages */
.setting {{ padding: 12px 0; }}
.page-header {{ margin: 20px 24px 8px 24px; }}
.panel {{ background: {t['surface-1']}; }}
.panel-left {{ border-right: 1px solid {t['line']}; }}
.panel-right {{ border-left: 1px solid {t['line']}; }}
.empty-state {{ margin: 48px 24px; }}
.status-dot {{ min-width: 6px; min-height: 6px; border-radius: 3px; background: {t['record']}; }}
.status-dot.paused {{ background: {t['text-3']}; }}

/* warnings */
.warning-strip {{ background: {t['warning-weak']}; color: {t['warning']}; border-radius: {R_SM}px; padding: 8px 10px; }}
.warning-strip label {{ color: {t['warning']}; {size('small')} }}

/* topics */
.topic-card {{ border-radius: {R_MD}px; padding: 10px 12px; margin: 2px 8px; background: transparent; border: none;
  box-shadow: none; transition: background-color 120ms ease-out; }}
.topic-card:hover {{ background: {t['surface-2']}; }}
.topic-card.now {{ background: {t['surface-2']}; }}
.topic-card label {{ color: {t['text']}; }}
.topic-card .small {{ color: {t['text-2']}; }}
.topic-card .caption {{ color: {t['text-3']}; }}
{topics}
/* HUDs */
window.hud-window, window.hud-window > * {{ background: transparent; }}
.hud {{ background: {t['hud']}; border: 1px solid {t['line-strong']}; border-radius: {R_LG}px; color: {t['text']};
  box-shadow: inset 0 1px {t['highlight']}, 0 8px 24px {t['shadow']}; padding: 16px; margin: 16px; {size('body')} }}
.hud.warning-edge {{ border-color: {t['warning-weak']}; }}
.hud .choice {{ min-height: 36px; border-radius: {R_SM}px; background: transparent; border: none; box-shadow: none;
  padding: 0 8px; color: {t['text']}; transition: background-color 120ms ease-out; }}
.hud .choice:hover {{ background: {t['surface-3']}; }}
.hud .quote {{ background: {t['surface-2']}; border-radius: {R_MD}px; padding: 10px 12px; }}
menu, .menu {{ background: {t['surface-1']}; border: 1px solid {t['line-strong']}; border-radius: {R_LG}px; padding: 6px; }}
menu menuitem {{ color: {t['text']}; padding: 6px 12px; border-radius: {R_SM}px; min-height: 18px; {size('body')} }}
menu menuitem:hover {{ background: {t['surface-3']}; }}
menu menuitem label {{ color: inherit; }}
menu menuitem check, menu menuitem radio {{ color: {t['accent']}; }}
menu separator {{ background: {t['line']}; margin: 4px 6px; min-height: 1px; }}
menu arrow {{ color: {t['text-3']}; }}
"""


_provider = None


def install():
    """Apply the design to the app's windows; follow the desktop's light/dark preference from now on."""
    global _provider, scheme
    scheme = _desktop_scheme() or "dark"
    _apply()
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
def _icon_paths(cr, name):
    """Draw icon name on a 16×16 grid (strokes; the caller strokes and fills)."""
    m, l, c, a = cr.move_to, cr.line_to, cr.curve_to, cr.arc
    pi = math.pi
    if name == "mic":
        cr.new_sub_path(); a(8, 4.5, 2.5, pi, 0); l(10.5, 7.5); a(8, 7.5, 2.5, 0, pi); cr.close_path()
        cr.new_sub_path(); a(8, 7.5, 4.5, 0, pi); m(8, 12); l(8, 14.5)
    elif name == "history":
        cr.new_sub_path(); a(8, 8, 6, 0, 2 * pi); m(8, 4.5); l(8, 8); l(10.5, 9.5)
    elif name == "transcript":
        for y, w in ((4, 10), (7, 8), (10, 10), (13, 6)):
            m(3, y); l(3 + w, y)
    elif name == "styles":
        m(8, 2); c(8.5, 5.5, 10.5, 7.5, 14, 8); c(10.5, 8.5, 8.5, 10.5, 8, 14); c(7.5, 10.5, 5.5, 8.5, 2, 8)
        c(5.5, 7.5, 7.5, 5.5, 8, 2); cr.close_path()
    elif name == "voices":
        cr.new_sub_path(); a(8, 5.5, 2.75, 0, 2 * pi); m(2.75, 14); c(3, 10.5, 5.5, 9.5, 8, 9.5); c(10.5, 9.5, 13, 10.5, 13.25, 14)
    elif name == "settings":
        cr.new_sub_path(); a(8, 8, 2.25, 0, 2 * pi)
        for k in range(8):
            ang = k * pi / 4
            m(8 + 4.2 * math.cos(ang), 8 + 4.2 * math.sin(ang)); l(8 + 6 * math.cos(ang), 8 + 6 * math.sin(ang))
        cr.new_sub_path(); a(8, 8, 4.2, 0, 2 * pi)
    elif name == "search":
        cr.new_sub_path(); a(7, 7, 4.25, 0, 2 * pi); m(10.2, 10.2); l(13.5, 13.5)
    elif name == "copy":
        _round_rect(cr, 5.5, 5.5, 8, 8, 1.75)
        m(3.5, 10.5); l(3.5, 4.25); c(3.5, 3.5, 3.5, 2.5, 4.5, 2.5); l(10.5, 2.5)
    elif name == "play":
        m(5, 3); l(13, 8); l(5, 13); cr.close_path()
    elif name == "stop":
        _round_rect(cr, 4, 4, 8, 8, 1.5)
    elif name == "pause":
        m(5.5, 3.5); l(5.5, 12.5); m(10.5, 3.5); l(10.5, 12.5)
    elif name == "trash":
        m(2.5, 4.5); l(13.5, 4.5); m(6, 4.5); l(6, 2.5); l(10, 2.5); l(10, 4.5)
        m(4, 4.5); l(4.75, 13.5); l(11.25, 13.5); l(12, 4.5)
    elif name == "undo":
        m(5.5, 3); l(2.5, 6); l(5.5, 9); m(2.5, 6); l(9.5, 6); c(12, 6, 13.5, 7.5, 13.5, 9.75); c(13.5, 12, 12, 13.5, 9.5, 13.5); l(6.5, 13.5)
    elif name == "folder":
        m(2, 4); l(6, 4); l(7.5, 5.5); l(14, 5.5); l(14, 12.5); l(2, 12.5); cr.close_path()
    elif name == "open":
        m(9, 2.5); l(13.5, 2.5); l(13.5, 7); m(13.5, 2.5); l(7.5, 8.5)
        m(11.5, 9.5); l(11.5, 13.5); l(2.5, 13.5); l(2.5, 4.5); l(6.5, 4.5)
    elif name == "plus":
        m(8, 3); l(8, 13); m(3, 8); l(13, 8)
    elif name == "check":
        m(3, 8.5); l(6.5, 12); l(13, 4.5)
    elif name == "warning":
        m(8, 2.5); l(14, 13); l(2, 13); cr.close_path(); m(8, 6.5); l(8, 9.25); m(8, 11.25); l(8, 11.3)
    elif name == "close":
        m(4, 4); l(12, 12); m(12, 4); l(4, 12)
    elif name == "record":
        cr.new_sub_path(); a(8, 8, 4, 0, 2 * pi)


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
    b = classes(Gtk.Button(tooltip_text=tooltip), "btn", kind if kind != "secondary" else None, "small" if small else None)
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
