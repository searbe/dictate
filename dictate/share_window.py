"""The window asking which transcripts to give Claude Code (sharing.py): what it's looking for, a warning that what
you share is sent to Anthropic, and every transcript (those that mention what it's looking for first), each with a
dropdown: Don't share (as they all start), its summary, or the whole transcript. Share (once something's chosen) or
Refuse; closing it, or Escape, is refusing. Drag it by its background to see what's behind it."""
import re

from gi.repository import Gtk

from . import design as d
from . import transcript

TITLE = "Share transcripts with Claude Code?"
DIM = 0.45  # how a transcript that isn't being shared looks


def relevance(item, words):
    """Which of words (lower case) its summary, topics or transcript mention."""
    path = item["path"]
    found = transcript.read_summary(path)
    topics = transcript.read_topics(path)
    text = " ".join([found.text if found else "", *(t["title"] for t in (topics.topics if topics else [])),
                     *(t for _, _, t in item["paragraphs"])]).lower()
    return [w for w in words if re.search(rf"\b{re.escape(w)}", text)]


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
                   "you choose it.")
        self.hud.box.pack_start(d.warning_strip(warning), False, False, 0)
        words = sorted({w for w in re.findall(r"[a-z0-9]{4,}", topic.lower())})
        items = [(it, relevance(it, words)) for it in transcript.saved() if it["paragraphs"]]
        items.sort(key=lambda x: (-len(x[1]), -x[0]["started"].timestamp()))
        self.rows = []
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_end=16)  # (clear of the
        # scrollbar, which shows over the list when the pointer's on it)
        for it, matched in items:
            listing.pack_start(self.row(it, matched), False, False, 0)
        if not items:
            listing.pack_start(d.text("There are no transcripts.", "small"), False, False, 0)
        scroll = d.scrolled(listing)
        scroll.set_size_request(-1, 320)
        self.hud.box.pack_start(scroll, True, True, 0)
        self.share = d.button("Share", self.give, "primary")
        self.share.set_sensitive(False)
        self.hud.buttons(d.button("Refuse", self.refuse), self.share)
        self.hud.show()
        self.hud.win.set_urgency_hint(True)

    def row(self, it, matched):
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
        kind = d.combo(kinds, None, lambda v: (words.set_opacity(1.0 if v else DIM), self.chosen()))
        words.set_opacity(DIM)  # (until it's chosen: plainly not being shared)
        kind.set_valign(Gtk.Align.START)
        kind.set_tooltip_text(f"Share {it['started']:%a %-d %b, %H:%M}?")
        box.pack_end(kind, False, False, 0)
        self.rows.append((it["path"], lambda: values[kind.get_active()]))
        return box

    def picked(self):
        return [(path, kind()) for path, kind in self.rows if kind()]

    def chosen(self):
        n = len(self.picked())
        self.share.set_sensitive(bool(n))
        self.share.set_label_text(f"Share {n}" if n else "Share")

    def give(self):
        if self.picked():  # (Share is greyed out until something's chosen)
            self.finish(self.picked())

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
