"""The window asking which transcripts to give Claude Code (sharing.py): what it's looking for, a warning that what you
share is sent to Anthropic, and every transcript, each with a dropdown: Don't share, its summary, or the whole
transcript. Those that mention what it's looking for come first, under a heading of their own, set to share their
summary: plain word matching, of the request's words that say what it's about (not everyday ones like "about",
"recent" or "team": every call has those), in each transcript's summary and topics (not all it said: a long call
says almost every word somewhere), at least two of them if the request has three or more; the rest under "Other
transcripts", not shared (dimmed). Each heading has None, to set its group back to Don't share, and stays pinned at
the top of the list while you scroll through its group. Above the buttons, what will be shared, whatever you've
scrolled to. Share (once something's chosen) or Refuse; closing it, or Escape, is refusing. Drag it by its
background to see what's behind it."""
import re

from gi.repository import Gtk

from . import design as d
from . import transcript

TITLE = "Share transcripts with Claude Code?"
DIM = 0.45  # how a transcript that isn't being shared looks
MATCHED, OTHERS = "Mentions what Claude is looking for", "Other transcripts"
_EVERYDAY = """
about above after again against also among another anyone anything around asked back because been before being
below between both call calls came come could decided decision decisions discuss discussed discussing discussion
does doing done down during each either else even ever every everyone everything find first from further gave
give given goes going good great have having help here into itself just keep kind know last later like look
looking made make many maybe meeting meetings might more most much must need needs never next notes nothing once
only other others over part please point points pretty quite rather really recent recently relevant request
requests right said same says should show since some someone something soon still such sure take talk talked
talking team tell than that their them then there these they thing things think this those though through time
today told took under until update upon used using very want wanted week well went were what whatever when where
whether which while whole will with within without work would year yesterday your yours
"""
EVERYDAY = set(_EVERYDAY.split())  # words of 4+ letters too common in a request to say what it's about


def keywords(topic):
    """The words of a request that say what it's about: 4+ letters, not EVERYDAY."""
    return sorted({w for w in re.findall(r"[a-z0-9]{4,}", topic.lower())} - EVERYDAY)


def relevance(item, words):
    """Which of words (lower case) its summary and topics mention (not its whole text: a long call says almost
    every word somewhere)."""
    path = item["path"]
    found = transcript.read_summary(path)
    topics = transcript.read_topics(path)
    text = " ".join([found.text if found else "",
                     *(f"{t['title']} {' '.join(t['points'])}" for t in (topics.topics if topics else []))]).lower()
    return [w for w in words if re.search(rf"\b{re.escape(w)}", text)]


def enough(matched, words):
    """Whether a transcript matching these of words is about it: two of them if there are three or more."""
    return len(matched) >= (2 if len(words) >= 3 else 1)


def when(it):
    return f"{it['started']:%a %-d %b %H:%M}"


class ShareWindow:
    """answer([(path, "summary" | "transcript")]) once you Share, or answer(None) if you refuse (however)."""

    def __init__(self, topic, where, answer):
        self.answer, self.answered = answer, False
        self.hud = d.Hud(TITLE, width=560)
        self.hud.on_escape = self.refuse
        self.hud.win.connect("delete-event", lambda *_: (self.refuse(), True)[1])
        self.hud.heading(TITLE, "transcript")
        asker = f"Claude Code (in {where})" if where else "Claude Code"
        self.hud.box.pack_start(d.text(f"{asker} is looking for transcripts about:", "body", wrap=True, max_chars=64),
                                False, False, 0)
        self.hud.box.pack_start(d.classes(d.text(topic, "strong", wrap=True, max_chars=64), "quote"),
                                False, False, 0)
        warning = ("Whatever you share is sent to Anthropic as part of that conversation. Nothing is shared unless "
                   "it's chosen below.")
        self.hud.box.pack_start(d.warning_strip(warning), False, False, 0)

        words = keywords(topic)
        items = [(it, relevance(it, words)) for it in transcript.saved() if it["paragraphs"]]
        items = [(it, matched if enough(matched, words) else []) for it, matched in items]
        items.sort(key=lambda x: -x[0]["started"].timestamp())
        groups = [(MATCHED, [x for x in items if x[1]]), (OTHERS, [x for x in items if not x[1]])]
        groups = [(title, group) for title, group in groups if group]
        self.rows, self.headers = [], []  # rows: (item, kind(), set_kind(value), group's title)
        self.listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_end=16)  # (clear of the
        # scrollbar, which shows over the list when the pointer's on it)
        for title, group in groups:
            if len(groups) > 1:  # (with only one kind, it needs no heading)
                header = self.header(title, len(group))
                self.headers.append((title, len(group), header))
                self.listing.pack_start(header, False, False, 0)
            for it, matched in group:
                self.listing.pack_start(self.row(it, matched, title), False, False, 0)
        if not items:
            self.listing.pack_start(d.text("There are no transcripts.", "small"), False, False, 0)
        self.scroll = d.scrolled(self.listing)
        self.scroll.set_size_request(-1, 320)
        # the heading of the group at the top of the list, pinned there once its own has scrolled out of sight
        self.pinned = d.classes(Gtk.Box(valign=Gtk.Align.START, margin_end=16, no_show_all=True), "pinned")
        self.pinned.title = None
        overlay = Gtk.Overlay()
        overlay.add(self.scroll)
        overlay.add_overlay(self.pinned)
        self.scroll.get_vadjustment().connect("value-changed", lambda _: self.pin())
        self.hud.box.pack_start(overlay, True, True, 0)
        self.sharing = d.text("", "small", wrap=True, max_chars=64)
        self.hud.box.pack_start(self.sharing, False, False, 0)
        self.share = d.button("Share", self.give, "primary")
        self.hud.buttons(d.button("Refuse", self.refuse), self.share)
        self.chosen()
        self.hud.show()
        self.hud.win.set_urgency_hint(True)

    def header(self, title, n):
        """A group's heading: its title, how many, and None (set them all back to Don't share)."""
        box = Gtk.Box(spacing=8, margin_top=8, margin_bottom=2)
        box.pack_start(d.classes(Gtk.Label(label=f"{title} ({n})", xalign=0), "field-label"), True, True, 0)
        none = d.button("None", lambda: self.none(title), "quiet", small=True,
                        tooltip=f"Don't share any of: {title.lower()}")
        box.pack_end(none, False, False, 0)
        return box

    def row(self, it, matched, group):
        found = transcript.read_summary(it["path"])
        overview = re.sub(r"^#+ .*$|\*\*", "", found.text, flags=re.M).strip() if found and found.text else ""
        gist = overview or " ".join(t for _, _, t in it["paragraphs"])
        box = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head = f"{it['started']:%a %-d %b %Y, %H:%M}" + (f" · {it['length']}" if it["length"] else "")
        words.pack_start(d.text(head, "strong"), False, False, 0)
        if matched:
            words.pack_start(d.text("Mentions " + ", ".join(matched), "caption"), False, False, 0)
        words.pack_start(d.text(gist[:220] + ("…" if len(gist) > 220 else ""), "small", wrap=True, max_chars=56),
                         False, False, 0)
        box.pack_start(words, True, True, 0)
        kinds = [(None, "Don't share")] + ([("summary", "Its summary")] if overview else []) + \
            [("transcript", "Whole transcript")]
        values = [v for v, _ in kinds]
        start = "summary" if matched and overview else None  # (a summary, not a whole transcript, unasked)
        kind = d.combo(kinds, start, lambda v: (words.set_opacity(1.0 if v else DIM), self.chosen()))
        words.set_opacity(1.0 if start else DIM)  # (not being shared: plainly so)
        kind.set_valign(Gtk.Align.START)
        kind.set_tooltip_text(f"Share {it['started']:%a %-d %b, %H:%M}?")
        box.pack_end(kind, False, False, 0)
        self.rows.append((it, lambda: values[kind.get_active()], lambda v: kind.set_active(values.index(v)), group))
        return box

    def none(self, group):
        for _, _, set_kind, title in self.rows:
            if title == group:
                set_kind(None)

    def pin(self):
        """Pin the heading of the group at the top of the list there, once its own has scrolled out of sight."""
        top = self.scroll.get_vadjustment().get_value()
        current = None
        for title, n, header in self.headers:
            y = header.translate_coordinates(self.listing, 0, 0)
            if y and y[1] + header.get_allocated_height() // 2 <= top:
                current = (title, n)
        if current != self.pinned.title:
            self.pinned.title = current
            for kid in self.pinned.get_children():
                kid.destroy()
            if current:
                header = self.header(*current)
                self.pinned.pack_start(header, True, True, 0)
                header.show_all()  # (not the box's show_all: it's no_show_all, so that does nothing)
            self.pinned.set_visible(bool(current))

    def picked(self):
        return [(it, kind()) for it, kind, _, _ in self.rows if kind()]

    def chosen(self):
        """What will be shared, said above the buttons (whatever's scrolled into view); Share once there's any."""
        picked = self.picked()
        summaries = [when(it) for it, k in picked if k == "summary"]
        wholes = [when(it) for it, k in picked if k == "transcript"]
        parts = ([f"the summar{'ies' if len(summaries) > 1 else 'y'} of {join(summaries)}"] if summaries else []) + \
                ([f"the whole transcript{'s' if len(wholes) > 1 else ''} of {join(wholes)}"] if wholes else [])
        self.sharing.set_text(f"Sharing {' and '.join(parts)}." if parts else "Nothing chosen to share.")
        self.share.set_sensitive(bool(picked))

    def give(self):
        if self.picked():  # (Share is greyed out until something's chosen)
            self.finish([(it["path"], kind) for it, kind in self.picked()])

    def refuse(self):
        self.finish(None)

    def finish(self, shared):
        if not self.answered:
            self.answered = True
            self.answer(shared)
        if self.hud.open:
            self.hud.close()

    def close(self):
        """Not answered in time: refused."""
        self.finish(None)

    @property
    def open(self):
        return self.hud.open


def join(names):
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
