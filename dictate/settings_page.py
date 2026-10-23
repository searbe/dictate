"""The Settings page: everything that's otherwise in the capsule's menu, in one place."""

from gi.repository import Gtk

from . import design as d
from . import refinements
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
        rows = [
            ("Dictation",),
            ("Refine text", "Cleanup, then the refinement for the app you're dictating into (or the default), with a "
                            "local model. Off pastes exactly what was heard; Alt still picks a refinement.",
             d.switch(cfg["refine"], app.set_refine)),
            ("Default refinement", "Applied after cleanup to every dictation that no app's refinement matches.",
             d.combo([(None, "None (cleanup only)")] + [(n, n) for n in names], here and here["name"],
                     refinements.set_default)),
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
            ("Startup",),
            ("Run at startup", "Start Dictate when you log in.", d.switch(app.autostart(), app.set_autostart)),
        ]
        first = True
        for title, *rest in rows:
            if not rest:
                self.body.pack_start(d.classes(Gtk.Label(label=title, xalign=0, margin_top=8 if first else 24,
                                                         margin_bottom=4), "title"), False, False, 0)
                first = False
                continue
            self.body.pack_start(d.setting_row(title, *rest), False, False, 0)
            self.body.pack_start(d.hairline(), False, False, 0)
        self.body.show_all()
