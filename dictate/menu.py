"""The capsule's right-click menu, which the tray icon shows too (tray.py mirrors it).

Its ticks and its refinement lists are refreshed each time it opens (refresh()): the same settings can be
changed on the Settings and Refinements pages."""

from gi.repository import Gtk

from . import osio, refinements
from .settings import REMOTE_MODES, SAME

TRANSCRIBE, STOP_TRANSCRIBING = "Transcribe this computer", "Stop transcribing"


class Menu:
    """app: the App, whose settings the menu shows and whose windows it opens."""

    def __init__(self, app):
        self.app, settings = app, app.settings
        self.widget = menu = Gtk.Menu()
        self._item(menu, "Open Dictate", lambda: app.open_hub("dictations"))
        menu.append(Gtk.SeparatorMenuItem())
        self.refine = Gtk.CheckMenuItem(label="Refine text", active=settings["refine"])
        self.refine.connect("toggled", lambda item: settings.update(refine=item.get_active()))
        menu.append(self.refine)
        self.default_menu = self._submenu(menu, "Default refinement")
        self._item(menu, "Dictations", lambda: app.open_hub("dictations"))
        self._item(menu, "Refinements…", lambda: app.open_hub("refinements"))
        self._item(menu, "Settings…", lambda: app.open_hub("settings"))
        menu.append(Gtk.SeparatorMenuItem())
        self.transcribe = None
        if osio.HEARS_SPEAKERS:
            self.transcribe = self._item(menu, TRANSCRIBE, app.toggle_transcribing)
            self._item(menu, "Transcripts", app.show_transcripts)
            menu.append(Gtk.SeparatorMenuItem())
        away = self._submenu(menu, "When another computer has the keyboard")  # e.g. through Synergy
        self.remote_modes, group = [], None
        for mode, label in REMOTE_MODES:
            item = Gtk.RadioMenuItem(label=label, group=group, active=mode == settings["remote_mode"])
            group = group or item
            self.remote_modes.append((item, mode))
            away.append(item)
        for item, mode in self.remote_modes:  # connected after ticking, so setting them up isn't saved
            item.connect("toggled", lambda i, m=mode: i.get_active() and settings.update(remote_mode=m))
        away.append(Gtk.SeparatorMenuItem())
        # per-app refinements can't apply over there: its apps can't be seen
        self.remote_default_menu = self._submenu(away, "Default refinement there")
        self.startup = Gtk.CheckMenuItem(label="Run at startup", active=osio.autostart_enabled())
        self.startup.connect("toggled", lambda item: osio.set_autostart(item.get_active()))
        menu.append(self.startup)
        self._item(menu, "Quit", lambda: app.quit("Quit chosen from the menu"))
        menu.show_all()
        self.ticking = False  # while the refinement lists are being (re)built: GTK's own ticks aren't choices
        self.refresh()

    @staticmethod
    def _item(menu, label, chosen):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _: chosen())
        menu.append(item)
        return item

    @staticmethod
    def _submenu(menu, label):
        item, sub = Gtk.MenuItem(label=label), Gtk.Menu()
        item.set_submenu(sub)
        menu.append(item)
        return sub

    def popup(self, event):
        self.refresh()
        self.widget.popup_at_pointer(event)

    def close(self):
        if self.widget.get_visible():
            self.widget.popdown()

    def transcribing(self, on):
        if self.transcribe:
            self.transcribe.set_label(STOP_TRANSCRIBING if on else TRANSCRIBE)

    def refresh(self):
        """Tick what's set now, and list the refinements there are now (here, and on the other computer)."""
        settings = self.app.settings
        ticks = [(self.refine, settings["refine"]), (self.startup, osio.autostart_enabled()),
                 *((item, mode == settings["remote_mode"]) for item, mode in self.remote_modes)]
        for item, on in ticks:
            if item.get_active() != on:
                item.set_active(on)
        data = refinements.load()
        names = [r["name"] for r in data["refinements"]]
        here = refinements.default()
        self._fill(self.default_menu, [(None, "None (cleanup only)")] + [(n, n) for n in names],
                   here and here["name"], refinements.set_default)
        there = data.get("remote_default", SAME)
        self._fill(self.remote_default_menu,
                   [(SAME, "Same as here"), (None, "None (cleanup only)")] + [(n, n) for n in names],
                   there if there in [SAME, None, *names] else None,
                   lambda value: refinements.set_remote_default(value, same=value is SAME))

    def _fill(self, menu, choices, current, pick):
        """A radio list of (value, label) choices with current ticked; pick(value) saves a choice.
        Rebuilt only if the choices changed, otherwise just re-ticked, so the tray's item ids stay valid."""
        self.ticking = True
        if choices != getattr(menu, "choices", None):
            for item in menu.get_children():
                menu.remove(item)
            menu.choices, menu.items, group = choices, {}, None
            for value, label in choices:
                item = menu.items[value] = Gtk.RadioMenuItem(label=label, group=group)
                group = group or item
                item.connect("toggled", lambda i, v=value: i.get_active() and not self.ticking and pick(v))
                menu.append(item)
            menu.show_all()
        menu.items[current].set_active(True)
        self.ticking = False
