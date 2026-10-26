"""The Dictate window: one home for everything but the capsule and a moment's HUD (docs/design/DESIGN.md). A
sidebar of pages (Dictations, Transcripts, Refinements, Voices, Settings); the window's title is the page shown. Pages
are built when first shown, and told each time they're shown again (so Dictations shows the latest)."""
from gi.repository import GLib, Gtk

from . import design as d
from . import voices
from .dictations_page import DictationsPage
from .refinements_page import RefinementsPage
from .settings_page import SettingsPage
from .transcripts_page import TranscriptsPage
from .voices_page import VoicesPage

PAGES = (("dictations", "Dictations", "history"), ("transcripts", "Transcripts", "transcript"),
         ("refinements", "Refinements", "refinements"), ("voices", "Voices", "voices"),
         ("settings", "Settings", "settings"))


class Hub:
    """app: the App (its settings, playback, and what it's transcribing)."""

    def __init__(self, app):
        self.app, self.pages, self.page = app, {}, None
        self.win = d.classes(Gtk.Window(title="Dictate", default_width=1120, default_height=680), "dictate")
        bar = Gtk.HeaderBar(show_close_button=True)
        bar.set_custom_title(Gtk.Box())  # the page says what it is; the bar only holds the window's buttons
        self.win.set_titlebar(bar)
        bar.show_all()  # (else there's no title bar at all: nothing to close or drag the window by)
        self.win.connect("delete-event", lambda *_: not self.may_close())  # (True keeps it open)
        self.win.connect("destroy", lambda *_: (setattr(self, "closed", True), app.playback.stop()))
        self.closed = False

        side = self.side = d.classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200, hexpand=False),
                                     "sidebar")
        self.wide_only = [d.classes(Gtk.Label(label="Dictate", xalign=0), "app-name")]  # hidden while compact
        side.pack_start(self.wide_only[0], False, False, 0)
        self.nav = d.classes(Gtk.ListBox(), "nav")
        for key, title, icon in PAGES:
            if key == "voices" and not voices.available():
                continue
            row = Gtk.ListBoxRow()
            row.key = key
            box = Gtk.Box(spacing=10)
            box.pack_start(d.Icon(icon), False, False, 0)
            name = Gtk.Label(label=title, xalign=0)
            box.pack_start(name, True, True, 0)
            row.add(box)
            row.set_tooltip_text(title)
            self.wide_only.append(name)
            self.nav.add(row)
        self.nav.connect("row-selected", lambda _, row: row and row.key != self.page and self.show(row.key))
        side.pack_start(self.nav, False, False, 0)
        hint = d.text("Hold Ctrl+Win to dictate", "caption", wrap=True, margin=16)
        side.pack_end(hint, False, False, 0)
        self.wide_only.append(hint)
        self.compact = False
        self.win.connect("size-allocate", lambda w, room: self.fit(w.get_size()[0]))  # (room has the shadow too)

        self.stack = Gtk.Stack(hhomogeneous=False)  # pages switch at once: a frequent action, not worth animating
        # (and each has its own narrowest: Transcripts needs more room than Settings)
        body = Gtk.Box()
        body.pack_start(side, False, False, 0)
        body.pack_start(self.stack, True, True, 0)
        self.win.add(body)
        body.show_all()

    def may_close(self):
        """Before the window closes: a page with unsaved changes is shown, and asks whether to save them."""
        for key, page in self.pages.items():
            if getattr(page, "dirty", lambda: False)():
                self.show(key)
                if not page.leave():
                    return False
        return True

    COMPACT = 1120  # px: a window narrower than this has the sidebar's icons only (so Transcripts fits in ~960)

    def fit(self, width):
        """Collapse the sidebar to its icons in a narrow window, and back in a wide one."""
        compact = width < self.COMPACT
        if compact != self.compact:
            self.compact = compact
            GLib.idle_add(self.collapse, compact)  # (not while GTK's allocating sizes: it would be ignored)

    def collapse(self, compact):
        for w in self.wide_only:
            w.set_visible(not compact)
        self.side.set_size_request(56 if compact else 200, -1)
        (self.win.get_style_context().add_class if compact else self.win.get_style_context().remove_class)("compact")
        return False

    def show(self, key, focus=True, **kw):
        """Show page key (building it the first time), passing kw to it; bring the window forward (unless not
        focus: e.g. started from the keyboard mid-conversation)."""
        if key not in self.pages:
            self.pages[key] = page = {"dictations": DictationsPage, "transcripts": TranscriptsPage,
                                      "refinements": RefinementsPage, "voices": VoicesPage,
                                      "settings": SettingsPage}[key](self)
            self.stack.add_named(page.widget, key)
            page.widget.show_all()
        self.page = key
        self.stack.set_visible_child_name(key)
        self.win.set_title(dict((k, t) for k, t, _ in PAGES)[key])
        for row in self.nav.get_children():
            if row.key == key and self.nav.get_selected_row() is not row:
                self.nav.select_row(row)
        self.pages[key].shown(**kw)
        if not self.win.get_visible():
            self.win.set_focus_on_map(focus)
            self.win.show()
        elif focus:
            self.win.present()
        return self.pages[key]
