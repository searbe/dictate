"""The Settings page: everything that's otherwise in the capsule's menu, in one place."""

from gi.repository import GLib, Gtk

from . import claude_code, huds, osio, refinements
from . import design as d
from .settings import KEEP_AUDIO, REMOTE_MODES, SAME


class SettingsPage:
    """Everything that's otherwise in the menu, in one place."""

    def __init__(self, hub):
        self.hub, self.app = hub, hub.app
        self.widget = d.page_box()
        self.widget.pack_start(d.page_header("Settings", clamp=640), False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=24, margin_end=24)
        self.widget.pack_start(d.scrolled(d.Clamp(self.body, 640)), True, True, 0)

    def shown(self, **_):
        for kid in self.body.get_children():
            kid.destroy()
        app, cfg = self.app, self.app.settings
        data = refinements.load()
        names = [r["name"] for r in data["refinements"]]
        here = refinements.default()
        there = data.get("remote_default", SAME)
        mic = app.microphone()  # (which also adds any microphones seen for the first time)
        rows = [
            ("Dictation",),
            ("Refine text", "Cleanup, then the refinement for the app you're dictating into (or the default), with a "
                            "local model. Off pastes exactly what was heard; Alt still picks a refinement.",
             d.switch(cfg["refine"], app.set_refine)),
            ("Default refinement", "Applied after cleanup to every dictation that no app's refinement matches.",
             d.combo([(None, "None (cleanup only)")] + [(n, n) for n in names], here and here["name"],
                     refinements.set_default)),
            ("Microphone",),
            d.text("Dictate records the first of these that's connected.", "small", wrap=True, margin_bottom=8),
            *self.microphone_rows(mic),
            ("Recordings",),
            ("Keep dictation recordings", "How long each dictation's audio is kept, to play back from Dictations. "
                                          "Its text is kept until you delete it.",
             d.combo(list(KEEP_AUDIO), cfg["keep_audio_hours"], app.set_keep_audio)),
            ("Keep transcript recordings", "How long a transcript's audio is kept, to play back from Transcripts. "
                                           "The transcript is kept until you delete it.",
             d.combo(list(KEEP_AUDIO), cfg["keep_call_hours"], app.set_keep_calls)),
            ("Another computer",),
            ("When it has the keyboard", "When your keyboard controls another computer (Synergy and similar).",
             d.combo(list(REMOTE_MODES), cfg["remote_mode"], lambda m: cfg.update(remote_mode=m))),
            ("Default refinement there", "Its apps can't be seen from here, so this is used for everything.",
             d.combo([(SAME, "Same as here"), (None, "None (cleanup only)")] + [(n, n) for n in names],
                   there if there in [SAME, None, *names] else None,
                   lambda v: refinements.set_remote_default(v, same=v is SAME))),
            ("Claude Code",),
            ("/meeting-notes", "A skill for every Claude Code session: /meeting-notes asks Dictate for transcripts "
                               "about something, and you choose which to share, if any. Installing it also turns on "
                               "the block below.",
             d.button("Remove" if claude_code.skill_installed() else "Install", self.toggle_skill, small=True)),
            ("Let Claude Code ask for transcripts", "Each time, a window here asks which to share. Off: every request "
                                                    "is refused without asking.",
             d.switch(cfg["share_with_claude"], lambda on: cfg.update(share_with_claude=on))),
            ("Block Claude Code from reading Dictate's files", "So transcripts reach it only through that window: its "
                                                               "file tools and commands like cat can't open them (a "
                                                               "program that opens files itself still could). Turn "
                                                               "off only to develop Dictate with Claude Code.",
             d.switch(claude_code.blocked(), self.set_blocked)),
            ("Startup",),
            ("Run at startup", "Start Dictate when you log in.", d.switch(app.autostart(), app.set_autostart)),
        ]
        first = True
        for row in rows:
            if isinstance(row, Gtk.Widget):
                self.body.pack_start(row, False, False, 0)
                continue
            title, *rest = row
            if not rest:
                self.body.pack_start(d.classes(Gtk.Label(label=title, xalign=0, margin_top=8 if first else 24,
                                                         margin_bottom=4), "title"), False, False, 0)
                first = False
                continue
            self.body.pack_start(d.setting_row(title, *rest), False, False, 0)
            self.body.pack_start(d.hairline(), False, False, 0)
        self.body.show_all()

    def toggle_skill(self):
        try:
            claude_code.remove_skill() if claude_code.skill_installed() else claude_code.install_skill()
        except (OSError, ValueError) as err:
            huds.message(self.hub.win, "Couldn't change Claude Code's settings", str(err))
        self.shown()

    def set_blocked(self, on):
        try:
            claude_code.set_blocked(on)
        except (OSError, ValueError) as err:
            huds.message(self.hub.win, "Couldn't change Claude Code's settings", str(err))
            GLib.idle_add(lambda: self.shown() and False)  # (the switch back as it is)

    def microphone_rows(self, mic):
        """A row for each microphone seen, in the order they're preferred, with buttons to move it up or down,
        and to forget one that isn't connected."""
        order, connected = self.app.settings["microphones"], dict(osio.microphones())

        def move(i, by):
            new = list(order)
            new.insert(i + by, new.pop(i))
            self.app.set_microphones(new)
            self.shown()

        def forget(i):
            self.app.set_microphones(order[:i] + order[i + 1:])
            self.shown()

        rows = []
        for i, (name, label) in enumerate(order):
            buttons = Gtk.Box(spacing=4)
            for icon, by, tip in (("up", -1, "Move {} up"), ("down", 1, "Move {} down")):
                b = d.icon_button(icon, tip.format(label), lambda i=i, by=by: move(i, by))
                b.set_sensitive(0 <= i + by < len(order))
                buttons.pack_start(b, False, False, 0)
            if name not in connected:
                buttons.pack_start(d.icon_button("trash", f"Forget {label}", lambda i=i: forget(i)), False, False, 0)
            rows.append((connected.get(name, label),
                         "In use" if name == mic else "Connected" if name in connected else "Not connected", buttons))
        return rows
