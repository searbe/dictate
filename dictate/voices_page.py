"""The Voices page: whether voices are remembered (opt-in), and the voices remembered, each of which can be
forgotten."""

from gi.repository import GLib, Gtk

from . import design as d
from . import huds, transcript, voices


class VoicesPage:
    """Remembering voices (opt-in) and the voices remembered, each of which can be forgotten."""
    EXPLAIN = ("Dictate keeps a voiceprint of each person you name in a transcript, on this computer only, and names "
               "them in later transcripts. A voiceprint can identify someone: ask people first. Turning this off "
               "forgets every voice.")

    def __init__(self, hub):
        self.hub = hub
        self.widget = d.page_box()
        self.widget.pack_start(d.page_header("Voices", clamp=560), False, False, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=24, margin_end=24)
        self.toggle = Gtk.Switch(active=voices.remembering())
        self.toggle.connect("notify::active", lambda *_: self.toggled())
        body.pack_start(d.setting_row("Remember voices I name", self.EXPLAIN, self.toggle), False, False, 0)
        body.pack_start(d.hairline(), False, False, 0)
        body.pack_start(d.classes(Gtk.Label(label="Remembered voices", xalign=0, margin_top=16, margin_bottom=8),
                                  "title"), False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        body.pack_start(self.list, False, False, 0)
        self.widget.pack_start(d.Clamp(body, 560), False, False, 0)

    def shown(self, **_):
        self.refresh()

    def refresh(self):
        for kid in self.list.get_children():
            kid.destroy()
        names = [name for name, _ in voices.remembered()]
        if not names:
            self.list.add(d.text("None yet. Name someone in a transcript to remember their voice."
                                 if voices.remembering() else "None.", "small"))
        for name in names:
            row = d.classes(Gtk.Box(spacing=8), "row-item")
            row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            row.pack_end(d.button("Forget", lambda n=name: (voices.forget(n), self.refresh()), "danger", small=True),
                         False, False, 0)
            self.list.add(row)
        self.list.show_all()

    def toggled(self):
        on = self.toggle.get_active()
        n = len(voices.remembered())
        if not on and n and not huds.confirm(self.hub.win, f"Forget {'the' if n == 1 else f'all {n}'} remembered "
                                             f"voice{'s' if n > 1 else ''}?", "This can't be undone.", "Forget"):
            GLib.idle_add(lambda: self.toggle.set_active(True) and False)
            return
        voices.set_remembering(on)
        if not on:
            transcript.forget_voiceprints()
        self.refresh()
