"""The Transcripts page of the Dictate window: every transcript in a list at left (when, how long, how it starts),
the selected one in the middle (all the room there is), and its topics in a rail at right (the list and the rail
are as wide as you drag them, remembered) (the current one marked while it's recorded;
click one to go to it). The one being recorded (the app's session) is always first in the list and grows as it's
heard (kept scrolled to the end unless you've scrolled up); while it's shown, the header has its status, Pause /
Resume and Stop. A saved one has Play (while its recordings are kept), Copy all, Open file, Open folder and Delete,
and each paragraph can be played on its own. Closing the window doesn't stop the recording (it stops playback)."""
import json

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import design as d
from . import huds, llm, summary, transcript, voices

GUTTER = 88  # px: a paragraph's play button and time are in a gutter this wide; what was said starts at its edge,
# and so do its wrapped lines (not under the time)


def transcript_view():
    """A read-only text view for a transcript."""
    view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        left_margin=24, right_margin=24, top_margin=8, bottom_margin=24, pixels_inside_wrap=2)
    tabs = Pango.TabArray.new(1, True)  # (in pixels)
    tabs.set_tab(0, Pango.TabAlign.LEFT, GUTTER)
    view.set_tabs(tabs)
    style_tags(view.get_buffer())
    d.on_scheme.append(lambda: style_tags(view.get_buffer()))
    return view


def style_tags(buf):
    """The text view's tags, in the design's colours (again when the scheme changes)."""
    table = buf.get_tag_table()
    for name, props in (("pending", {"foreground": d.tok("text-3"), "style": Pango.Style.ITALIC}),
                        ("who", {"foreground": d.tok("text"), "weight": 600}),
                        ("clock", {"foreground": d.tok("text-3"), "scale": 0.85}),
                        ("playing", {"paragraph-background-rgba": d.rgba("accent", 0.16)}),
                        ("hang", {"indent": -GUTTER})):  # (wrapped lines start at the gutter's edge: GTK
        # indents a paragraph's lines after its first by a negative indent)
        tag = table.lookup(name) or buf.create_tag(name)
        for k, v in props.items():
            tag.set_property(k, v)
    for i in range(len(d.SCHEMES[d.scheme]["topics"])):
        if table.lookup(f"topic{i}"):
            topic_tags(buf, i, restyle=True)


def topic_tags(buf, i, restyle=False):
    """The tags for paragraphs on a topic of colour number i (tinted that colour) and for its name above them."""
    table = buf.get_tag_table()
    if restyle or not table.lookup(f"topic{i}"):
        tint = table.lookup(f"topic{i}") or buf.create_tag(f"topic{i}")
        tint.set_property("paragraph-background-rgba", d.rgba(d.topic_colour(i), 0.09))
        name = table.lookup(f"name{i}") or buf.create_tag(f"name{i}")
        for k, v in {"foreground": d.topic_colour(i), "weight": 600, "scale": 0.85, "pixels-above-lines": 8}.items():
            name.set_property(k, v)
    return f"topic{i}", f"name{i}"


def show_transcript(view, paragraphs, previews=(), found=None, marks=None, control=None):
    """paragraphs: [(clock, who, text)]; previews: what's being said and not yet transcribed whole, shown greyed
    out after them. found: the Topics, and marks: {paragraph's place: topic index}: a paragraph on a topic is
    tinted its colour, with the topic's name above it where the conversation turns to it. control(i): a widget to
    put before paragraph i's time (e.g. its Play button). Returns {topic index: a mark where it's first talked
    about}; view.paragraphs is [(mark where each paragraph starts, mark where the next block starts or None)].
    Only what's changed is written again, from the first paragraph that has (usually just the preview at the end):
    emptying the whole text each time made it shrink to nothing for a moment, so it flashed and lost its place."""
    buf, specs, last = view.get_buffer(), [], None
    for i, (clock, name, text) in enumerate([*paragraphs, *previews]):
        pending = i >= len(paragraphs)
        topic = (marks or {}).get(i) if not pending else None
        if topic is not None and topic >= len(found.topics):
            topic = None
        title, hue = (found.topics[topic]["title"], found.hue(topic)) if topic is not None else (None, None)
        specs.append((i, topic, last, title, hue, clock, name, text, pending))
        last = topic
    shown = getattr(view, "shown", None)
    if not shown or shown["chars"] != buf.get_char_count() or shown["control"] != bool(control):  # start again,
        buf.set_text("")  # from nothing (e.g. a recording just stopped: played back, it has buttons; or something else
        shown = view.shown = {"blocks": [], "chars": -1, "control": bool(control)}  # was written)
    blocks = shown["blocks"]  # [(spec, mark where it starts, its topic's first mark or None)]
    same = next((k for k, (spec, *_) in enumerate(blocks) if k >= len(specs) or spec != specs[k]), len(blocks))
    if same < len(blocks):
        buf.delete(buf.get_iter_at_mark(blocks[same][1]), buf.get_end_iter())
        for _, at, first, begins in blocks[same:]:
            for mark in (at, first, begins):
                if mark:
                    buf.delete_mark(mark)
        del blocks[same:]
    firsts = {spec[1]: first for spec, _, first, _ in blocks if first}
    for spec in specs[same:]:
        i, topic, last, title, hue, clock, name, text, pending = spec
        at, first = buf.create_mark(None, buf.get_end_iter(), True), None
        tags = ("pending",) if pending else ()
        if topic is not None:
            tint, label = topic_tags(buf, hue)
            tags = (tint,)
            if topic != last:
                buf.insert_with_tags_by_name(buf.get_end_iter(), ("\n\n" if i else "") + f"● {title}", label, tint)
                if topic not in firsts:
                    first = firsts[topic] = buf.create_mark(None, buf.get_end_iter(), True)
                buf.insert_with_tags_by_name(buf.get_end_iter(), "\n", tint)
            elif i:
                buf.insert_with_tags_by_name(buf.get_end_iter(), "\n\n", tint)
        elif i:
            buf.insert(buf.get_end_iter(), "\n\n")
        begins = buf.create_mark(None, buf.get_end_iter(), True)
        widget = control(i) if control and not pending else None
        if widget:
            anchor = buf.create_child_anchor(buf.get_end_iter())
            view.add_child_at_anchor(widget, anchor)
            buf.insert_with_tags_by_name(buf.get_end_iter(), " ", "clock", *tags)
        buf.insert_with_tags_by_name(buf.get_end_iter(), f"{clock}\t", "clock", *tags)  # (to the gutter's edge)
        buf.insert_with_tags_by_name(buf.get_end_iter(), f"{name}  ", "who", *tags)
        buf.insert_with_tags_by_name(buf.get_end_iter(), text, *tags)
        buf.apply_tag_by_name("hang", buf.get_iter_at_mark(begins), buf.get_end_iter())
        blocks.append((spec, at, first, begins))
    shown["chars"] = buf.get_char_count()
    view.paragraphs = [(begins, blocks[k + 1][1] if k + 1 < len(blocks) else None)
                       for k, (_, _, _, begins) in enumerate(blocks)]
    return firsts


def small_model(session, found):
    """A warning, if topics are being (or were) found by the smaller, less reliable model on the CPU."""
    why = "your graphics card {}" if llm.gpu_present() else "this computer has no graphics card it can use"
    if session:
        return (f"Warning: using a less reliable model because {why.format('is busy')}." if llm.server.mode == "cpu"
                else None)
    if found and found.small and found.topics:
        return f"These topics were found with a less reliable model, as {why.format('was busy')}."
    return None


def open_uri(path):
    Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)


class TranscriptsPage:
    EMPTY = "No transcripts yet"
    HOW = "To start one, hold Ctrl+Win, lift Win and press it again."
    LISTENING = "Listening to this computer's speakers and microphone"

    def __init__(self, hub):
        self.hub, self.app = hub, hub.app
        self.shown_item, self.paths, self.seen, self.firsts = None, None, None, {}
        self.offsets, self.controls, self.hovered, self.drawn = [], {}, None, None  # (see paragraph_control)
        unlisten = self.app.playback.listen(self.playback_changed)
        hub.win.connect("destroy", lambda *_: unlisten())
        GLib.timeout_add(1000, self.tick)  # (the recording's clock: it runs whether or not anything's heard)
        self.widget = d.classes(Gtk.Box(), "page")

        # the list of transcripts
        self.list = d.classes(Gtk.ListBox(), "pick")
        self.list.connect("row-selected", lambda _, row: row and self.show(row.item))
        left = d.classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=160), "panel")
        left.pack_start(d.classes(Gtk.Label(label="Transcripts", xalign=0, margin=16, margin_bottom=8), "title"),
                        False, False, 0)
        left.pack_start(d.scrolled(self.list), True, True, 0)
        folder = d.button("Open folder", lambda: (transcript.FOLDER.mkdir(parents=True, exist_ok=True),
                                                  open_uri(transcript.FOLDER)), "quiet", icon="folder", small=True)
        folder.set_halign(Gtk.Align.START)
        folder.set_margin_start(12)
        folder.set_margin_bottom(12)
        left.pack_end(folder, False, False, 0)

        # the transcript shown
        self.heading = d.text("", "headline", ellipsize=True)
        self.status = d.status_pill("")
        self.meta = d.text("", "small", ellipsize=True)
        under = Gtk.Box(spacing=8)
        under.pack_start(self.status, False, False, 0)
        under.pack_start(self.meta, False, False, 0)
        self.pause_btn = d.icon_button("pause", "Pause", self.toggle_pause)  # (icons: the column stays narrow)
        self.live_actions = Gtk.Box(spacing=8)
        self.live_actions.pack_start(self.pause_btn, False, False, 0)
        self.live_actions.pack_start(d.button("Stop", lambda: self.app.stop_transcribing(), "primary", icon="stop"),
                                     False, False, 0)
        self.saved_actions = Gtk.Box(spacing=2)
        self.play_btn = d.icon_button("play", "Play", self.play_all)
        self.saved_actions.pack_start(self.play_btn, False, False, 0)
        copy = d.icon_button("copy", "Copy all", lambda: (
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.shown_item["path"].read_text(), -1),
            d.flash(copy, "Copied", "Copy all", "copy")))
        for b in (copy, d.icon_button("open", "Open file", lambda: open_uri(self.shown_item["path"])),
                  d.icon_button("trash", "Delete", self.delete, danger=True)):
            self.saved_actions.pack_start(b, False, False, 0)
        header = d.classes(Gtk.Box(spacing=8), "page-header")
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        words.pack_start(self.heading, False, False, 0)
        words.pack_start(under, False, False, 0)
        header.pack_start(words, True, True, 0)
        for box in (self.saved_actions, self.live_actions):
            box.set_valign(Gtk.Align.START)
            box.set_no_show_all(True)
            header.pack_end(box, False, False, 0)
        self.people = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                                  margin_start=24, margin_end=24, margin_bottom=8, no_show_all=True, homogeneous=False,
                                  max_children_per_line=40)  # (wraps)
        self.text = transcript_view()
        self.text.connect("motion-notify-event", lambda _, ev: self.hover(self.paragraph_at(ev.x, ev.y)))
        self.text.connect("leave-notify-event",  # (not when it's onto a paragraph's own button)
                          lambda _, ev: ev.detail != Gdk.NotifyType.INFERIOR and self.hover(None))
        self.scroll = d.scrolled(self.text)
        # (a wrapping text view says the width it's laid out at is the narrowest it can be, so with "never" the
        # transcript could only ever get a little narrower than it is: "external" lets it be any width)
        self.scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.AUTOMATIC)
        # at the end, it stays there as more is heard: moved as the text grows, before it's drawn (moving it a
        # moment later showed the new line below the bottom, then jumped). It stops only when you scroll up
        # (not whenever it isn't at the end: a wheel's or touchpad's scrolling glides on, to where the end was
        # before the text grew), and follows again once you're back at the end
        self.following, self.moving = True, False
        adj = self.scroll.get_vadjustment()
        adj.connect("value-changed", self.scrolled)
        adj.connect("changed", lambda _: self.follow())
        self.text.connect("scroll-event", self.wheel)
        self.text.connect("key-press-event", self.key)
        self.scroll.get_vscrollbar().connect("change-value", self.scroll_dragged)
        self.empty = d.empty_state("transcript", self.EMPTY, self.HOW)
        self.content = Gtk.Stack(width_request=300)  # (narrower, a transcript is unreadable)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.pack_start(header, False, False, 0)
        main.pack_start(self.people, False, False, 0)
        main.pack_start(self.scroll, True, True, 0)
        self.content.add_named(main, "transcript")
        self.content.add_named(self.empty, "empty")

        # its topics and its summary, a tab each
        self.topics = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_bottom=12)
        self.topics.shown = None
        self.summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=16, margin_top=4)
        self.summary.shown = None
        self.tabs = Gtk.Stack()
        self.tabs.add_named(d.scrolled(self.topics), "Topics")
        self.tabs.add_named(d.scrolled(self.summary), "Summary")
        self.switch = d.segmented(("Topics", "Summary"), "Topics", self.tabs.set_visible_child_name)
        self.switch.set_margin_start(12)
        self.switch.set_margin_end(12)
        self.switch.set_margin_top(12)
        self.warning = Gtk.Box(margin_start=12, margin_end=12, margin_top=8, no_show_all=True)
        self.right = d.classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200), "panel")
        for w, grow in ((self.switch, False), (self.warning, False), (self.tabs, True)):
            self.right.pack_start(w, grow, grow, 4 if w is self.tabs else 0)

        # list | transcript | topics: the list and the rail keep the width they're dragged to (resize=False),
        # the transcript takes the rest
        self.panes = self.app.settings.get("transcript_panes", list(self.PANES))
        # (each divider: a hairline with 2 px either side to grab, in the colour of the pane beside it)
        self.outer = d.classes(Gtk.Paned(wide_handle=False), "after-panel")
        self.inner = d.classes(Gtk.Paned(wide_handle=False), "before-panel")
        self.outer.pack1(left, False, False)
        self.outer.pack2(self.inner, True, False)
        self.inner.pack1(self.content, True, False)
        self.inner.pack2(self.right, False, False)
        self.outer.set_position(self.panes[0])
        self.inner.connect("size-allocate", self.place_rail)
        for paned in (self.outer, self.inner):
            paned.connect("notify::position", lambda *_: self.dragged())
        self.widget.pack_start(self.outer, True, True, 0)
        self.saving = None

    PANES = (240, 280)  # px: the list's and the rail's widths, until they're dragged

    def place_rail(self, inner, room):
        """The first time there's room: the rail as wide as it was left (after that, the window growing or
        shrinking leaves it be, as the transcript takes up the difference)."""
        if not getattr(self, "placed", False):
            self.placed = True
            GLib.idle_add(lambda: inner.set_position(max(0, room.width - self.panes[1])) and False)

    def dragged(self):
        """Remember how wide the list and the rail were left (once dragging stops)."""
        if not getattr(self, "placed", False):
            return
        self.panes = [self.outer.get_position(), self.inner.get_allocated_width() - self.inner.get_position()]
        if self.saving:
            GLib.source_remove(self.saving)
        self.saving = GLib.timeout_add(500, lambda: (self.app.settings.update(transcript_panes=self.panes),
                                                     setattr(self, "saving", None)) and False)

    @property
    def win(self):
        return self.hub.win

    @property
    def closed(self):
        return self.hub.closed

    def current(self):
        return self.app.session

    def shown(self, recording=False, **_):
        self.changed()
        if recording:
            self.show_recording()

    def tick(self):
        """Every second: the clock of the transcript being recorded, if it's shown (the rest changes only as
        something's heard: a quiet stretch, or a microphone switched off, mustn't stop the clock)."""
        if self.closed:
            return False
        session = self.current()
        if session and self.shown_item and self.shown_item.get("recording"):
            self.status.text.set_text(transcript.clock(session.now()))
        return True

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
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8, margin_start=10, margin_end=10)
        top = Gtk.Box(spacing=6)
        top.pack_start(d.text(f"{it['started']:%a %d %b · %H:%M}", "strong"), False, False, 0)
        row.length = d.text("", "caption")
        top.pack_end(row.length, False, False, 0)
        box.pack_start(top, False, False, 0)
        row.start = d.text("", "small", ellipsize=True, max_chars=30)
        box.pack_start(row.start, False, False, 0)
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
                select = self.shown_item and self.shown_item["path"]
            self.rebuild(items, select)
        else:
            for row in self.list.get_children():
                if row.item.get("recording"):
                    self.describe(row)
            if self.shown_item and self.shown_item.get("recording"):
                self.show(self.shown_item)
            elif self.shown_item and self.shown_item.get("changed") is not None:  # e.g. its last topics, just found
                again = transcript.read(self.shown_item["path"])
                if again and again["changed"] != self.shown_item["changed"]:
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
            self.shown_item = None
            self.content.set_visible_child_name("empty")
            self.right.hide()
            return
        self.content.set_visible_child_name("transcript")
        self.right.show()
        self.list.select_row(next((r for r in rows if r.item["path"] == select), rows[0]))

    def show(self, item):
        session = self.current() if item.get("recording") else None
        if item.get("recording") and not session:  # stopped since: show it as saved
            item = transcript.read(item["path"]) or item
        if item is not self.shown_item:
            self.following = bool(session)  # (one being recorded is shown at its end; a saved one, from the start)
        if self.shown_item and item["path"] != self.shown_item["path"]:
            if self.app.playback.playing(self.shown_item["path"]):
                self.app.playback.stop()  # (another transcript: playing one that isn't shown can't be stopped)
            self.hovered = None
        self.shown_item = item
        self.heading.set_text(f"{item['started']:%A %-d %B, %H:%M}")
        self.saved_actions.set_visible(not session)
        self.live_actions.set_visible(bool(session))
        for box in (self.saved_actions, self.live_actions):
            for b in box.get_children():
                b.show_all()
        self.status.set_visible(bool(session))
        self.play_btn.set_visible(not session and bool(transcript.recordings(item["path"])))
        if session:
            self.pause_btn.set_tooltip_text("Resume" if session.paused else "Pause")
            self.pause_btn.icon.set_icon("record" if session.paused else "pause")
            dot = self.status.get_children()[0].get_style_context()
            (dot.add_class if session.paused else dot.remove_class)("paused")
            self.status.text.set_text(transcript.clock(session.now()))
            self.status.set_tooltip_text("Paused" if session.paused else "Recording")
            self.meta.set_text("Nothing is being added" if session.paused else self.LISTENING)
            self.offsets = []  # (not played back while it's recorded)
            found, marks, people = session.topic_view()
            paragraphs = session.paragraphs()
            self.firsts = show_transcript(self.text, paragraphs, session.previews(), found, marks)
            if not paragraphs and not session.previews():
                self.text.get_buffer().set_text("Nothing heard yet.")
        else:
            self.meta.set_text(item.get("length", ""))
            paragraphs = item.get("paragraphs", [])
            found = transcript.read_topics(item["path"])
            marks, people = (found.of, found.people(transcript.numbered(paragraphs))) if found else ({}, [])
            playable = bool(transcript.recordings(item["path"]))
            self.offsets = transcript.offsets(item) if playable else []
            self.firsts = show_transcript(self.text, paragraphs, found=found, marks=marks,
                                          control=self.paragraph_control if playable else None)
            if not paragraphs:
                self.text.get_buffer().set_text("Nothing was heard.")
        self.show_topics(found, people, bool(session), bool(item.get("paragraphs")), small_model(session, found))
        self.show_summary(session.summary if session else transcript.read_summary(item["path"]), bool(session),
                          bool(item.get("paragraphs")))
        nameable = not session or session.voices  # without the voice model, a recording's voices are all "Them"
        self.show_people(transcript.labels(session.paragraphs() if session else item.get("paragraphs", []))
                         if nameable else [])
        self.drawn = None
        self.playback_changed()

    def show_topics(self, found, people, live, heard, warning=None):
        """The topics of the transcript shown: each a card edged in its colour, with who brought it up and who
        else spoke on it; the one being talked about now marked, while it's recorded. warning: that they're found
        by the less reliable model, or None."""
        topics_ = found.topics if found else []
        now = found.now if found and live else None
        shown = (self.shown_item["path"], json.dumps(topics_, sort_keys=True), people, now, live, heard, warning,
                 d.scheme)
        if shown == self.topics.shown:
            return
        self.topics.shown = shown
        for kid in self.topics.get_children():
            kid.destroy()
        for kid in self.warning.get_children():
            kid.destroy()
        if warning:
            strip = d.warning_strip(warning)
            strip.show_all()  # (its box is no_show_all, so it isn't shown with the window: only when there's one)
            self.warning.pack_start(strip, True, True, 0)
        self.warning.set_visible(bool(warning))
        if not topics_:
            hint = ("The topics of the conversation appear here as it goes on, about a minute in." if live else
                    "No topics were found." if heard else "Nothing was heard.")
            self.topics.pack_start(d.text(hint, "small", wrap=True, max_chars=34, margin_start=16, margin_end=16),
                                   False, False, 0)
        for i, t in enumerate(topics_):
            card = d.classes(Gtk.Button(), "topic-card", f"topic-edge-{found.hue(i)}", "now" if i == now else None)
            card.connect("clicked", lambda _, i=i: self.go_to_topic(i))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            head = Gtk.Box(spacing=6)
            head.pack_start(d.text(t["title"], "strong", wrap=True, max_chars=26), True, True, 0)
            if i == now:
                head.pack_end(d.chip("Now", accent=True), False, False, 0)
            box.pack_start(head, False, False, 0)
            who = people[i] if i < len(people) else []
            if who:
                box.pack_start(d.text(f"{who[0]} brought it up" + (f" · with {', '.join(who[1:])}" if who[1:] else ""),
                                      "caption", wrap=True, max_chars=34), False, False, 0)
            for point in t["points"]:
                box.pack_start(d.text(point, "small", wrap=True, max_chars=34), False, False, 0)
            card.add(box)
            self.topics.pack_start(card, False, False, 0)
        self.topics.show_all()

    # --- playing it back ---
    # Everything is drawn from the app's playback (what's playing, and where it's got to), never kept here too: the
    # Play button above (Stop while any of this transcript plays), and before each paragraph's time a play button,
    # shown while it's hovered, and while it's the paragraph being played (highlighted, its button Stop): as the
    # whole call plays, that moves on from paragraph to paragraph.
    def paragraph_control(self, i):
        """Paragraph i's play button (show_transcript puts it before its time)."""
        b = d.classes(d.icon_button("play", "Play this paragraph", lambda: self.play_paragraph(i)), "inline")
        b.icon.size = 12
        b.icon.set_size_request(12, 12)
        b.show_all()
        b.set_child_visible(False)  # (until it's hovered: it keeps its room, so the text doesn't move)
        b.connect("enter-notify-event", lambda *_: (self.hover(i), self.pointer("pointer")) and False)
        b.connect("leave-notify-event", lambda *_: self.pointer("text") and False)
        self.controls[i] = b
        return b

    def pointer(self, name):
        """The pointer over the transcript: "pointer" (a hand) over a play button, else "text" (it's selectable)."""
        window = self.text.get_window(Gtk.TextWindowType.TEXT)
        if window:
            window.set_cursor(Gdk.Cursor.new_from_name(window.get_display(), name))

    def play_all(self):
        path = self.shown_item["path"]
        if self.app.playback.playing(path):
            self.app.playback.stop()
        else:
            self.app.playback.play_transcript(path)

    def play_paragraph(self, i):
        """Play paragraph i, from its time to the next paragraph's; or, if it's the one playing, stop."""
        if i == self.playing_paragraph():
            return self.app.playback.stop()
        start = self.offsets[i]
        end = min((o for o in self.offsets if o > start), default=None)
        self.app.playback.play_transcript(self.shown_item["path"], start, end)

    def playing_paragraph(self):
        """The paragraph being played (of the transcript shown), or None."""
        now = self.shown_item and self.offsets and self.app.playback.playing(self.shown_item["path"])
        if not now:
            return None
        at = now.at()
        if now.end is not None:  # (its end is where the next paragraph starts: that one isn't being played)
            at = min(at, now.end - 0.05)
        before = [(o, i) for i, o in enumerate(self.offsets) if o <= at + 0.01]
        return max(before)[1] if before else 0

    def paragraph_at(self, x, y):
        """The paragraph at (x, y) in the text view's window, or None."""
        if not self.offsets:
            return None
        bx, by = self.text.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(x), int(y))
        found, at = self.text.get_iter_at_location(bx, by)
        if not found:
            return None
        buf, off = self.text.get_buffer(), at.get_offset()
        for i, (begins, ends) in enumerate(getattr(self.text, "paragraphs", [])[:len(self.offsets)]):
            end = buf.get_iter_at_mark(ends).get_offset() if ends else buf.get_char_count()
            if buf.get_iter_at_mark(begins).get_offset() <= off < end:
                return i
        return None

    def hover(self, i):
        if i != self.hovered:
            self.hovered = i
            self.playback_changed()
        return False

    def playback_changed(self):
        """Draw what's playing: the Play button above, and the paragraph being played."""
        if self.closed or not self.shown_item:
            return
        playing = bool(self.app.playback.playing(self.shown_item["path"]))
        current = self.playing_paragraph()
        drawn = (self.shown_item["path"], playing, current, self.hovered, len(self.offsets))
        if drawn == self.drawn:
            return
        self.drawn = drawn
        self.play_btn.icon.set_icon("stop" if playing else "play")
        self.play_btn.set_tooltip_text("Stop" if playing else "Play")
        for i in range(len(self.offsets)):
            b = self.controls.get(i)
            if not b:
                continue
            b.set_child_visible(i in (current, self.hovered))
            b.icon.set_icon("stop" if i == current else "play")
            b.set_tooltip_text("Stop" if i == current else "Play this paragraph")
        buf = self.text.get_buffer()
        tag = buf.get_tag_table().lookup("playing")
        buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
        paragraphs = getattr(self.text, "paragraphs", [])
        if current is not None and current < len(paragraphs):
            begins, ends = paragraphs[current]
            tag.set_priority(buf.get_tag_table().get_size() - 1)  # (over its topic's tint)
            buf.apply_tag(tag, buf.get_iter_at_mark(begins), buf.get_iter_at_mark(ends) if ends else buf.get_end_iter())

    def show_summary(self, found, live, heard):
        """The summary of the transcript shown: its sections and bullets, and whether it's still being written (or
        its final pass is waiting for the graphics card: waiting.py)."""
        text, final = (found.text, found.final) if found else ("", False)
        path, wait = self.shown_item["path"], self.app.waiting
        pending = None if live else ("waiting" if any(j.path == path for j in wait.jobs) else
                                     "writing" if wait.running and wait.running.path == path else None)
        shown = (path, text, final, live, heard, pending, d.scheme)
        if shown == self.summary.shown:
            return
        self.summary.shown = shown
        for kid in self.summary.get_children():
            kid.destroy()
        if pending == "waiting":
            box = Gtk.Box(spacing=8)
            box.pack_start(d.text("Waiting for the graphics card to write the final summary.", "small", wrap=True,
                                  max_chars=26), True, True, 0)
            box.pack_end(d.button("Use the CPU", wait.use_cpu, small=True, tooltip="Slower, and a little rougher"),
                         False, False, 0)
            self.summary.pack_start(box, False, False, 0)
        elif pending == "writing":
            self.summary.pack_start(d.text("Writing the final summary…", "small", wrap=True, max_chars=34),
                                    False, False, 0)
        if not text and not pending:
            hint = ("A summary of the conversation appears here a few minutes in, and is kept up to date as it goes on."
                    if live else "No summary for this one." if heard else "Nothing was heard.")
            self.summary.pack_start(d.text(hint, "small", wrap=True, max_chars=34), False, False, 0)
        elif text:
            top = Gtk.Box(spacing=6)
            status = ("Kept up to date as it goes on" if live else "The final summary" if final else
                      "As it was when it stopped")
            top.pack_start(d.text(status, "caption", wrap=True), True, True, 0)
            copy = d.icon_button("copy", "Copy summary", lambda: (
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1),
                d.flash(copy, "Copied", "Copy summary", "copy")))
            top.pack_end(copy, False, False, 0)
            self.summary.pack_start(top, False, False, 0)
            first = True
            for kind, markup in summary.markup_lines(text):
                if kind == "heading":
                    lab = d.text("", "strong", wrap=True, max_chars=34, margin_top=0 if first else 10)
                elif kind == "bullet":
                    lab = d.text("", "small", wrap=True, max_chars=34, margin_start=4)
                    markup = f"•  {markup}"
                else:
                    lab = d.text("", "small", wrap=True, max_chars=34)
                lab.set_markup(markup)
                lab.set_selectable(True)
                lab.set_can_focus(False)
                self.summary.pack_start(lab, False, False, 0)
                first = False
        self.summary.show_all()

    def waiting_changed(self):
        """The saved transcript shown may have started or stopped waiting for its final pass (waiting.py)."""
        it = self.shown_item
        if it and not it.get("recording") and not self.closed:
            self.show_summary(transcript.read_summary(it["path"]), False, bool(it.get("paragraphs")))

    def go_to_topic(self, i):
        """Scroll the transcript to where topic i is first talked about."""
        mark = self.firsts.get(i)
        if mark and not mark.get_deleted():
            self.following = False
            self.text.scroll_to_mark(mark, 0.0, True, 0.0, 0.1)

    def show_people(self, labels):
        """A button per voice in the transcript shown, to name it."""
        if labels == getattr(self.people, "labels", None):
            return
        self.people.labels = labels
        for kid in self.people.get_children():
            kid.destroy()
        self.people.add(d.text("Speakers", "caption", margin_end=4))
        for label in labels:
            self.people.add(d.button(label, lambda who=label: self.rename(who), small=True, tooltip=f"Rename {label}"))
        for kid in self.people.get_children():
            kid.show_all()
        self.people.set_visible(bool(labels))

    def rename(self, label):
        it, session = self.shown_item, self.current()
        live = it.get("recording") and session
        remembers = voices.remembering() and (live or transcript.voiceprints(it["path"]).exists())
        name = huds.ask_name(self.win, label, remembers)
        if not name:
            return
        if live:
            session.rename(label, name)  # its on_change shows it
        else:
            transcript.rename(it["path"], label, name)
            self.shown_item = None
            self.paths = None  # read it again
            self.changed()
            self.list.select_row(next(r for r in self.list.get_children() if r.item["path"] == it["path"]))

    def at_end(self):
        adj = self.scroll.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 20

    def scrolled(self, _):
        if self.moving:
            return
        if self.at_end():
            self.following = True
        else:  # moved, not by you (you scrolling up stops it following first): back to the end
            self.follow()

    def wheel(self, _, ev):
        up = ev.direction == Gdk.ScrollDirection.UP or (ev.direction == Gdk.ScrollDirection.SMOOTH and ev.delta_y < 0)
        if up:
            self.following = False
        return False

    def key(self, _, ev):
        if Gdk.keyval_name(ev.keyval) in ("Up", "Page_Up", "Home", "KP_Up", "KP_Page_Up", "KP_Home"):
            self.following = False
        return False

    def scroll_dragged(self, bar, _, value):
        adj = bar.get_adjustment()
        self.following = value >= adj.get_upper() - adj.get_page_size() - 20
        return False

    def follow(self):
        """Keep it at the end, if it's following (the text has grown, or the window's changed size)."""
        adj = self.scroll.get_vadjustment()
        if self.following and adj.get_value() != adj.get_upper() - adj.get_page_size():
            self.moving = True
            adj.set_value(adj.get_upper() - adj.get_page_size())
            self.moving = False

    def toggle_pause(self):
        session = self.current()
        if session:
            session.pause(not session.paused)

    def delete(self):
        it = self.shown_item
        if it and huds.confirm(self.win, f"Delete the transcript from {it['started']:%a %d %b, %H:%M}?",
                               "Its recordings are deleted too. This can't be undone.", "Delete"):
            if self.app.playback.playing(it["path"]):
                self.app.playback.stop()
            self.app.waiting.forget(it["path"])  # (its final pass, if it's still to do)
            transcript.delete(it["path"])
            self.shown_item = None
            self.changed()
