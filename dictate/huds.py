"""HUDs: a moment's question or notice, on one card (docs/design/DESIGN.md, "HUD card"): the refinement picker after
Ctrl+Win with Alt, the confirmations, naming a voice, and the reminder that a call is still being transcribed."""
import cairo
from gi.repository import Gdk, Gtk

from . import design as d
from . import refinements, transcript


# --- dialogs: a HUD card that waits for an answer ---
class HudDialog(Gtk.Dialog):
    """A modal Gtk.Dialog drawn as a HUD card: run() returns the response."""

    def __init__(self, parent, title):
        super().__init__(transient_for=parent, modal=True, decorated=False, title=title)
        d.classes(self, "hud-window")
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        d.grayscale(self)
        self.connect("draw", lambda w, cr: (cr.set_operator(cairo.OPERATOR_SOURCE), cr.set_source_rgba(0, 0, 0, 0),
                                            cr.paint(), cr.set_operator(cairo.OPERATOR_OVER)) and False)
        self.connect("map-event", lambda w, _: d.blur_behind(w, self.card) and False)
        self.get_action_area().hide()
        self.get_action_area().set_no_show_all(True)
        area = self.get_content_area()
        area.set_border_width(0)
        self.card = d.classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=360), "hud")
        area.pack_start(self.card, True, True, 0)

    def answer(self, label, response, kind="secondary", default=False):
        b = d.button(label, lambda: self.response(response), kind)
        if default:
            self.set_default_response(response)
        return b

    def finish(self, *buttons):
        row = Gtk.Box(spacing=8, margin_top=4)
        for b in reversed(buttons):
            row.pack_end(b, False, False, 0)
        self.card.pack_start(row, False, False, 0)
        self.card.show_all()


def confirm(parent, question, detail, action="Delete all"):
    """Ask before something that can't be undone: Cancel, or action (in danger red). Returns True for action."""
    dialog = HudDialog(parent, question)
    dialog.card.pack_start(d.text(question, "title", wrap=True, max_chars=40), False, False, 0)
    dialog.card.pack_start(d.text(detail, "small", wrap=True, max_chars=50), False, False, 0)
    dialog.finish(dialog.answer("Cancel", Gtk.ResponseType.CANCEL),
                  dialog.answer(action, Gtk.ResponseType.OK, "danger"))
    answer = dialog.run()
    dialog.destroy()
    return answer == Gtk.ResponseType.OK


def ask_save(parent, name):
    """Ask before unsaved changes to name are lost: "save", "discard", or None to go back to them (Cancel, Escape)."""
    question = f"Save your changes to {name}?"
    dialog = HudDialog(parent, question)
    dialog.card.pack_start(d.text(question, "title", wrap=True, max_chars=40), False, False, 0)
    dialog.card.pack_start(d.text("They haven't been saved yet.", "small", wrap=True, max_chars=50), False, False, 0)
    dialog.finish(dialog.answer("Cancel", Gtk.ResponseType.CANCEL),
                  dialog.answer("Don't save", Gtk.ResponseType.REJECT),
                  dialog.answer("Save", Gtk.ResponseType.OK, "primary", default=True))
    answer = dialog.run()
    dialog.destroy()
    return {Gtk.ResponseType.OK: "save", Gtk.ResponseType.REJECT: "discard"}.get(answer)


def ask_name(parent, label, remembers):
    """Ask what a voice is called. remembers: whether naming it remembers the voice for later transcripts."""
    dialog = HudDialog(parent, f"Who is {label}?")
    dialog.card.pack_start(d.text(f"Who is {label}?", "title"), False, False, 0)
    entry = Gtk.Entry(placeholder_text="Name", activates_default=True)
    if not label.startswith("Speaker "):
        entry.set_text(label)
    dialog.card.pack_start(entry, False, False, 0)
    dialog.card.pack_start(d.text("Dictate will remember this voice and name it in later transcripts." if remembers
                                  else "Naming two voices the same makes them one person.", "small", wrap=True,
                                  max_chars=50), False, False, 0)
    dialog.finish(dialog.answer("Cancel", Gtk.ResponseType.CANCEL),
                  dialog.answer("Rename", Gtk.ResponseType.OK, "primary", default=True))
    answer, name = dialog.run(), entry.get_text()
    dialog.destroy()
    return transcript.clean_name(name) if answer == Gtk.ResponseType.OK else ""


# --- the refinement picker (after Ctrl+Win with Alt tapped) ---
class RefinementPicker:
    """Shows the cleaned-up text, then calls on_choose(refinement, paste): refinement is None for "Paste as is", paste
    is False after Esc (the text is kept in history and on the clipboard only). on_new() opens Refinements to add
    one."""

    def __init__(self, text, on_choose, on_new=lambda: None):
        self.on_choose = on_choose
        self.hud = d.Hud("Refine", width=420)
        self.hud.on_escape = lambda: self.choose(None, paste=False)
        self.hud.win.connect("key-press-event", self.on_key)
        self.hud.heading("Pick a refinement", "refinements")
        quote = d.classes(Gtk.Box(), "quote")
        said = d.text(text, "body", wrap=True, max_chars=56, selectable=True)
        said.set_can_focus(False)  # (else it opens with its text selected)
        quote.pack_start(said, True, True, 0)
        self.hud.box.pack_start(quote, False, False, 0)
        self.choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.hud.box.pack_start(self.choices, False, False, 0)
        self.refresh()
        new = d.button("New refinement…", lambda: (self.choose(None, paste=False, keep=True), on_new()), "quiet",
                       icon="plus")
        foot = self.hud.buttons(d.button("Paste as is", lambda: self.choose(None), "primary", keyhint="Enter"))
        foot.pack_start(new, False, False, 0)
        foot.pack_start(d.text("Esc copies only", "caption"), False, False, 8)
        self.hud.show()

    @property
    def win(self):
        return self.hud.win

    def refresh(self):
        for c in self.choices.get_children():
            self.choices.remove(c)
        self.refinements = refinements.load()["refinements"]
        for s in self.refinements:
            row = Gtk.Box(spacing=10)
            row.pack_start(d.key_badge(s["key"]), False, False, 0)
            row.pack_start(Gtk.Label(label=s["name"], xalign=0), True, True, 0)
            b = d.classes(Gtk.Button(), "choice")
            b.add(row)
            b.connect("clicked", lambda _, s=s: self.choose(s))
            self.choices.add(b)
        self.choices.show_all()

    def on_key(self, _, ev):
        name = Gdk.keyval_name(ev.keyval)
        if name in ("Return", "KP_Enter"):
            self.choose(None)
        else:
            s = next((s for s in self.refinements if s["key"] == name.lower()), None)
            if s:
                self.choose(s)
        return False

    def choose(self, refinement, paste=True, keep=False):
        self.hud.close()
        self.on_choose(refinement, paste)


# --- still transcribing ---
STOP_WAYS = ("Stop, in Transcripts (click the capsule to open it)", "Ctrl+Win, lift Win and press it again",
             "Stop transcribing, in the capsule's menu")
REMINDERS = {  # why: (heading, what's happening)
    "closed": ("Still transcribing", "Closing the window doesn't stop it: everything said through this computer's "
                                     "speakers and microphone is still being written down."),
    "quiet": ("Nothing heard for {minutes} minutes", "Dictate is still transcribing. If the call is over, stop it, or "
                                                     "it will carry on recording whatever is said here."),
}


def reminder_text(why, minutes):
    heading, body = REMINDERS[why]
    return heading.format(minutes=minutes), body


class StillTranscribing:
    """A HUD beside the capsule saying a call is still being transcribed, with a picture of the capsule as it looks
    while it is (picture: a pixbuf), every way to stop, and Stop now / Keep going."""

    def __init__(self, why, minutes, picture, beside, on_stop):
        """beside: (x, y, width, height) of the capsule on screen."""
        heading, body = reminder_text(why, minutes)
        self.hud = d.Hud("Still transcribing", width=400, warning=True)
        self.hud.on_escape = self.close
        self.hud.heading(heading, "warning", warning=True)
        self.hud.box.pack_start(d.text(body, "body", wrap=True, max_chars=52), False, False, 0)
        icon = Gtk.Box(spacing=12)
        icon.pack_start(Gtk.Image.new_from_pixbuf(picture), False, False, 0)
        icon.pack_start(d.text("This capsule means it's transcribing. Click it to see the transcript.", "small",
                               wrap=True, max_chars=36), True, True, 0)
        self.hud.box.pack_start(icon, False, False, 0)
        ways = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        ways.pack_start(d.classes(Gtk.Label(label="To stop it:", xalign=0), "field-label"), False, False, 0)
        for way in STOP_WAYS:
            ways.pack_start(d.text(f"•  {way}", "small", wrap=True, max_chars=52), False, False, 0)
        self.hud.box.pack_start(ways, False, False, 0)
        self.hud.buttons(d.button("Keep going", self.close),
                         d.button("Stop now", lambda: (on_stop(), self.close()), "primary"))
        self.hud.show(near=beside)

    @property
    def win(self):
        return self.hud.win

    def close(self):
        self.hud.close()

    @property
    def open(self):
        return self.hud.open
