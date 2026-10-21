"""Dictate's windows: History, the refinement style manager, the style picker, and the transcript."""
import json
from datetime import datetime
from gi.repository import Gio, Gtk, Gdk, GLib
from . import refine

CSS = b"""
* { font-family: "Inter", "Noto Sans", sans-serif; }
menu, .menu { background: #1d1e22; border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 6px; }
menu menuitem { color: #e6e7ea; padding: 7px 14px; border-radius: 6px; min-width: 120px; }
menu menuitem:hover { background: rgba(124,140,255,.18); color: #fff; }
menu separator { background: rgba(255,255,255,.07); margin: 4px 6px; min-height: 1px; }
.win { background: #16171a; }
.win headerbar { background: #1d1e22; border: none; box-shadow: none; min-height: 44px; }
.win headerbar .title { color: #e6e7ea; font-weight: 600; }
.win entry { background: #24262b; color: #e6e7ea; border: 1px solid rgba(255,255,255,.06); border-radius: 8px; padding: 6px 10px; }
.win list { background: transparent; }
.win row { background: transparent; padding: 0; }
.card { background: #1f2125; border: 1px solid rgba(255,255,255,.05); border-radius: 10px; padding: 12px 14px; margin: 5px 12px; }
.card:hover { background: #25272c; }
.time { color: #8a8d96; font-size: 9pt; }
.text { color: #e6e7ea; font-size: 10.5pt; }
.btn { background: rgba(124,140,255,.14); color: #aab4ff; border: none; border-radius: 6px; padding: 3px 12px; box-shadow: none; }
.btn:hover { background: rgba(124,140,255,.28); color: #fff; }
.danger { background: rgba(255,90,90,.12); color: #ff9a9a; }
.danger:hover { background: rgba(255,90,90,.25); color: #fff; }
.empty { color: #6b6e76; }
.hint { color: #8a8d96; font-size: 9pt; }
.error { color: #ff8a8a; font-size: 9pt; }
.field { color: #8a8d96; font-size: 9pt; font-weight: 600; }
.editor text { background: #1f2125; color: #e6e7ea; }
.editor textview { font-family: "Noto Sans Mono", monospace; font-size: 10pt; }
.frame { border: 1px solid rgba(255,255,255,.06); border-radius: 10px; }
.sidebar { background: #1b1c20; border-right: 1px solid rgba(255,255,255,.05); }
.sidebar row { padding: 9px 14px; border-radius: 8px; margin: 2px 8px; color: #e6e7ea; }
.sidebar row:selected { background: rgba(124,140,255,.2); }
.key { background: #2b2e35; color: #c9cdf9; border-radius: 5px; padding: 1px 7px; font-weight: 700; font-size: 9pt; }
.choice { background: #1f2125; border: 1px solid rgba(255,255,255,.05); border-radius: 8px; padding: 9px 12px; color: #e6e7ea; box-shadow: none; }
.choice:hover { background: #2a2c33; border-color: rgba(124,140,255,.4); }
.transcript text { background: #16171a; color: #e6e7ea; }
.heading { color: #e6e7ea; font-size: 11pt; font-weight: 600; }
.chip { background: rgba(124,140,255,.12); color: #aab4ff; border-radius: 5px; padding: 1px 7px; font-size: 8.5pt; }
"""


def install_css():
    style = Gtk.CssProvider()
    style.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style, 600)
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)


def css(widget, *classes):
    for c in classes:
        widget.get_style_context().add_class(c)
    return widget


def window(title, w, h, subtitle=None):
    win = css(Gtk.Window(title=title, default_width=w, default_height=h), "win")
    bar = Gtk.HeaderBar(title=title, subtitle=subtitle, show_close_button=True)
    win.set_titlebar(bar)
    return win, bar


def button(label, cb, *classes):
    b = css(Gtk.Button(label=label), "btn", *classes)
    b.connect("clicked", lambda _: cb())
    return b


def flash(btn, done, label):
    btn.set_label(done)
    GLib.timeout_add(1200, lambda: btn.set_label(label))


def key_badge(key):
    return css(Gtk.Label(label=key.upper()), "key")


# --- history ---
def history(app, path, audio_dir):
    """Newest first. Each entry: what was applied, Play/Stop (if its recording exists), Copy, Original, Delete."""
    lines = path.read_text().splitlines() if path.exists() else []
    win, bar = window("History", 740, 560)
    search = Gtk.SearchEntry(placeholder_text="Search")
    bar.pack_end(search)
    lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    empty = css(Gtk.Label(label="Nothing yet — hold Ctrl+Win to dictate", margin=40), "empty")

    def show_empty():
        if not lb.get_children():
            lb.add(empty)
            empty.show()

    def delete(row):
        """Remove one entry from the history file, and its recording."""
        app.player.stop()
        keep = path.read_text().splitlines()
        if row.line in keep:
            keep.remove(row.line)
            path.write_text("".join(l + "\n" for l in keep))
        if row.audio:
            row.audio.unlink(missing_ok=True)
        lb.remove(row)
        show_empty()

    def clear():
        n = len([r for r in lb.get_children() if hasattr(r, "line")])
        if not n or not confirm(win, f"Delete all {n} history entries and their recordings?", "This can't be undone."):
            return
        app.player.stop()
        path.write_text("")
        for wav in audio_dir.glob("*.wav"):
            wav.unlink(missing_ok=True)
        for row in lb.get_children():
            lb.remove(row)
        show_empty()

    bar.pack_start(button("Clear history", clear, "danger"))
    bar.pack_start(keep_recordings(app, lambda: [r.refresh_audio() for r in lb.get_children() if hasattr(r, "line")]))
    for line in reversed(lines):
        try:
            lb.add(history_card(app, json.loads(line), line, audio_dir, delete))
        except ValueError:
            continue
    show_empty()
    lb.set_filter_func(lambda row: search.get_text().lower() in getattr(row, "text", "").lower())
    search.connect("search-changed", lambda *_: lb.invalidate_filter())
    win.connect("destroy", lambda *_: app.player.stop())

    scroll = Gtk.ScrolledWindow(margin_top=6, margin_bottom=6, hscrollbar_policy=Gtk.PolicyType.NEVER)  # never cut off buttons
    scroll.add(lb)
    win.add(scroll)
    win.show_all()


def keep_recordings(app, refresh):
    """'Keep recordings: [24 hours ▾]' for the header: how long each dictation's audio is kept for playback."""
    box = Gtk.Box(spacing=6, margin_start=8)
    box.pack_start(css(Gtk.Label(label="Keep recordings:"), "hint"), False, False, 0)
    combo = Gtk.ComboBoxText()
    for hours, label in app.KEEP_AUDIO:
        combo.append_text(label)
    combo.set_active([h for h, _ in app.KEEP_AUDIO].index(app.cfg["keep_audio_hours"]))

    def changed(c):
        app.set_keep_audio(app.KEEP_AUDIO[c.get_active()][0])
        refresh()  # recordings may just have been deleted: hide their Play buttons
    combo.connect("changed", changed)
    box.pack_start(combo, False, False, 0)
    return box


def applied(it):
    """What was done to an entry's text, e.g. ["Cleanup", "Slack"]; older entries didn't record cleanup."""
    cleanup = it.get("cleanup", "raw" in it or "style" in it or None)
    return (["Cleanup"] if cleanup else ["Raw transcript"] if cleanup is False else []) + ([it["style"]] if "style" in it else [])


def history_card(app, it, line, audio_dir, delete):
    when = datetime.fromisoformat(it["t"]).strftime("%a %d %b · %H:%M")
    head = Gtk.Box(spacing=8)
    head.pack_start(css(Gtk.Label(label=" · ".join(filter(None, (when, it.get("app")))), xalign=0), "time"), False, False, 0)
    for i, label in enumerate(applied(it)):
        head.pack_start(css(Gtk.Label(label=("+ " if i else "") + label), "chip"), False, False, 0)
    head.pack_start(Gtk.Box(hexpand=True), True, True, 0)

    row = Gtk.ListBoxRow(activatable=False)
    row.text, row.line = it["text"], line
    row.audio = audio_dir / it["audio"] if it.get("audio") else None
    play = css(Gtk.Button(label="▶ Play", no_show_all=True), "btn")

    def toggle(b):
        if b.get_label() == "■ Stop":
            return app.player.stop()
        if not row.refresh_audio():  # deleted since the window opened (e.g. it got too old)
            return
        b.set_label("■ Stop")
        app.player.play(str(row.audio), lambda: b.set_label("▶ Play"))
    play.connect("clicked", toggle)
    head.pack_start(play, False, False, 0)
    row.refresh_audio = lambda: (play.set_visible(bool(row.audio and row.audio.exists())), play.get_visible())[1]
    row.refresh_audio()
    for label, text in (("Copy", it["text"]), ("Original", it.get("raw"))):
        if text:
            btn = css(Gtk.Button(label=label, tooltip_text=text if label == "Original" else None), "btn")
            btn.connect("clicked", lambda b, t=text, l=label: (app.copy(t), flash(b, "Copied ✓", l)))
            head.pack_start(btn, False, False, 0)
    head.pack_start(button("Delete", lambda: delete(row), "danger"), False, False, 0)

    card = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "card")
    card.add(head)
    card.add(css(Gtk.Label(label=it["text"], xalign=0, wrap=True, selectable=True, margin_top=6), "text"))
    row.add(card)
    return row


def confirm(parent, question, detail):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                               buttons=Gtk.ButtonsType.NONE, text=question, secondary_text=detail)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete all", Gtk.ResponseType.OK)
    answer = dialog.run()
    dialog.destroy()
    return answer == Gtk.ResponseType.OK


# --- style manager ---
class StyleManager:
    """Sidebar: Default cleanup, Vocabulary, then the additional styles; an editor for the selected one."""
    FIXED = 2  # sidebar rows before the styles

    def __init__(self, on_change=None, new=False):
        self.on_change, self.data = on_change, refine.load_styles()
        self.win, bar = window("Refinement styles", 760, 600)
        css(self.win, "editor")
        bar.pack_end(button("Save", self.save))
        self.delete = button("Delete", self.remove, "danger")
        self.reset = button("Reset to default", lambda: self.prompt.get_buffer().set_text(refine.CLEANUP))
        bar.pack_start(self.delete)
        bar.pack_start(self.reset)

        self.list = Gtk.ListBox()
        self.list.connect("row-selected", lambda _, row: row and self.show(row.get_index()))
        side = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=210), "sidebar")
        side.pack_start(self.list, True, True, 8)
        side.pack_end(button("+ Add refinement style", self.add), False, False, 10)

        self.name, self.key = Gtk.Entry(hexpand=True), Gtk.Entry(max_length=1, width_chars=3)
        self.apps = Gtk.Entry(placeholder_text="e.g. slack, discord  (matched against the focused app and window title)")
        self.prompt = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, left_margin=14, right_margin=14,
                                   top_margin=12, bottom_margin=12)
        self.hint = css(Gtk.Label(xalign=0, wrap=True), "hint")
        self.error = css(Gtk.Label(xalign=0), "error")
        self.fields = Gtk.Grid(column_spacing=10, row_spacing=4)
        for col, row, label in ((0, 0, "NAME"), (1, 0, "LETTER"), (0, 2, "USE AUTOMATICALLY IN APPS")):
            self.fields.attach(css(Gtk.Label(label=label, xalign=0, margin_top=6 if row else 0), "field"), col, row, 1, 1)
        self.fields.attach(self.name, 0, 1, 1, 1)
        self.fields.attach(self.key, 1, 1, 1, 1)
        self.fields.attach(self.apps, 0, 3, 2, 1)
        scroll = css(Gtk.ScrolledWindow(vexpand=True), "frame")
        scroll.add(self.prompt)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=14)
        for w in (self.fields, self.hint, scroll, self.error):
            form.add(w)

        body = Gtk.Box()
        body.pack_start(side, False, False, 0)
        body.pack_start(form, True, True, 0)
        self.win.add(body)
        self.win.show_all()
        self.rebuild(0)
        if new:
            self.add()

    def rebuild(self, select):
        for row in self.list.get_children():
            self.list.remove(row)
        rows = [("Default cleanup", None), ("Vocabulary", None)] + [(s["name"], s["key"]) for s in self.data["styles"]]
        for name, key in rows:
            box = Gtk.Box(spacing=8)
            box.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            if key:
                box.pack_end(key_badge(key), False, False, 0)
            self.list.add(box)
        self.list.show_all()
        self.list.select_row(self.list.get_row_at_index(select))

    def show(self, i):
        self.i = i
        style = self.data["styles"][i - self.FIXED] if i >= self.FIXED else {}
        text = self.data["cleanup"] if i == 0 else refine.load_vocab() if i == 1 else style["prompt"]
        self.fields.set_visible(i >= self.FIXED)
        self.delete.set_visible(i >= self.FIXED)
        self.reset.set_visible(i == 0)
        self.name.set_text(style.get("name", ""))
        self.key.set_text(style.get("key", "").upper())
        self.apps.set_text(style.get("apps", ""))
        self.prompt.get_buffer().set_text(text)
        self.error.set_text("")
        self.hint.set_text([
            "Always applied first, to every dictation. Keep it to light clean-up.",
            "Names and terms you use, one per line (people, products, jargon). Cleanup prefers these spellings "
            "and fixes similar-sounding mis-hearings of them.",
        ][i] if i < self.FIXED else
            "Applied after cleanup. Hold Ctrl+Win and press Alt+letter to use it, or tap Alt to choose afterwards. "
            "It's also used automatically when you dictate into a matching app. Describe the style and give an "
            "Input/Output example or two.")

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
        self.error.set_text("Saved ✓")
        if self.on_change:
            self.on_change()

    def remove(self):
        del self.data["styles"][self.i - self.FIXED]
        refine.save_styles(self.data)
        self.rebuild(0)
        if self.on_change:
            self.on_change()


# --- style picker (after Ctrl+Win with Alt tapped) ---
class StylePicker:
    """Shows the cleaned-up text, then calls on_choose(style, paste): style is None for "Paste as is",
    paste is False if the user pressed Escape (text is kept in history and the clipboard only)."""

    def __init__(self, text, on_choose):
        self.on_choose = on_choose
        self.win, bar = window("Refine", 520, -1)
        self.win.set_keep_above(True)
        self.win.set_position(Gtk.WindowPosition.CENTER)
        self.win.connect("key-press-event", self.on_key)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
        box.add(css(Gtk.Label(label="Here's the cleaned-up version of what you said:", xalign=0), "hint"))
        card = css(Gtk.Box(), "card")
        card.add(css(Gtk.Label(label=text, xalign=0, wrap=True, selectable=True, max_width_chars=60), "text"))
        box.add(card)
        box.add(css(Gtk.Label(label="Which additional refinement style would you like to apply?", xalign=0), "heading"))
        self.choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add(self.choices)
        foot = Gtk.Box(spacing=8, margin_top=6)
        foot.pack_start(button("+ Add refinement style", lambda: StyleManager(self.refresh, new=True)), False, False, 0)
        foot.pack_end(button("Paste as is  ⏎", lambda: self.choose(None)), False, False, 0)
        box.add(foot)
        self.win.add(box)
        self.refresh()
        self.win.show_all()
        self.win.present_with_time(Gtk.get_current_event_time())

    def refresh(self):
        for c in self.choices.get_children():
            self.choices.remove(c)
        self.styles = refine.load_styles()["styles"]
        for s in self.styles:
            row = Gtk.Box(spacing=10)
            row.pack_start(key_badge(s["key"]), False, False, 0)
            row.pack_start(Gtk.Label(label=s["name"], xalign=0), True, True, 0)
            b = css(Gtk.Button(), "choice")
            b.add(row)
            b.connect("clicked", lambda _, s=s: self.choose(s))
            self.choices.add(b)
        self.choices.show_all()

    def on_key(self, _, ev):
        name = Gdk.keyval_name(ev.keyval)
        if name == "Escape":
            self.choose(None, paste=False)
        elif name in ("Return", "KP_Enter"):
            self.choose(None)
        else:
            s = next((s for s in self.styles if s["key"] == name.lower()), None)
            if s:
                self.choose(s)
        return False

    def choose(self, style, paste=True):
        self.win.destroy()
        self.on_choose(style, paste)


# --- transcript ---
class TranscriptWindow:
    """The transcript as it grows, newest at the bottom (kept in view unless you've scrolled up).
    While recording: Pause / Resume and Stop. Closing the window stops too. Once stopped: Copy all, Open file."""
    LISTENING = "Listening to this computer's speakers (Them) and microphone (Me)"

    def __init__(self, session, on_stop):
        self.session, self.on_stop = session, on_stop
        self.win, self.bar = window("Transcript", 620, 520, self.LISTENING)
        self.win.set_focus_on_map(False)  # started from the keyboard, mid-conversation: leave focus where it is
        self.win.connect("delete-event", lambda *_: self.stop() or False)
        self.win.connect("destroy", lambda *_: setattr(self, "closed", True))
        self.closed = False
        self.pause_btn = button("Pause", self.toggle_pause)
        self.stop_btn = button("Stop", self.stop, "danger")
        self.bar.pack_start(self.stop_btn)
        self.bar.pack_start(self.pause_btn)
        self.text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
                                 left_margin=16, right_margin=16, top_margin=12, bottom_margin=12)
        self.who = self.text.get_buffer().create_tag("who", weight=700, foreground="#aab4ff")
        self.scroll = css(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER), "transcript")
        self.scroll.add(self.text)
        self.win.add(self.scroll)
        self.win.show_all()
        self.refresh()

    def refresh(self):
        if self.closed:
            return
        adj = self.scroll.get_vadjustment()
        following = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 20
        buf = self.text.get_buffer()
        buf.set_text("")
        paragraphs = self.session.paragraphs()
        if not paragraphs:
            buf.insert(buf.get_end_iter(), "Nothing heard yet." if not self.session.stopped else "Nothing was heard.")
        for i, (clock, who, text) in enumerate(paragraphs):
            buf.insert_with_tags(buf.get_end_iter(), ("\n\n" if i else "") + f"{clock} {who}  ", self.who)
            buf.insert(buf.get_end_iter(), text)
        if following:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()) and False)

    def toggle_pause(self):
        self.session.pause(not self.session.paused)
        self.pause_btn.set_label("Resume" if self.session.paused else "Pause")
        self.bar.set_subtitle("Paused: nothing is being added" if self.session.paused else self.LISTENING)

    def stop(self):
        if not self.session.stopped:
            self.on_stop()

    def stopped(self):
        """The session has stopped and the transcript is saved."""
        if self.closed:
            return
        for b in (self.pause_btn, self.stop_btn):
            b.destroy()
        self.bar.set_subtitle(f"Stopped. Saved as {self.session.path.name}")
        path = self.session.path
        copy = button("Copy all", lambda: (Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(path.read_text(), -1),
                                           flash(copy, "Copied ✓", "Copy all")))
        self.bar.pack_start(copy)
        self.bar.pack_start(button("Open file", lambda: Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)))
        self.bar.show_all()
        self.refresh()
