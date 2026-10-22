"""Dictate's windows: History, the refinement style manager, the style picker, Transcripts (including the
one being recorded), and the reminder that a transcript is still being recorded."""
import json, threading
from datetime import datetime
from gi.repository import Gio, Gtk, Gdk, GLib
from . import refine, topics, transcript, voices

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
.topics { background: #1b1c20; border-left: 1px solid rgba(255,255,255,.05); }
.topic { background-image: none; background: #1f2125; border: 1px solid rgba(255,255,255,.05); border-radius: 8px; padding: 8px 10px; margin: 3px 10px; box-shadow: none; }
.topic:hover { background: #25272c; }
.topic.now { background: #2a2c35; border-top-color: rgba(255,255,255,.18); border-right-color: rgba(255,255,255,.18); border-bottom-color: rgba(255,255,255,.18); }
.topic-title { color: #e6e7ea; font-weight: 600; }
.topic-note { color: #b9bcc4; font-size: 9pt; }
.warning { background: rgba(255,159,67,.12); color: #ffb86b; border-radius: 8px; padding: 7px 10px; margin: 0 10px 6px 10px; font-size: 9pt; }
.reminder { border: 1px solid rgba(255,159,67,.45); }
.warning.heading { font-size: 11pt; font-weight: 700; padding: 9px 12px; margin: 0; }
""" + "".join(f".topic{i} {{ border-left: 4px solid {c}; }}\n.dot{i} {{ color: {c}; }}\n"
              for i, c in enumerate(topics.COLOURS)).encode()


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


def confirm(parent, question, detail, action="Delete all"):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                               buttons=Gtk.ButtonsType.NONE, text=question, secondary_text=detail)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, action, Gtk.ResponseType.OK)
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


# --- transcripts ---
def transcript_view():
    """A read-only text view for a transcript, and the tag for who's speaking."""
    view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
                        left_margin=16, right_margin=16, top_margin=12, bottom_margin=12)
    buf = view.get_buffer()
    buf.create_tag("pending", foreground="#8a8d96", style=2)  # 2: italic
    return view, buf.create_tag("who", weight=700, foreground="#aab4ff")


def topic_tags(buf, i):
    """The tags for topic i's paragraphs (tinted its colour) and for its name above them."""
    table = buf.get_tag_table()
    if not table.lookup(f"topic{i}"):
        rgba = Gdk.RGBA()
        rgba.parse(topics.colour(i))
        tint = Gdk.RGBA(rgba.red, rgba.green, rgba.blue, 0.09)
        buf.create_tag(f"topic{i}", paragraph_background_rgba=tint)
        buf.create_tag(f"name{i}", foreground=topics.colour(i), weight=700, scale=0.85, pixels_above_lines=6)
    return f"topic{i}", f"name{i}"


def show_transcript(view, who, paragraphs, empty, previews=(), found=None, marks=None):
    """paragraphs: [(clock, who, text)]; empty: what to say if there are none; previews: what's being said
    and not yet transcribed whole, shown greyed out after them. found: the Topics, and marks: {paragraph's
    place: topic index}: a paragraph on a topic is tinted its colour, with the topic's name above it where the
    conversation turns to it. Returns {topic index: a mark where it's first talked about}."""
    buf, firsts, last = view.get_buffer(), {}, None
    buf.set_text("" if paragraphs or previews else empty)
    for i, (clock, name, text) in enumerate([*paragraphs, *previews]):
        tags = ("pending",) if i >= len(paragraphs) else ()
        topic = (marks or {}).get(i) if not tags else None
        if topic is not None and topic < len(found.topics):
            tint, label = topic_tags(buf, topic)
            tags = (tint,)
            if topic != last:
                buf.insert_with_tags_by_name(buf.get_end_iter(), ("\n\n" if i else "") + f"● {found.topics[topic]['title']}", label, tint)
                firsts.setdefault(topic, buf.create_mark(None, buf.get_end_iter(), True))
                buf.insert_with_tags_by_name(buf.get_end_iter(), "\n", tint)
            elif i:
                buf.insert_with_tags_by_name(buf.get_end_iter(), "\n\n", tint)
        elif i:
            buf.insert(buf.get_end_iter(), "\n\n")
        last = topic
        buf.insert_with_tags_by_name(buf.get_end_iter(), f"{clock} {name}  ", "who", *tags)
        buf.insert_with_tags_by_name(buf.get_end_iter(), text, *tags)
    return firsts


def small_model(session, found):
    """A warning, if topics are being (or were) found by the smaller, less reliable model on the CPU."""
    why = "your graphics card {}" if refine.gpu_present() else "this computer has no graphics card it can use"
    if session:
        return f"Warning: using a less reliable model because {why.format('is busy')}." if refine.mode() == "cpu" else None
    if found and found.small and found.topics:
        return f"These topics were found with a less reliable model, as {why.format('was busy')}."
    return None


def json_safe(value):
    return json.dumps(value, sort_keys=True)


def open_uri(path):
    Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)


def copy_button(path):
    """Copy all: the transcript's Markdown, as saved."""
    copy = button("Copy all", lambda: (Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(path().read_text(), -1),
                                       flash(copy, "Copied ✓", "Copy all")))
    return copy


class TranscriptsWindow:
    """Every transcript: a list on the left (when, how long, how it starts), the selected one in the middle and
    its topics on the right (the current one highlighted while it's recorded; click one to go to it).
    The one being recorded, if any (current() gives its Session), is always at the top of the list and grows
    as it's heard (kept scrolled to the end unless you've scrolled up); while it's selected the header has
    Pause / Resume and Stop (on_stop() stops it). A saved one has Copy all, Open file and Delete.
    Closing the window doesn't stop the recording."""
    EMPTY = "No transcripts yet. To start one, hold Ctrl+Win, lift Win and press it again."
    LISTENING = "Listening to this computer's speakers and microphone (Me)"

    def __init__(self, current, on_stop, focus=True):
        self.current, self.on_stop, self.shown, self.paths, self.seen = current, on_stop, None, None, None
        self.win, self.bar = window("Transcripts", 1180, 640)
        self.win.set_focus_on_map(focus)  # False when started from the keyboard mid-conversation
        self.win.connect("destroy", lambda *_: setattr(self, "closed", True))
        self.closed = False
        self.bar.pack_end(button("Open folder", lambda: (transcript.FOLDER.mkdir(parents=True, exist_ok=True),
                                                          open_uri(transcript.FOLDER))))
        if voices.available():
            self.bar.pack_end(button("Voices…", lambda: VoicesWindow(self.win)))
        self.saved_actions, self.live_actions = Gtk.Box(spacing=6, no_show_all=True), Gtk.Box(spacing=6, no_show_all=True)
        for b in (copy_button(lambda: self.shown["path"]), button("Open file", lambda: open_uri(self.shown["path"])),
                  button("Delete", self.delete, "danger")):
            self.saved_actions.pack_start(b, False, False, 0)
        self.pause_btn = button("Pause", self.toggle_pause)
        for b in (button("Stop", self.on_stop, "danger"), self.pause_btn):
            self.live_actions.pack_start(b, False, False, 0)
        for box in (self.saved_actions, self.live_actions):
            for b in box.get_children():
                b.show()
            self.bar.pack_start(box)

        self.list = Gtk.ListBox()
        self.list.connect("row-selected", lambda _, row: row and self.show(row.item))
        side = css(Gtk.ScrolledWindow(width_request=270, hscrollbar_policy=Gtk.PolicyType.NEVER), "sidebar")
        side.add(self.list)
        self.text, self.who = transcript_view()
        self.scroll = css(Gtk.ScrolledWindow(hexpand=True, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER), "transcript")
        self.scroll.add(self.text)
        self.people = Gtk.Box(spacing=6, margin=8, margin_start=16, no_show_all=True)  # click a voice to name it
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.pack_start(self.people, False, False, 0)
        main.pack_start(self.scroll, True, True, 0)
        self.topics = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=10, margin_bottom=10)
        self.topics.shown = None
        right = css(Gtk.ScrolledWindow(width_request=300, hscrollbar_policy=Gtk.PolicyType.NEVER), "topics")
        right.add(self.topics)
        self.firsts = {}
        body = Gtk.Box()
        body.pack_start(side, False, False, 0)
        body.pack_start(main, True, True, 0)
        body.pack_start(right, False, False, 0)
        self.win.add(body)
        self.win.show_all()
        self.changed()

    def items(self):
        """The one being recorded first, then the saved transcripts, newest first."""
        session = self.current()
        items = [it for it in transcript.saved() if not (session and it["path"] == session.path)]
        if session:
            items.insert(0, {"path": session.path, "started": session.started, "recording": True})
        return items

    def row(self, it):
        row = Gtk.ListBoxRow()
        row.item = it
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=2, margin_bottom=2)
        box.add(Gtk.Label(label=f"{it['started']:%a %d %b · %H:%M}", xalign=0))
        row.length = css(Gtk.Label(xalign=0), "time")
        row.start = css(Gtk.Label(xalign=0, ellipsize=3, max_width_chars=30), "hint")  # 3: ellipsize at the end
        box.add(row.length)
        box.add(row.start)
        row.add(box)
        self.describe(row)
        return row

    def describe(self, row):
        """Fill in a row's length and first words (the recording's change as it's heard)."""
        it, session = row.item, self.current()
        live = it.get("recording") and session
        row.length.set_text(("Paused" if session.paused else "Recording now") if live else it["length"])
        paragraphs = session.paragraphs() if live else it["paragraphs"]
        start = " ".join(text for _, _, text in paragraphs)[:200]
        row.start.set_text(start or ("Nothing heard yet." if live else "Nothing was heard."))

    def changed(self):
        """Something changed: a recording started, grew, paused or stopped, or a transcript was deleted.
        The list is only rebuilt if which transcripts there are has changed, so reading one isn't disturbed."""
        if self.closed:
            return
        items = self.items()
        paths = [(it["path"], bool(it.get("recording"))) for it in items]
        if paths != self.paths:
            self.paths = paths
            session = self.current()
            if session and session.path != self.seen:  # a new recording: select it, to watch it
                self.seen, select = session.path, session.path
            else:
                select = self.shown and self.shown["path"]
            self.rebuild(items, select)
        else:
            for row in self.list.get_children():
                if row.item.get("recording"):
                    self.describe(row)
            if self.shown and self.shown.get("recording"):
                self.show(self.shown)
            elif self.shown and self.shown.get("changed") is not None:  # e.g. its last topics, just found
                again = transcript.read(self.shown["path"])
                if again and again["changed"] != self.shown["changed"]:
                    self.show(again)

    def show_recording(self):
        """Select the one being recorded (it's always first)."""
        first = self.list.get_row_at_index(0)
        if first and first.item.get("recording"):
            self.list.select_row(first)

    def rebuild(self, items, select=None):
        for row in self.list.get_children():
            self.list.remove(row)
        for it in items:
            self.list.add(self.row(it))
        self.list.show_all()
        rows = self.list.get_children()
        if not rows:
            self.shown = None
            self.saved_actions.hide()
            self.live_actions.hide()
            return show_transcript(self.text, self.who, [], self.EMPTY)
        self.list.select_row(next((r for r in rows if r.item["path"] == select), rows[0]))

    def show(self, item):
        session = self.current() if item.get("recording") else None
        if item.get("recording") and not session:  # stopped since: show it as saved
            item = transcript.read(item["path"]) or item
        following = item is not self.shown or self.at_end()
        self.shown = item
        self.saved_actions.set_visible(not session)
        self.live_actions.set_visible(bool(session))
        if session:
            self.pause_btn.set_label("Resume" if session.paused else "Pause")
            self.bar.set_subtitle("Paused: nothing is being added" if session.paused else self.LISTENING)
            found, marks, people = session.topic_view()
            self.firsts = show_transcript(self.text, self.who, session.paragraphs(), "Nothing heard yet.",
                                          session.previews(), found, marks)
        else:
            self.bar.set_subtitle(None)
            paragraphs = item.get("paragraphs", [])
            found = transcript.read_topics(item["path"])
            marks, people = (found.of, found.people(transcript.numbered(paragraphs))) if found else ({}, [])
            self.firsts = show_transcript(self.text, self.who, paragraphs, "Nothing was heard.", found=found, marks=marks)
        self.show_topics(found, people, bool(session), bool(item.get("paragraphs")), small_model(session, found))
        nameable = not session or session.voices  # without the voice model, a recording's voices are all "Them"
        self.show_people(transcript.labels(session.paragraphs() if session else item.get("paragraphs", [])) if nameable else [])
        if session and following:
            adj = self.scroll.get_vadjustment()
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()) and False)

    def show_topics(self, found, people, live, heard, warning=None):
        """The topics of the transcript shown: each a card in its colour, with who started it and who else
        spoke on it; the one being talked about now highlighted, while it's recorded. warning: that they're
        found by the less reliable model, or None."""
        topics_ = found.topics if found else []
        now = found.now if found and live else None
        shown = (self.shown["path"], json_safe(topics_), people, now, live, heard, self.finding, warning)
        if shown == self.topics.shown:
            return
        self.topics.shown = shown
        for kid in self.topics.get_children():
            kid.destroy()
        self.topics.pack_start(css(Gtk.Label(label="Topics", xalign=0, margin_start=14, margin_bottom=4), "heading"), False, False, 0)
        if warning:
            self.topics.pack_start(css(Gtk.Label(label=warning, xalign=0, wrap=True, max_width_chars=34), "warning"), False, False, 0)
        if not topics_:
            if live:
                hint = "The topics of the conversation appear here as it goes on, about a minute in."
            elif self.finding == self.shown["path"]:
                hint = "Finding the topics…"
            else:
                hint = "No topics were found." if transcript.read_topics(self.shown["path"]) else \
                    "Recorded before topics were found." if heard else "Nothing was heard."
            self.topics.pack_start(css(Gtk.Label(label=hint, xalign=0, wrap=True, max_width_chars=34, margin_start=14,
                                                 margin_end=14), "hint"), False, False, 0)
            if heard and not live and self.finding != self.shown["path"] and not transcript.read_topics(self.shown["path"]):
                find = button("Find topics", self.find_topics)
                find.set_halign(Gtk.Align.START)
                find.set_margin_start(14)
                find.set_margin_top(8)
                self.topics.pack_start(find, False, False, 0)
        for i, t in enumerate(topics_):
            card = css(Gtk.Button(), "topic", f"topic{i % len(topics.COLOURS)}", *(["now"] if i == now else []))
            card.connect("clicked", lambda _, i=i: self.go_to_topic(i))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            head = Gtk.Box(spacing=6)
            head.pack_start(css(Gtk.Label(label=t["title"], xalign=0, wrap=True, max_width_chars=26), "topic-title"), True, True, 0)
            if i == now:
                head.pack_end(css(Gtk.Label(label="Now"), "chip"), False, False, 0)
            box.pack_start(head, False, False, 0)
            who = people[i] if i < len(people) else []
            if who:
                text = f"{who[0]} brought it up" + (f" · with {', '.join(who[1:])}" if who[1:] else "")
                box.pack_start(css(Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=34), "time"), False, False, 0)
            for point in t["points"]:
                box.pack_start(css(Gtk.Label(label=point, xalign=0, wrap=True, max_width_chars=34), "topic-note"), False, False, 0)
            card.add(box)
            self.topics.pack_start(card, False, False, 0)
        self.topics.show_all()

    def go_to_topic(self, i):
        """Scroll the transcript to where topic i is first talked about."""
        mark = self.firsts.get(i)
        if mark and not mark.get_deleted():
            self.text.scroll_to_mark(mark, 0.0, True, 0.0, 0.1)

    finding = None

    def find_topics(self):
        """Find the topics of a transcript saved before topics were (it takes a model request per few minutes)."""
        path = self.finding = self.shown["path"]
        self.topics.shown = None
        self.show(self.shown)
        def find():
            try:
                found = transcript.find_topics(path)
                transcript.save_topics(path, found)
            except (OSError, ValueError, KeyError) as err:
                print("topics: couldn't find them:", err, flush=True)
            GLib.idle_add(done)
        def done():
            self.finding = None
            if not self.closed and self.shown and self.shown["path"] == path:
                self.shown = transcript.read(path) or self.shown
                self.topics.shown = None
                self.show(self.shown)
        threading.Thread(target=find, daemon=True).start()

    def show_people(self, labels):
        """A button per voice in the transcript shown, to name it."""
        if labels == getattr(self.people, "labels", None):
            return
        self.people.labels = labels
        for kid in self.people.get_children():
            kid.destroy()
        self.people.pack_start(css(Gtk.Label(label="Click a name to rename:"), "hint"), False, False, 0)
        for label in labels:
            self.people.pack_start(button(label, lambda l=label: self.rename(l)), False, False, 0)
        for kid in self.people.get_children():
            kid.show()
        self.people.set_visible(bool(labels))

    def rename(self, label):
        it, session = self.shown, self.current()
        live = it.get("recording") and session
        remembers = voices.remembering() and (live or transcript.voiceprints(it["path"]).exists())
        name = ask_name(self.win, label, remembers)
        if not name:
            return
        if live:
            session.rename(label, name)  # its on_change shows it
        else:
            transcript.rename(it["path"], label, name)
            self.shown = None
            self.paths = None  # read it again
            self.changed()
            self.list.select_row(next(r for r in self.list.get_children() if r.item["path"] == it["path"]))

    def at_end(self):
        adj = self.scroll.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 20

    def toggle_pause(self):
        session = self.current()
        if session:
            session.pause(not session.paused)

    def delete(self):
        it = self.shown
        if it and confirm(self.win, f"Delete the transcript from {it['started']:%a %d %b, %H:%M}?",
                          "Its recordings are deleted too. This can't be undone.", "Delete"):
            transcript.delete(it["path"])
            self.shown = None
            self.changed()


def ask_name(parent, label, remembers):
    """Ask what a voice is called. remembers: whether naming it remembers the voice for later transcripts."""
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.NONE, text=f"Who is {label}?",
                               secondary_text="Dictate will remember this voice and name it in later transcripts."
                               if remembers else "Naming two voices the same makes them one person.")
    entry = Gtk.Entry(placeholder_text="Name", activates_default=True)
    if not label.startswith("Speaker "):
        entry.set_text(label)
    dialog.get_message_area().pack_start(entry, False, False, 6)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Rename", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.show_all()
    answer, name = dialog.run(), entry.get_text()
    dialog.destroy()
    return transcript.clean_name(name) if answer == Gtk.ResponseType.OK else ""


class VoicesWindow:
    """Remembering voices (opt-in) and the voices remembered, each of which can be forgotten."""
    EXPLAIN = ("When this is on, Dictate keeps a voiceprint of each person you name in a transcript, on this computer "
               "only, and names them automatically in later transcripts. A voiceprint can identify someone, so ask "
               "people before you remember their voice. Turning this off forgets every voice.")

    def __init__(self, parent=None):
        self.win, _ = window("Voices", 520, 420)
        if parent:
            self.win.set_transient_for(parent)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
        self.toggle = Gtk.CheckButton(label="Remember voices I name", active=voices.remembering())
        self.toggle.connect("toggled", self.toggled)
        box.pack_start(self.toggle, False, False, 0)
        box.pack_start(css(Gtk.Label(label=self.EXPLAIN, xalign=0, wrap=True, max_width_chars=60), "hint"), False, False, 0)
        box.pack_start(css(Gtk.Label(label="Remembered voices", xalign=0, margin_top=6), "heading"), False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.list, False, False, 0)
        self.win.add(box)
        self.win.show_all()
        self.refresh()

    def refresh(self):
        for kid in self.list.get_children():
            kid.destroy()
        names = [name for name, _ in voices.remembered()]
        if not names:
            self.list.add(css(Gtk.Label(label="None yet. Name someone in a transcript to remember their voice."
                                        if voices.remembering() else "None.", xalign=0), "empty"))
        for name in names:
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            row.pack_end(button("Forget", lambda n=name: (voices.forget(n), self.refresh()), "danger"), False, False, 0)
            self.list.add(row)
        self.list.show_all()

    def toggled(self, toggle):
        on = toggle.get_active()
        n = len(voices.remembered())
        if not on and n and not confirm(self.win, f"Forget {'the' if n == 1 else f'all {n}'} remembered "
                                        f"voice{'s' if n > 1 else ''}?", "This can't be undone.", "Forget"):
            toggle.handler_block_by_func(self.toggled)
            toggle.set_active(True)
            toggle.handler_unblock_by_func(self.toggled)
            return
        voices.set_remembering(on)
        if not on:
            transcript.forget_voiceprints()
        self.refresh()


# --- still transcribing ---
STOP_WAYS = ("Stop, in the Transcripts window (click the icon to open it)", "Ctrl+Win, lift Win and press it again",
             "Stop transcribing, in the icon's menu")
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
    """A panel beside the floating icon saying a transcript is still being recorded, with a picture of the icon
    as it looks while transcribing (picture: a pixbuf), every way to stop it, and Stop now / Keep going."""

    def __init__(self, why, minutes, picture, beside, on_stop):
        """beside: (x, y, width, height) of the icon on screen."""
        heading, body = reminder_text(why, minutes)
        self.win = css(Gtk.Window(title="Still transcribing", decorated=False, resizable=False, skip_taskbar_hint=True,
                                  type_hint=Gdk.WindowTypeHint.DIALOG), "win", "reminder")
        self.win.set_keep_above(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16, width_request=420)
        box.pack_start(css(Gtk.Label(label=f"⚠  {heading}", xalign=0, halign=Gtk.Align.FILL), "warning", "heading"),
                       False, False, 0)
        box.pack_start(css(Gtk.Label(label=body, xalign=0, wrap=True, max_width_chars=60), "text"), False, False, 0)
        icon = Gtk.Box(spacing=12)
        icon.pack_start(Gtk.Image.new_from_pixbuf(picture), False, False, 0)
        icon.pack_start(css(Gtk.Label(label="The blue ring around Dictate's icon means it's transcribing. Click the "
                                            "icon to see the transcript.", xalign=0, wrap=True, max_width_chars=50),
                            "text"), True, True, 0)
        box.pack_start(icon, False, False, 0)
        box.pack_start(css(Gtk.Label(label="To stop it:", xalign=0), "field"), False, False, 0)
        for way in STOP_WAYS:
            box.pack_start(css(Gtk.Label(label=f"•  {way}", xalign=0, wrap=True, max_width_chars=60), "text"), False, False, 0)
        buttons = Gtk.Box(spacing=8, margin_top=6)
        buttons.pack_end(button("Keep going", self.close), False, False, 0)
        buttons.pack_end(button("Stop now", lambda: (on_stop(), self.close()), "danger"), False, False, 0)
        box.pack_start(buttons, False, False, 0)
        self.win.add(box)
        self.win.show_all()
        self.place(beside)

    def place(self, beside):
        """To the right of the icon, or its left if there's no room, within its screen."""
        x, y, w, h = beside
        width, height = self.win.get_size()
        display = Gdk.Display.get_default()
        area = display.get_monitor_at_point(x + w // 2, y + h // 2).get_workarea()
        left = x + w + 8 if x + w + 8 + width <= area.x + area.width else x - 8 - width
        top = min(max(y, area.y), area.y + area.height - height)
        self.win.move(max(left, area.x), top)

    def close(self):
        self.win.destroy()

    @property
    def open(self):
        return self.win.get_mapped()
