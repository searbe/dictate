"""The Dictate window: one home for everything but the capsule and a moment's HUD (docs/design/DESIGN.md). A
sidebar of pages (Dictations, Transcripts, Styles, Voices, Settings); the window's title is the page shown. Pages
are built when first shown, and told each time they're shown again (so Dictations shows the latest)."""
import json
from datetime import datetime, timedelta
from gi.repository import Gdk, GLib, Gtk
from . import design as d, huds, refine, summary, transcript, voices
from .transcripts_page import TranscriptsPage

PAGES = (("dictations", "Dictations", "history"), ("transcripts", "Transcripts", "transcript"),
         ("styles", "Styles", "styles"), ("voices", "Voices", "voices"), ("settings", "Settings", "settings"))


class Hub:
    """app: the App (its settings, player, and what it's transcribing)."""

    def __init__(self, app):
        self.app, self.pages, self.page = app, {}, None
        self.win = d.classes(Gtk.Window(title="Dictate", default_width=1120, default_height=680), "dictate")
        bar = Gtk.HeaderBar(show_close_button=True)
        bar.set_custom_title(Gtk.Box())  # the page says what it is; the bar only holds the window's buttons
        self.win.set_titlebar(bar)
        bar.show_all()  # (else there's no title bar at all: nothing to close or drag the window by)
        self.win.connect("destroy", lambda *_: setattr(self, "closed", True))
        self.closed = False

        side = self.side = d.classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200, hexpand=False), "sidebar")
        self.wide_only = [d.classes(Gtk.Label(label="Dictate", xalign=0), "app-name")]  # hidden while compact
        side.pack_start(self.wide_only[0], False, False, 0)
        self.nav = d.classes(Gtk.ListBox(), "nav")
        for key, title, icon in PAGES:
            if key == "voices" and not voices.available():
                continue
            row = Gtk.ListBoxRow()
            row.key = key
            box = Gtk.Box(spacing=10)
            box.pack_start(Icon(icon), False, False, 0)
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
            self.pages[key] = page = {"dictations": DictationsPage, "transcripts": TranscriptsPage, "styles": StylesPage,
                                      "voices": VoicesPage, "settings": SettingsPage}[key](self)
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


def Icon(name):
    return d.Icon(name)


def page_box():
    return d.classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "page")


def page_header(title, *actions, subtitle=None, clamp=None):
    """The page's headline at left, its actions at right; at most clamp px wide (the page's column), centred."""
    row = d.classes(Gtk.Box(spacing=8), "page-header")
    words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    words.pack_start(d.text(title, "headline", ellipsize=True), False, False, 0)
    if subtitle:
        words.pack_start(subtitle, False, False, 0)
    row.pack_start(words, True, True, 0)
    for a in reversed(actions):
        row.pack_end(a, False, False, 0)
    return d.Clamp(row, clamp) if clamp else row


# --- dictations ---
def day(when):
    today = datetime.now().date()
    return "Today" if when.date() == today else "Yesterday" if when.date() == today - timedelta(days=1) \
        else f"{when:%a %-d %b}" if when.year == today.year else f"{when:%a %-d %b %Y}"


def applied(it):
    """What was done to an entry's text, e.g. ["Cleanup", "Slack"]."""
    return ["Cleanup" if it["cleanup"] else "Raw transcript"] + ([it["style"]] if "style" in it else [])


def steps(it):
    """{label: (title, before, after)}: what each step of an entry did to its text, where it's known (an entry
    with a style keeps the cleaned-up text in between since 22 Oct 2026)."""
    out, styled, cleaned = {}, "style" in it, it.get("cleaned")
    if it["cleanup"] and (cleaned is not None or not styled):
        out["Cleanup"] = ("What cleanup changed", it.get("raw", it["text"]), cleaned if styled else it["text"])
    if styled and cleaned is not None:
        out[it["style"]] = (f"What {it['style']} changed", cleaned, it["text"])
    return out


class DictationsPage:
    """Every dictation, newest first, grouped by day; search; on hover: Play, Copy, Copy original, Delete."""
    EMPTY = "Nothing dictated yet"

    def __init__(self, hub):
        self.hub, self.app = hub, hub.app
        self.search = Gtk.SearchEntry(placeholder_text="Search", width_chars=12)
        self.search.connect("search-changed", lambda *_: (self.list.invalidate_filter(), self.list.invalidate_headers()))
        self.widget = page_box()
        self.widget.pack_start(page_header("Dictations", self.search, d.button("Clear all…", self.clear, "danger")),
                               False, False, 0)
        self.list = d.classes(Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE), "dictations")
        self.list.set_filter_func(lambda row: self.search.get_text().lower() in getattr(row, "text", "").lower())
        self.list.set_header_func(self.header)
        self.empty = d.empty_state("history", self.EMPTY, "Hold Ctrl+Win, speak, and let go: what you said is pasted, "
                                                         "and kept here.")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_bottom=16)
        inner.pack_start(self.list, False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.add_named(d.scrolled(inner), "list")
        self.stack.add_named(self.empty, "empty")
        self.widget.pack_start(self.stack, True, True, 0)
        self.hub.win.connect("destroy", lambda *_: self.app.player.stop())

    @property
    def path(self):
        return self.app.DICTATIONS

    FIRST, BATCH = 40, 60  # rows shown at once, then added a batch at a time while idle

    def shown(self, **_):
        stamp = self.path.stat().st_mtime_ns if self.path.exists() else None
        if stamp != getattr(self, "stamp", 0):  # (only when something's been dictated or deleted since)
            self.stamp = stamp
            self.load()

    def load(self):
        """The newest entries at once, the rest a batch at a time (hundreds of rows of wrapped text take a
        second to lay out)."""
        for row in self.list.get_children():
            self.list.remove(row)
        lines = self.path.read_text().splitlines() if self.path.exists() else []
        self.pending = list(reversed(lines))
        self.more(self.FIRST)
        self.refresh_empty()
        if self.pending:
            GLib.idle_add(lambda: self.more(self.BATCH))

    def more(self, n):
        """Add the next n entries; returns whether there are more to add (so idle_add carries on)."""
        batch, self.pending = self.pending[:n], self.pending[n:]
        for line in batch:
            try:
                row = self.row(json.loads(line), line)
            except (ValueError, KeyError):
                continue
            self.list.add(row)
            row.show_all()
        return bool(self.pending) and not self.hub.closed

    def refresh_empty(self):
        self.stack.show_all()
        self.stack.set_visible_child_name("list" if self.list.get_children() else "empty")

    def header(self, row, before):
        if before is None or before.day != row.day:
            row.set_header(d.group_header(row.day))
        else:
            row.set_header(None)

    def row(self, it, line):
        when = datetime.fromisoformat(it["t"])
        row = Gtk.ListBoxRow(activatable=False)
        row.text, row.line, row.day = it["text"], line, day(when)
        row.audio = self.app.AUDIO / it["audio"] if it.get("audio") else None
        item = d.classes(Gtk.Box(spacing=12), "row-item")
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        meta = Gtk.Box(spacing=6)
        meta.pack_start(d.text(" · ".join(filter(None, (f"{when:%H:%M}", it.get("app")))), "caption"), False, False, 0)
        known = steps(it)
        for label in applied(it):
            if label in known:
                chip = d.step_chip(label, lambda l=label: self.show_step(row, l), f"See what {label.lower() if label == 'Cleanup' else label} changed")
                row.chips = getattr(row, "chips", {}) | {label: chip}
                meta.pack_start(chip, False, False, 0)
            else:
                meta.pack_start(d.chip(label), False, False, 0)
        row.steps, row.step, row.words = known, None, words
        words.pack_start(meta, False, False, 0)
        words.pack_start(d.text(it["text"], "body", wrap=True, selectable=True), False, False, 0)
        item.pack_start(words, True, True, 0)

        actions = d.classes(Gtk.Box(spacing=2, valign=Gtk.Align.START), "actions")
        play = d.icon_button("play", "Play", lambda: self.play(row, play))
        play.icon.show()  # (no_show_all: shown only while its recording exists; its icon is shown regardless)
        play.set_no_show_all(True)
        actions.pack_start(play, False, False, 0)
        row.refresh_audio = lambda: (play.set_visible(bool(row.audio and row.audio.exists())), play.get_visible())[1]
        row.refresh_audio()
        copy = d.icon_button("copy", "Copy", lambda: (self.app.copy(it["text"]), d.flash(copy, "Copied", "Copy", "copy")))
        actions.pack_start(copy, False, False, 0)
        if it.get("raw"):
            orig = d.icon_button("undo", "Copy original", lambda: (self.app.copy(it["raw"]),
                                                               d.flash(orig, "Copied", "Copy original", "undo")))
            actions.pack_start(orig, False, False, 0)
        actions.pack_start(d.icon_button("trash", "Delete", lambda: self.delete(row), danger=True), False, False, 0)
        item.pack_end(actions, False, False, 0)
        row.add(item)
        return row

    def show_step(self, row, label):
        """Show (or, clicked again, hide) what step label did to the row's text, under it."""
        if not hasattr(row, "revealer"):
            row.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                                        transition_duration=int(d.FADE * 1000) if d.animations() else 0, margin_top=6)
            row.words.pack_start(row.revealer, False, False, 0)
        opening = row.step != label
        for name, chip in row.chips.items():
            chip.on(opening and name == label)
        if opening:
            if row.revealer.get_child():
                row.revealer.remove(row.revealer.get_child())
            row.revealer.add(d.step_card(*row.steps[label]))
            row.revealer.show_all()
        row.revealer.set_reveal_child(opening)
        row.step = label if opening else None

    def play(self, row, btn):
        if btn.get_tooltip_text() == "Stop":
            return self.app.player.stop()
        if not row.refresh_audio():  # deleted since (e.g. it got too old)
            return
        btn.icon.set_icon("stop")
        btn.set_tooltip_text("Stop")
        btn.get_parent().get_style_context().add_class("shown")  # keep the Stop button showing while it plays

        def done():
            btn.icon.set_icon("play")
            btn.set_tooltip_text("Play")
            btn.get_parent().get_style_context().remove_class("shown")
        self.app.player.play(str(row.audio), done)

    def delete(self, row):
        """Remove one entry from the history file, and its recording."""
        self.app.player.stop()
        keep = self.path.read_text().splitlines()
        if row.line in keep:
            keep.remove(row.line)
            self.path.write_text("".join(l + "\n" for l in keep))
        if row.audio:
            row.audio.unlink(missing_ok=True)
        self.list.remove(row)
        self.stamp = self.path.stat().st_mtime_ns
        self.refresh_empty()

    def clear(self):
        n = len(self.list.get_children())
        if not n or not huds.confirm(self.hub.win, f"Delete all {n} dictations and their recordings?",
                                     "This can't be undone.", "Delete all"):
            return
        self.app.player.stop()
        for wav in self.app.AUDIO.glob("*.wav"):  # (the recordings first: once the list is empty, they're gone)
            wav.unlink(missing_ok=True)
        self.path.write_text("")
        self.load()

    def recordings_changed(self):
        for row in self.list.get_children():
            row.refresh_audio()


# --- styles ---
class StylesPage:
    """The cleanup every dictation gets, the vocabulary, and the refinement styles: a list, and an editor for the
    one selected."""
    FIXED = 3  # list rows before the styles: Cleanup, Vocabulary, Live summary
    DEFAULTS = {0: lambda: refine.CLEANUP, 2: lambda: summary.PROMPT}  # what Reset to default puts back

    def __init__(self, hub):
        self.hub, self.data, self.i = hub, refine.load_styles(), 0
        self.widget = page_box()
        self.widget.pack_start(page_header("Styles"), False, False, 0)
        body = Gtk.Box(spacing=0, margin_start=12, margin_end=24, margin_bottom=24)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200, spacing=8)
        self.list = d.classes(Gtk.ListBox(), "pick")
        self.list.connect("row-selected", lambda _, row: row and self.show(row.get_index()))
        left.pack_start(self.list, False, False, 0)
        new = d.button("New style", self.add, "quiet", icon="plus")
        new.set_halign(Gtk.Align.START)
        new.set_margin_start(8)
        left.pack_start(new, False, False, 0)
        body.pack_start(left, False, False, 0)

        self.title = d.text("", "title")
        self.delete_btn = d.button("Delete", self.remove, "danger")
        self.reset_btn = d.button("Reset to default", lambda: self.prompt.get_buffer().set_text(self.DEFAULTS[self.i]()),
                                  "quiet")
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
        self.show(self.i)  # (what's hidden for the one selected)
        if new:
            self.add()

    def rebuild(self, select):
        for row in self.list.get_children():
            self.list.remove(row)
        rows = [("Cleanup", None), ("Vocabulary", None), ("Live summary", None)] + \
            [(s["name"], s["key"]) for s in self.data["styles"]]
        for name, key in rows:
            box = Gtk.Box(spacing=8, margin=8)
            box.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            if key:
                box.pack_end(d.key_badge(key), False, False, 0)
            self.list.add(box)
        self.list.show_all()
        self.list.select_row(self.list.get_row_at_index(select))

    def show(self, i):
        self.i = i
        style = self.data["styles"][i - self.FIXED] if i >= self.FIXED else {}
        self.title.set_text(["Cleanup", "Vocabulary", "Live summary"][i] if i < self.FIXED else style.get("name") or "New style")
        text = [lambda: self.data["cleanup"], refine.load_vocab, summary.prompt][i]() if i < self.FIXED else style["prompt"]
        self.fields.set_visible(i >= self.FIXED)
        self.delete_btn.set_visible(i >= self.FIXED)
        self.reset_btn.set_visible(i in self.DEFAULTS)
        self.name.set_text(style.get("name", ""))
        self.key.set_text(style.get("key", "").upper())
        self.apps.set_text(style.get("apps", ""))
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
            "Also used automatically when you dictate into a matching app. Describe the style and give an example "
            "or two.")

    def add(self):
        self.data["styles"].append({"name": "New style", "key": "", "apps": "", "prompt": ""})
        self.rebuild(len(self.data["styles"]) + self.FIXED - 1)
        self.name.grab_focus()

    def save(self):
        text = self.prompt.get_buffer().props.text.strip()
        if self.i == 0:
            self.data["cleanup"] = text
        elif self.i == 1:
            refine.save_vocab(text)
        elif self.i == 2:
            summary.save_prompt(text)
        else:
            j = self.i - self.FIXED
            name, key = self.name.get_text().strip(), self.key.get_text().lower()
            others = [s["key"] for k, s in enumerate(self.data["styles"]) if k != j]
            err = ("Give the style a name." if not name else
                   "Choose a letter A–Z." if not (key.isascii() and key.isalpha()) else
                   f"{key.upper()} is already used by another style." if key in others else
                   "Describe the style." if not text else "")
            if err:
                return self.error.set_text(err)
            if self.data.get("remote_default") == self.data["styles"][j]["name"]:  # follow a rename
                self.data["remote_default"] = name
            self.data["styles"][j].update(name=name, key=key, apps=self.apps.get_text().strip(), prompt=text)
        refine.save_styles({**self.data, "styles": [s for s in self.data["styles"] if s["key"]]})  # skip unsaved new
        self.rebuild(self.i)
        self.saved.set_text("Saved")
        if self.on_change:
            self.on_change()

    def remove(self):
        del self.data["styles"][self.i - self.FIXED]
        refine.save_styles(self.data)
        self.rebuild(0)
        if self.on_change:
            self.on_change()

    on_change = None


# --- voices ---
class VoicesPage:
    """Remembering voices (opt-in) and the voices remembered, each of which can be forgotten."""
    EXPLAIN = ("Dictate keeps a voiceprint of each person you name in a transcript, on this computer only, and names "
               "them in later transcripts. A voiceprint can identify someone: ask people first. Turning this off "
               "forgets every voice.")

    def __init__(self, hub):
        self.hub = hub
        self.widget = page_box()
        self.widget.pack_start(page_header("Voices", clamp=560), False, False, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=24, margin_end=24)
        self.toggle = Gtk.Switch(active=voices.remembering())
        self.toggle.connect("notify::active", lambda *_: self.toggled())
        body.pack_start(d.setting_row("Remember voices I name", self.EXPLAIN, self.toggle), False, False, 0)
        body.pack_start(d.hairline(), False, False, 0)
        body.pack_start(d.classes(Gtk.Label(label="Remembered voices", xalign=0, margin_top=16, margin_bottom=8), "title"),
                        False, False, 0)
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
            row.pack_end(d.button("Forget", lambda n=name: (voices.forget(n), self.refresh()), "danger", small=True), False, False, 0)
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


# --- settings ---
class SettingsPage:
    """Everything that's otherwise in the menu, in one place."""

    def __init__(self, hub):
        self.hub, self.app = hub, hub.app
        self.widget = page_box()
        self.widget.pack_start(page_header("Settings", clamp=640), False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=24, margin_end=24)
        self.widget.pack_start(d.scrolled(d.Clamp(self.body, 640)), True, True, 0)

    def shown(self, **_):
        for kid in self.body.get_children():
            kid.destroy()
        app, cfg = self.app, self.app.cfg
        styles = [s["name"] for s in refine.load_styles()["styles"]]
        here = refine.default_style()
        data = refine.load_styles()
        there = data.get("remote_default", app.SAME)
        rows = [
            ("Dictation",),
            ("Refine text", "Clean up filler words, corrections and punctuation with a local model. Off pastes exactly "
                            "what was heard.", switch(cfg["refine"], app.set_refine)),
            ("Default style", "Applied after cleanup to every dictation that no app's style matches.",
             combo([(None, "None (cleanup only)")] + [(n, n) for n in styles], here and here["name"], refine.set_default)),
            ("Recordings",),
            ("Keep dictation recordings", "How long each dictation's audio is kept, to play back from Dictations. "
                                          "Its text is kept until you delete it.",
             combo(list(app.KEEP_AUDIO), cfg["keep_audio_hours"], app.set_keep_audio)),
            ("Keep call recordings", "How long a transcribed call's audio is kept, to play back from Transcripts. "
                                     "The transcript is kept until you delete it.",
             combo(list(app.KEEP_AUDIO), cfg["keep_call_hours"], app.set_keep_calls)),
            ("Another computer",),
            ("When it has the keyboard", "When your keyboard controls another computer (Synergy and similar).",
             combo(list(app.REMOTE_MODES), cfg["remote_mode"], lambda m: app.save_state(remote_mode=m))),
            ("Default style there", "Its apps can't be seen from here, so this is used for everything.",
             combo([(app.SAME, "Same as here"), (None, "None (cleanup only)")] + [(n, n) for n in styles],
                   there if there in [app.SAME, None, *styles] else None,
                   lambda v: refine.set_remote_default(v, same=v is app.SAME))),
            ("Startup",),
            ("Run at startup", "Start Dictate when you log in.", switch(app.autostart(), app.set_autostart)),
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
