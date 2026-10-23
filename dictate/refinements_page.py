"""The Refinements page: the cleanup prompt every dictation gets, the vocabulary, the live summary's prompt,
and the refinements, with an editor for the one selected."""

from gi.repository import Gtk

from . import design as d
from . import huds, refinements, summary


class RefinementsPage:
    """The cleanup every dictation gets, the vocabulary, and the refinements: a list, and an editor for the
    one selected."""
    FIXED = 3  # list rows before the refinements: Cleanup, Vocabulary, Live summary
    DEFAULTS = {0: lambda: refinements.CLEANUP, 2: lambda: summary.PROMPT}  # what Reset to default puts back

    def __init__(self, hub):
        self.hub, self.data, self.i = hub, refinements.load(), 0
        self.widget = d.page_box()
        self.widget.pack_start(d.page_header("Refinements"), False, False, 0)
        body = Gtk.Box(spacing=0, margin_start=12, margin_end=24, margin_bottom=24)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200, spacing=8)
        self.list = d.classes(Gtk.ListBox(), "pick")
        self.list.connect("row-selected", lambda _, row: row and self.picked(row.get_index()))
        self.rebuilding = False
        left.pack_start(self.list, False, False, 0)
        new = d.button("New refinement", self.add, "quiet", icon="plus")
        new.set_halign(Gtk.Align.START)
        new.set_margin_start(8)
        left.pack_start(new, False, False, 0)
        body.pack_start(left, False, False, 0)

        self.title = d.text("", "title")
        self.delete_btn = d.button("Delete", self.remove, "danger")
        self.reset_btn = d.button("Reset to default",
                                  lambda: self.prompt.get_buffer().set_text(self.DEFAULTS[self.i]()), "quiet")
        self.saved = d.text("", "small")
        top = Gtk.Box(spacing=8)
        top.pack_start(self.title, True, True, 0)
        for b in (self.saved, self.reset_btn, self.delete_btn, d.button("Save", self.save, "primary")):
            top.pack_start(b, False, False, 0)

        self.name, self.key = Gtk.Entry(hexpand=True), Gtk.Entry(max_length=1, width_chars=3)
        self.apps = Gtk.Entry(placeholder_text="e.g. slack, discord")
        self.fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        names = Gtk.Box(spacing=12)
        names.pack_start(d.field("Name", self.name), True, True, 0)
        names.pack_start(d.field("Letter", self.key), False, False, 0)
        self.fields.pack_start(names, False, False, 0)
        self.fields.pack_start(d.field("Use automatically in apps", self.apps,
                                       "Matched against the focused app's name and window title."), False, False, 0)
        self.hint = d.text("", "small", wrap=True)
        self.prompt = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, left_margin=12, right_margin=12, top_margin=10,
                                   bottom_margin=10)
        editor = d.classes(d.scrolled(self.prompt), "editor")
        self.error = d.text("", "small")
        self.error.get_style_context().add_class("danger-text")
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=24)
        for w, grow in ((top, False), (self.fields, False), (self.hint, False), (editor, True), (self.error, False)):
            form.pack_start(w, grow, grow, 0)
        body.pack_start(d.hairline(vertical=True), False, False, 0)
        body.pack_start(form, True, True, 0)
        self.widget.pack_start(body, True, True, 0)
        self.rebuild(0)

    def shown(self, new=False, on_change=None, **_):
        self.on_change = on_change
        if not self.dirty():  # (unsaved changes stay while you look at another page)
            self.show(self.i)  # (what's hidden for the one selected)
        if new:
            self.add()

    def saved_text(self, i):
        return [lambda: self.data["cleanup"], refinements.load_vocab, summary.prompt][i]() if i < self.FIXED \
            else self.data["refinements"][i - self.FIXED]["prompt"]

    def dirty(self):
        """Whether what's in the editor differs from what's saved."""
        text = self.prompt.get_buffer().props.text
        if self.i < self.FIXED:
            return text != self.saved_text(self.i)
        s = self.data["refinements"][self.i - self.FIXED]
        return (self.name.get_text(), self.key.get_text().lower(), self.apps.get_text(), text) != \
            (s.get("name", ""), s.get("key", ""), s.get("apps", ""), s.get("prompt", ""))

    def leave(self):
        """Before the one shown is left: if it has unsaved changes, ask whether to save them. False: stay on it."""
        if self.dirty():
            answer = huds.ask_save(self.hub.win, self.title.get_text())
            if answer == "save" and not self.save():
                return False  # (it says what's missing)
            if answer is None:
                return False
        if self.i >= self.FIXED and not self.data["refinements"][self.i - self.FIXED]["key"]:  # a new one, never saved
            del self.data["refinements"][self.i - self.FIXED]
        return True

    def picked(self, i):
        if self.rebuilding or i == self.i:
            return
        if self.leave():
            self.rebuild(i)
        else:  # back to the one with the changes, as it is
            self.rebuilding = True
            self.list.select_row(self.list.get_row_at_index(self.i))
            self.rebuilding = False

    def rebuild(self, select):
        self.rebuilding = True
        for row in self.list.get_children():
            self.list.remove(row)
        rows = [("Cleanup", None), ("Vocabulary", None), ("Live summary", None)] + \
            [(s["name"], s["key"]) for s in self.data["refinements"]]
        for name, key in rows:
            box = Gtk.Box(spacing=8, margin=8)
            box.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            if key:
                box.pack_end(d.key_badge(key), False, False, 0)
            self.list.add(box)
        self.list.show_all()
        self.list.select_row(self.list.get_row_at_index(select))
        self.rebuilding = False
        self.show(select)

    def show(self, i):
        self.i = i
        refinement = self.data["refinements"][i - self.FIXED] if i >= self.FIXED else {}
        self.title.set_text(["Cleanup", "Vocabulary", "Live summary"][i] if i < self.FIXED
                            else refinement.get("name") or "New refinement")
        text = self.saved_text(i)
        self.fields.set_visible(i >= self.FIXED)
        self.delete_btn.set_visible(i >= self.FIXED)
        self.reset_btn.set_visible(i in self.DEFAULTS)
        self.name.set_text(refinement.get("name", ""))
        self.key.set_text(refinement.get("key", "").upper())
        self.apps.set_text(refinement.get("apps", ""))
        self.prompt.get_buffer().set_text(text)
        self.error.set_text("")
        self.saved.set_text("")
        self.hint.set_text([
            "Always applied first, to every dictation. Keep it to light clean-up.",
            "Names and terms you use, one per line (people, products, jargon). Cleanup prefers these spellings "
            "and fixes similar-sounding mis-hearings of them.",
            "How the live summary of a transcribed call is written: kept up to date every few minutes, with a final "
            "pass when it's stopped. Say what it should cover and how.",
        ][i] if i < self.FIXED else
            "Applied after cleanup: hold Ctrl+Win and press Alt and its letter, or tap Alt to choose afterwards. "
            "Also used automatically when you dictate into a matching app. Describe the refinement and give an example "
            "or two.")

    def add(self):
        if not self.leave():
            return
        self.data["refinements"].append({"name": "New refinement", "key": "", "apps": "", "prompt": ""})
        self.rebuild(len(self.data["refinements"]) + self.FIXED - 1)
        self.name.grab_focus()

    def fresh_defaults(self):
        """Take the default refinements (here and on another computer) from the file: Settings and the menu
        change them there, after this page read it."""
        data = refinements.load()
        default = next((s["name"] for s in data["refinements"] if s.get("default")), None)
        for s in self.data["refinements"]:
            s["default"] = s["name"] == default
        self.data.pop("remote_default", None)
        if "remote_default" in data:
            self.data["remote_default"] = data["remote_default"]

    def save(self):
        self.fresh_defaults()
        text = self.prompt.get_buffer().props.text.strip()
        if self.i == 0:
            self.data["cleanup"] = text
        elif self.i == 1:
            refinements.save_vocab(text)
        elif self.i == 2:
            summary.save_prompt(text)
        else:
            j = self.i - self.FIXED
            name, key = self.name.get_text().strip(), self.key.get_text().lower()
            others = [s["key"] for k, s in enumerate(self.data["refinements"]) if k != j]
            err = ("Give the refinement a name." if not name else
                   "Choose a letter A–Z." if not (key.isascii() and key.isalpha()) else
                   f"{key.upper()} is already used by another refinement." if key in others else
                   "Describe the refinement." if not text else "")
            if err:
                return self.error.set_text(err)
            if self.data.get("remote_default") == self.data["refinements"][j]["name"]:  # follow a rename
                self.data["remote_default"] = name
            self.data["refinements"][j].update(name=name, key=key, apps=self.apps.get_text().strip(), prompt=text)
        refinements.save({**self.data,
                          "refinements": [s for s in self.data["refinements"] if s["key"]]})  # skip unsaved new
        self.rebuild(self.i)
        self.saved.set_text("Saved")
        if self.on_change:
            self.on_change()
        return True

    def remove(self):
        self.fresh_defaults()
        del self.data["refinements"][self.i - self.FIXED]
        refinements.save(self.data)
        self.rebuild(0)
        if self.on_change:
            self.on_change()

    on_change = None
