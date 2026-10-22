"""The topics of a conversation, kept up to date while it's transcribed, so someone in the call can glance at
what's been discussed and what's being discussed now (scripts/bench_topics.py tries them on saved transcripts).

Every so often the lines heard since the last time go to the refinement model (refine.ask), numbered, with the
topics so far and the few lines before them for context. It answers with the topics of those lines (at most
three, in JSON), each with what those lines said about it and their numbers: carrying on an earlier topic (by
its number) or a new one. So the list, and what's been said on each topic, only grows (a small model asked to
rewrite it drops things), and each line knows its topic: the Transcripts window colours it to match, and who
brought a topic up, and who else spoke on it, comes from whose lines they are. Lines no topic claims are small
talk, apart from those between two lines of one topic, which are part of it.

Every MERGE seconds, and when it's stopped, the larger model is asked which topics turned out to be one
subject under two titles (it came up again later), then asked again about each pair it gives: asked about the
whole list, it's quick to group things only talked about together. They're merged, keeping the first's colour.
(Not by the smaller model: it lumps different subjects together.)

Tried on two real calls replayed as they were heard: Qwen3.5 9B (GPU) took 0.3–3 s an update and found the
topics of a meeting well; merging joined its two topics on one bug, and nothing else. Told that things tried in
turn are a topic each, it kept one person's four cameras apart, each with what was said of it. (Also tried:
having the model say what's being tried, and telling it next time; it lumped everything after under that.)
4B (CPU) took 8–19 s and was rougher: small talk kept as topics, and different subjects lumped into one."""
import json, re
from . import refine

TICK = 5  # seconds between checks for whether an update is due (and whether the GPU has come free)
FREE_FOR = 15  # seconds the GPU must be free, while the smaller model's on the CPU, to switch to the larger
EVERY = 60  # seconds between updates, once 20 words have been said since the last
MOST = 120  # or after this many seconds, if anything has; or as soon as WORDS have
WORDS = 150
BEFORE = 6  # lines already sorted shown before the new ones, for context
RECENT = 8  # the latest topics are given with their last points; earlier ones by title only (a short prompt)
MERGE = 600  # seconds between asking which topics are the same subject
MERGE_FROM = 4  # topics: fewer aren't worth asking about
COLOURS = ("#7c8cff", "#ff9f43", "#2ed1a2", "#ff6b9a", "#f9d65c", "#b18cff", "#5ec8ff", "#9be15d")
PROMPT = """You keep a live list of the topics of a meeting or call while it happens, for someone in it to glance at.
You get the topics so far, and the transcript of what was said since, as numbered lines (after a few lines from before, for context). The transcript is from speech recognition: it has mis-heard words, cut-off sentences and lines given to the wrong speaker.

Reply with the topics of the numbered lines, in the order they came up: at most 3, fewer is better. Each has:
- topic: the number of the topic in the list whose subject the lines carry on, or 0 for a new subject.
- title: 2 to 6 words (for a topic carried on, its title as it is).
- said: one short sentence on what these lines say about it (opinions, problems, ideas, decisions, things to do), naming who where it matters.
- lines: the numbers of the lines about it, including short replies to them.
A topic is one subject people talk about for a while, such as a tool, a feature, a bug, a version being tried or a plan, not each remark. Lines on the same subject as a topic in the list carry it on (rather than start one much like it); a different subject is a new topic, even if it comes up in the same conversation or activity. When people try several things in turn, each is its own topic, and what they say goes under the one being tried at the time it's said.
Leave out greetings, small talk and shouts while playing. If nothing else was said, reply with no topics. Don't invent anything that wasn't said."""


def schema(lines, known):
    """The answer's shape, for lines new lines and known topics: the model can only give numbers that exist
    (left to count, a small model can number lines on and on)."""
    number = lambda low, high: {"type": "integer", "minimum": low, "maximum": high}
    return {"type": "object", "required": ["topics"], "properties": {"topics": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "required": ["topic", "title", "said", "lines"], "properties": {
            "topic": number(0, known), "title": {"type": "string", "maxLength": 60},
            "said": {"type": "string", "maxLength": 200},
            "lines": {"type": "array", "minItems": 1, "maxItems": lines, "items": number(1, lines)}}}}}}


MERGE_PROMPT = """You keep the list of topics of a meeting or call tidy while it happens. Below are its topics so far, numbered, each with what was said on it. Some may be one subject listed twice under different titles, because it came up again later (e.g. "Boost bug" and "Movement direction bug").

Reply with the groups of topics that are one subject and should be one topic, each with a title for it (2 to 6 words). Only group topics that really are the same subject: different things that came up in the same discussion, or one after another, stay separate. Different options, versions or things tried or compared in turn (e.g. two cameras, two builds, two designs) are different subjects, even though they're the same kind of thing: never group them. If none are the same subject, reply with no groups."""


SAME_PROMPT = """Two topics from the list of topics of a meeting or call, each with what was said on it. Are they one subject that came up twice (so they should be one topic), rather than two different things, however related or close together in the conversation? Different options, versions or things tried in turn are different things."""
SAME_SCHEMA = {"type": "object", "required": ["same"], "properties": {"same": {"type": "boolean"}}}


def merge_schema(known):
    number = {"type": "integer", "minimum": 1, "maximum": known}
    return {"type": "object", "required": ["groups"], "properties": {"groups": {"type": "array", "maxItems": 5, "items": {
        "type": "object", "required": ["topics", "title"], "properties": {
            "topics": {"type": "array", "minItems": 2, "maxItems": known, "items": number},
            "title": {"type": "string", "maxLength": 60}}}}}}


def similar(a, b):
    """Whether two titles are much alike: a topic carried on keeps its title, give or take a word."""
    a, b = (set(re.findall(r"\w+", t.lower())) for t in (a, b))
    return len(a & b) >= max(1, min(len(a), len(b)) // 2)


def colour(i):
    return COLOURS[i % len(COLOURS)]


class Topics:
    """topics: [{"title", "points": [what was said on it, an update at a time], "colour": its colour's number
    (it keeps it when another's merged into it)}] in the order they came up; of: line key -> index into topics;
    now: the index of the topic of the latest lines sorted, or None; small: whether any were found by the
    smaller, less reliable model (on the CPU, when the GPU was busy). A line is (key, who, text); a key is
    anything that identifies it (a stretch's start, a paragraph's place)."""

    def __init__(self, data=None):
        data = data or {}
        self.topics = data.get("topics", [])
        self.of = {k: i for k, i in data.get("of", [])}
        self.now, self.small = data.get("now"), data.get("small", False)

    def data(self):
        return {"topics": self.topics, "of": list(self.of.items()), "now": self.now, "small": self.small}

    def colour(self, i):
        """The colour of topic i."""
        return colour(self.topics[i]["colour"])

    def hue(self, i):
        """The number of topic i's colour (for the window's styles)."""
        return self.topics[i]["colour"] % len(COLOURS)

    def due(self, lines, since):
        """Whether to update: lines are those not sorted yet; since: seconds since the last update."""
        words = sum(len(text.split()) for _, _, text in lines)
        return bool(lines) and (since >= MOST or (since >= EVERY and words >= 20) or words >= WORDS)

    def update(self, lines, before=()):
        """Sort lines (not sorted yet) into topics; before: the lines just before them. Returns whether
        anything changed. Raises OSError or ValueError if the model can't be asked."""
        return bool(lines) and self.apply(lines, self.ask(lines, before))

    def ask(self, lines, before=()):
        """The model's answer for lines (slow: not on the GTK thread)."""
        known = "\n".join(f"{i}. {t['title']}" + (f": {' '.join(t['points'][-2:])}" if i > len(self.topics) - RECENT else "")
                          for i, t in enumerate(self.topics, 1)) or "(none yet)"
        context = "".join(f"(before) {who}: {text}\n" for _, who, text in before[-BEFORE:])
        numbered = "".join(f"{n}. {who}: {text}\n" for n, (_, who, text) in enumerate(lines, 1))
        return refine.ask(PROMPT, f"Topics so far:\n{known}\n\nWhat was said since:\n<transcript>\n{context}{numbered}"
                                  f"</transcript>", schema(len(lines), len(self.topics)), max_tokens=1200)

    def apply(self, lines, reply):
        """Take the model's answer for lines. Returns whether there were any topics in it."""
        try:
            found = json.loads(reply)["topics"]
            assert isinstance(found, list)
        except (ValueError, KeyError, TypeError, AssertionError):
            print("topics: the model's answer isn't topics:", reply[:100], "…", reply[-100:], flush=True)
            return False
        titles = {t["title"].lower(): i for i, t in enumerate(self.topics)}
        claimed = {}
        for t in found:
            if not isinstance(t, dict):
                continue
            title, said = " ".join(str(t.get("title", "")).split()), " ".join(str(t.get("said", "")).split())
            nums = [n for n in t.get("lines") or [] if isinstance(n, int) and 1 <= n <= len(lines)]
            if not title or not nums:
                continue
            number = t.get("topic")
            i = titles.get(title.lower())
            if i is None and isinstance(number, int) and 1 <= number <= len(self.topics) and similar(title, self.topics[number - 1]["title"]):
                i = number - 1
            if i is None:
                i = titles[title.lower()] = len(self.topics)
                self.topics.append({"title": title, "points": [],
                                    "colour": max((t["colour"] for t in self.topics), default=-1) + 1})
            points = self.topics[i]["points"]
            if said and i not in claimed.values() and said not in points[-1:]:  # one point per topic per update
                points.append(said)
            for n in nums:
                claimed.setdefault(n, i)
        for n in range(1, len(lines) + 1):  # a line between two of one topic's is part of it
            if n not in claimed:
                prev = next((claimed[m] for m in range(n - 1, 0, -1) if m in claimed), None)
                nxt = next((claimed[m] for m in range(n + 1, len(lines) + 1) if m in claimed), None)
                if prev is not None and prev == nxt:
                    claimed[n] = prev
        for n, i in claimed.items():
            self.of[lines[n - 1][0]] = i
        if claimed:
            self.now = claimed[max(claimed)]
        return bool(claimed)

    def merge(self):
        """Ask the model which topics are one subject, and merge them. Returns whether any were. Raises
        OSError or ValueError if the model can't be asked."""
        return len(self.topics) >= MERGE_FROM and self.merge_apply(self.merge_ask())

    def merge_ask(self):
        """The model's answer on which topics are one subject (slow: not on the GTK thread). Asked about the
        whole list, it's quick to group things that were only talked about together; so each topic in a
        group it gives is asked about again, beside the group's first, and left out unless it's the same."""
        about = lambda i: f"{self.topics[i]['title']}: {' '.join(self.topics[i]['points'])}"
        listed = "\n".join(f"{i}. {about(i - 1)}" for i in range(1, len(self.topics) + 1))
        try:
            groups = json.loads(refine.ask(MERGE_PROMPT, f"Topics:\n{listed}", merge_schema(len(self.topics)),
                                           max_tokens=500))["groups"]
        except (KeyError, TypeError):
            return '{"groups": []}'
        checked = []
        for g in groups if isinstance(groups, list) else []:
            members = sorted({n for n in g.get("topics") or [] if isinstance(n, int) and 1 <= n <= len(self.topics)})
            same = [n for n in members[1:] if json.loads(refine.ask(
                SAME_PROMPT, f"A. {about(members[0] - 1)}\n\nB. {about(n - 1)}", SAME_SCHEMA, max_tokens=20)).get("same") is True]
            if same:
                checked.append({**g, "topics": [members[0], *same]})
        return json.dumps({"groups": checked})

    def merge_apply(self, reply):
        """Take the model's answer on which topics are one subject: each group becomes its first topic, with
        the others' points after its own, and their lines. Returns whether any were merged."""
        try:
            groups = json.loads(reply)["groups"]
            assert isinstance(groups, list)
        except (ValueError, KeyError, TypeError, AssertionError):
            print("topics: the model's answer isn't groups of topics:", reply[:100], flush=True)
            return False
        into, used = {}, set()  # merged topic -> the one it's merged into
        for g in groups:
            if not isinstance(g, dict):
                continue
            members = sorted({n - 1 for n in g.get("topics") or [] if isinstance(n, int) and 1 <= n <= len(self.topics)} - used)
            if len(members) < 2:
                continue
            keep, title = members[0], " ".join(str(g.get("title", "")).split())
            for i in members[1:]:
                into[i] = keep
                self.topics[keep]["points"] += self.topics[i]["points"]
            if title:
                self.topics[keep]["title"] = title
            used.update(members)
            print("topics: merged", [self.topics[i]["title"] for i in members[1:]], "into", self.topics[keep]["title"], flush=True)
        if not into:
            return False
        moved = {}  # old index -> new
        for i in range(len(self.topics)):
            if i not in into:
                moved[i] = len(moved)
        renumber = lambda i: moved[into.get(i, i)]
        self.of = {k: renumber(i) for k, i in self.of.items() if i < len(self.topics)}
        self.now = renumber(self.now) if self.now is not None and self.now < len(self.topics) else None
        self.topics = [t for i, t in enumerate(self.topics) if i not in into]
        return True

    def people(self, lines):
        """For each topic, [who started it, then who else spoke on it], from lines (key, who, text) in order."""
        out = [[] for _ in self.topics]
        for key, who, _ in lines:
            i = self.of.get(key)
            if i is not None and i < len(out) and who not in out[i]:
                out[i].append(who)
        return out
