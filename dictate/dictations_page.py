"""The Dictations page: every dictation, newest first, grouped by day, with what each step (cleanup, a
refinement) changed, and its recording to play back."""

import json
from datetime import datetime, timedelta

from gi.repository import GLib, Gtk

from . import design as d
from . import history, huds


def day(when):
    today = datetime.now().date()
    return "Today" if when.date() == today else "Yesterday" if when.date() == today - timedelta(days=1) \
        else f"{when:%a %-d %b}" if when.year == today.year else f"{when:%a %-d %b %Y}"


def applied(it):
    """What was done to an entry's text, e.g. ["Cleanup", "Slack"]."""
    return ["Cleanup" if it["cleanup"] else "Raw transcript"] + ([it["refinement"]] if "refinement" in it else [])


def steps(it):
    """{label: (title, before, after)}: what each step of an entry did to its text, where it's known (an entry
    with a refinement keeps the cleaned-up text in between since 22 Oct 2026)."""
    out, refined, cleaned = {}, "refinement" in it, it.get("cleaned")
    if it["cleanup"] and (cleaned is not None or not refined):
        out["Cleanup"] = ("What cleanup changed", it.get("raw", it["text"]), cleaned if refined else it["text"])
    if refined and cleaned is not None:
        out[it["refinement"]] = (f"What {it['refinement']} changed", cleaned, it["text"])
    return out


class DictationsPage:
    """Every dictation, newest first, grouped by day; search; on hover: Play, Copy, Copy original, Delete."""
    EMPTY = "Nothing dictated yet"

    def __init__(self, hub):
        self.hub, self.app = hub, hub.app
        self.search = Gtk.SearchEntry(placeholder_text="Search", width_chars=12)
        self.search.connect("search-changed",
                            lambda *_: (self.list.invalidate_filter(), self.list.invalidate_headers()))
        self.widget = d.page_box()
        self.widget.pack_start(d.page_header("Dictations", self.search, d.button("Clear all…", self.clear, "danger")),
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


    FIRST, BATCH = 40, 60  # rows shown at once, then added a batch at a time while idle

    def shown(self, **_):
        stamp = history.changed()
        if stamp != getattr(self, "stamp", 0):  # (only when something's been dictated or deleted since)
            self.stamp = stamp
            self.load()

    def load(self):
        """The newest entries at once, the rest a batch at a time (hundreds of rows of wrapped text take a
        second to lay out)."""
        for row in self.list.get_children():
            self.list.remove(row)
        lines = history.lines()
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
        row.audio = history.AUDIO / it["audio"] if it.get("audio") else None
        item = d.classes(Gtk.Box(spacing=12), "row-item")
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        meta = Gtk.Box(spacing=6)
        meta.pack_start(d.text(" · ".join(filter(None, (f"{when:%H:%M}", it.get("app")))), "caption"), False, False, 0)
        known = steps(it)
        for label in applied(it):
            if label in known:
                chip = d.step_chip(label, lambda step=label: self.show_step(row, step),
                                   f"See what {label.lower() if label == 'Cleanup' else label} changed")
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
        copy = d.icon_button("copy", "Copy", lambda: (self.app.copy(it["text"]),
                                                      d.flash(copy, "Copied", "Copy", "copy")))
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
        history.remove(row.line)
        if row.audio:
            row.audio.unlink(missing_ok=True)
        self.list.remove(row)
        self.stamp = history.changed()
        self.refresh_empty()

    def clear(self):
        n = len(self.list.get_children())
        if not n or not huds.confirm(self.hub.win, f"Delete all {n} dictations and their recordings?",
                                     "This can't be undone.", "Delete all"):
            return
        self.app.player.stop()
        history.clear()
        self.load()

    def recordings_changed(self):
        for row in self.list.get_children():
            row.refresh_audio()
