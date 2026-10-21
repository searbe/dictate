"""Transcribe mode: what's said through this computer's speakers and into its microphone ("Me"), written
into a transcript as it's heard. Each stretch of speech is transcribed by stt.Live as soon as there's a
pause, so the transcript grows while people talk; meanwhile, previews() shows what's being said so far,
updated every second (shown only: it isn't saved). Voices through the speakers are told apart by voices.py
("Speaker 1", "Speaker 2", …, or their names once named; "Them" without the voice model), and a stretch is
split between voices where the voice changes in it, between words, by when each word was said.

Left out: your dictations (the microphone is muted while you hold Ctrl+Win), Dictate playing a recording
back, anything said while paused, and the speakers' sound picked up again by the microphone (without
headphones): PipeWire's echo canceller takes some of it out of the microphone (osio.Recorder's echo_cancel),
echo.py tells what's left from you speaking, and the same words at the same time as Them are an echo too.

Saved as Markdown in data/transcripts/, rewritten after every new stretch, with an Ogg Opus recording per
source beside it (about 12 MB an hour each, kept as long as dictation recordings are). saved() reads them
back for the Transcripts window. While remembering voices is on, each transcript's voiceprints are saved
beside it too, so a voice can be named (and remembered) after the call."""
import json, re, threading, time
from datetime import datetime, timedelta
import numpy as np
from gi.repository import GLib
from . import DATA, echo, osio, stt, voices

FOLDER = DATA / "transcripts"
SOURCES = (("me", False), ("them", True))  # who, recorded from the speakers
NAMES = {"me": "Me", "them": "Them"}
JOIN = 10  # seconds: a stretch this soon after the same person's last one continues their paragraph
PAUSE = 1.2  # seconds of silence that end a stretch: transcribed whole, more around each word makes it clearer
PIECE = 0.4  # but who said it is worked out between its shorter pauses, where people usually take turns
ECHO = 0.6  # share of a stretch's words also heard through the speakers at the same time, for it to be an echo
STAMP = "%Y-%m-%d %H.%M.%S"  # a transcript's file name: when it started
LASTED = re.compile(r"^Lasted (.+), until \d\d:\d\d\.$", re.M)
PARAGRAPH = re.compile(r"^\*\*(\d\d:\d\d:\d\d) (.+?):\*\* (.*)$", re.M)


def length(seconds):
    """e.g. "under a minute", "27 min", "1 h 05 min"."""
    minutes = round(seconds / 60)
    if seconds < 60:
        return "under a minute"
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def recordings(path):
    """The recordings saved beside the transcript at path."""
    return [f for f in path.parent.glob(f"{path.stem} *") if f.suffix in (".ogg", ".wav")]


def voiceprints(path):
    """Where the voiceprints of the transcript at path are kept (only while remembering voices is on)."""
    return path.with_name(f"{path.stem} voices.json")


def clean_name(name):
    """A name as it can appear in a transcript (no Markdown or line breaks), or "" for none."""
    return re.sub(r"[*:\n\r]", "", name or "").strip()[:40]


def labels(paragraphs):
    """The names of the voices in a transcript, in the order they first speak, apart from "Me"."""
    return list(dict.fromkeys(who for _, who, _ in paragraphs if who != NAMES["me"]))


def rename(path, label, name):
    """Rename a voice in a saved transcript (and remember it, if its voiceprint was kept)."""
    name = clean_name(name)
    if not name or name == label:
        return
    text = re.sub(rf"^(\*\*\d\d:\d\d:\d\d ){re.escape(label)}(:\*\*)", lambda m: m[1] + name + m[2], path.read_text(), flags=re.M)
    path.write_text(text)
    try:
        prints = json.loads(voiceprints(path).read_text())
    except (OSError, ValueError):
        return
    if label in prints:
        vector = np.asarray(prints.pop(label), np.float32)
        if name in prints:  # two voices with one name are one voice
            vector = vector + np.asarray(prints[name], np.float32)
        prints[name] = (vector / np.linalg.norm(vector)).tolist()
        voiceprints(path).write_text(json.dumps(prints))
        voices.remember(name, prints[name])


def read(path):
    """A saved transcript: {"path", "started", "length", "paragraphs": [(clock, who, text)]}, or None."""
    try:
        started, text = datetime.strptime(path.stem, STAMP), path.read_text()
    except (ValueError, OSError):
        return None
    paragraphs = PARAGRAPH.findall(text)
    lasted = LASTED.search(text)
    if lasted:
        took = lasted[1]
    else:  # saved before transcripts said how long they lasted: the longest recording, else the last paragraph
        import soundfile
        seconds = 0.0
        for rec in recordings(path):
            try:
                seconds = max(seconds, soundfile.info(str(rec)).duration)
            except RuntimeError:
                pass
        if not seconds and paragraphs:
            last = datetime.combine(started.date(), datetime.strptime(paragraphs[-1][0], "%H:%M:%S").time())
            seconds = (last - started).total_seconds() % 86400
        took = length(seconds)
    return {"path": path, "started": started, "length": took, "paragraphs": paragraphs}


def saved():
    """Every saved transcript, newest first."""
    return [t for t in map(read, sorted(FOLDER.glob("*.md"), reverse=True)) if t]


def delete(path):
    """Delete a saved transcript, its recordings and voiceprints."""
    for f in [path, *recordings(path), voiceprints(path)]:
        f.unlink(missing_ok=True)


def forget_voiceprints():
    """Delete every transcript's voiceprints (remembering voices was turned off)."""
    for f in FOLDER.glob("* voices.json"):
        f.unlink(missing_ok=True)


def parts_of(samples, words, narrow):
    """[(start, end)] in seconds: the parts of a stretch said by one voice each, cut at its short pauses and,
    within those, where the voice changes (voices.turns), between words. Each starts where its audio does."""
    out = []
    for at, piece in stt.stretches(samples, PIECE) or [(0, samples)]:
        turns = [(at / stt.RATE + a, at / stt.RATE + b) for a, b in voices.turns(piece, narrow)] if narrow is not None \
            else [(at / stt.RATE, (at + len(piece)) / stt.RATE)]
        out += between_words(turns, words) if words else turns
    return out


def said_in(parts, words, text):
    """The words of each part: from its start to the next one's (so a word in a pause between them is kept)."""
    if len(parts) == 1:
        return [text]
    starts = [a for a, _ in parts[1:]]
    return ["".join(w for t, w in words if (i == 0 or t >= parts[i][0]) and (i == len(parts) - 1 or t < starts[i])).strip()
            for i in range(len(parts))]


def between_words(parts, words, near=0.6):
    """parts, with each change of voice moved to the longest gap between words within near seconds of it
    (people take turns between words, and voiceprints only find the change to within a few tenths)."""
    starts = [t for t, _ in words]
    edges = [parts[0][0]]
    for _, cut in parts[:-1]:
        gaps = [(starts[i] - starts[i - 1], starts[i]) for i in range(1, len(starts)) if abs(starts[i] - cut) <= near]
        edges.append(max(gaps)[1] - 0.01 if gaps else cut)  # just before the word that starts the new turn
    return list(zip(edges, [*edges[1:], parts[-1][1]]))


class Session:
    """A transcript being recorded. on_change() runs on the GTK thread whenever the transcript changes."""

    def __init__(self, on_change=lambda: None):
        FOLDER.mkdir(parents=True, exist_ok=True)
        self.started, self.t0, self.on_change = datetime.now().replace(microsecond=0), time.monotonic(), on_change
        while (FOLDER / f"{self.started:{STAMP}}.md").exists():  # another started within the same second
            self.started += timedelta(seconds=1)
        stamp = f"{self.started:{STAMP}}"
        self.path = FOLDER / f"{stamp}.md"
        self.heard = []  # (who, start, end, text, voice id or None), in seconds since the start
        self.voices = voices.Voices(voices.remembered()) if voices.available() else None
        self.band = (0.0, 0.0)  # the speakers' power above 4 kHz, and in all: is it a phone line?
        self.previewing = {}  # who: (start, text) of what they're saying, before it's transcribed whole
        self.echo = echo.Echo()  # what the speakers played, to tell the microphone's echoes of it
        self.muted = {who: [] for who, _ in SOURCES}  # [start, end] (end None: still muted)
        self.paused = self.stopped = False
        self.recorders, self.lives, self.recordings = [], [], []
        for who, speakers in SOURCES:
            path = str(FOLDER / f"{stamp} {who}.ogg")
            live = stt.Live(pause=PAUSE, on_text=lambda *heard, who=who: self.hear(who, *heard),
                            on_preview=lambda *so_far, who=who: self.preview(who, *so_far))
            rec = osio.Recorder()
            rec.start(path, speakers=speakers, echo_cancel=not speakers,
                      on_audio=(lambda chunk, push=live.push: (self.echo.played(chunk), push(chunk))) if speakers else live.push)
            self.recorders.append(rec)
            self.recordings.append(path)
            self.lives.append(live)
        self.save()

    def now(self):
        return time.monotonic() - self.t0

    def hear(self, who, start, end, text, samples=None, words=None):
        """A stretch of speech has been transcribed (on Live's thread, where it's split between voices too:
        voiceprints are slow-ish, the GTK thread mustn't wait for them). What the microphone heard is cut at
        its short pauses too, so that the speakers' echo in it can be left out, and you kept."""
        heard = [((who, start, end, text), None)]
        real = isinstance(samples, np.ndarray)  # (not a test's stand-in)
        if who == "me" and real:
            parts = parts_of(samples, words, None)
            heard = [((who, start + a, start + b, said), None) for (a, b), said in zip(parts, said_in(parts, words, text))
                     if said and not self.echo.echo(start + a, samples[int(a * stt.RATE):int(b * stt.RATE)])]
        elif who == "them" and self.voices and real:
            high, total = voices.band(samples)
            self.band = (self.band[0] + high, self.band[1] + total)
            narrow = voices.narrowband(power=self.band)
            parts = parts_of(samples, words, narrow)
            heard = [((who, start + a, start + b, said), (voices.voiceprint(samples[int(a * stt.RATE):int(b * stt.RATE)]), b - a, narrow))
                     for (a, b), said in zip(parts, said_in(parts, words, text)) if said]
        elif who == "them" and self.voices:
            heard = [((who, start, end, text), (voices.voiceprint(samples), end - start, False))]
        GLib.idle_add(self._add, who, heard)

    def _add(self, who, heard):
        for stretch, voice in heard:
            self.heard.append((*stretch, self.voices.voice(*voice) if voice else None))
        self.previewing.pop(who, None)  # now transcribed whole
        self.save()
        self.on_change()

    def preview(self, who, start, text, samples=None, at=None):
        """What who is saying so far (on Live's thread); samples: the end of it, from at seconds."""
        echoed = who == "me" and samples is not None and self.echo.echo(at, samples)
        GLib.idle_add(self._preview, who, start, None if echoed else text)

    def _preview(self, who, start, text):
        if not self.stopped:
            if text:
                self.previewing[who] = (start, text)
            else:  # the speakers, not you
                self.previewing.pop(who, None)
            self.on_change()

    def previews(self):
        """[(clock, who's name, text)]: what's being said, not yet transcribed whole (not when it would be
        left out of the transcript: muted, or the microphone's echo of the speakers)."""
        out, them = [], self.previewing.get("them")
        for who, (start, text) in sorted(self.previewing.items(), key=lambda p: p[1][0]):
            if self.left_out(who, start, self.now(), text, [("them", them[0], self.now(), them[1], None)] if them else []):
                continue
            name = "…" if who == "them" and self.voices else NAMES[who]  # whose voice it is comes once it's whole
            out.append((f"{self.started + timedelta(seconds=start):%H:%M:%S}", name, text))
        return out

    def rename(self, label, name):
        """Name the voice shown as label (naming two voices the same makes them one), and remember it if
        remembering voices is on."""
        name = clean_name(name)
        vid = self.voices.find(label) if self.voices else None
        if not name or vid is None:
            return
        vid = self.voices.rename(vid, name)
        voices.remember(name, self.voices.vector(vid).tolist())
        self.save()
        self.on_change()

    def mute(self, who, on):
        """Leave out what who says from now (on) until mute(who, False)."""
        spans = self.muted[who]
        if on and not (spans and spans[-1][1] is None):
            spans.append([self.now(), None])
        elif not on and spans and spans[-1][1] is None:
            spans[-1][1] = self.now()

    def pause(self, on):
        self.paused = on
        for who in self.muted:
            self.mute(who, on)
        self.on_change()

    def stop(self, on_done):
        """Stop recording, transcribe what's left, save, then on_done() on the GTK thread."""
        self.stopped = True
        def finish():
            for rec in self.recorders:
                rec.stop()
            for live in self.lives:
                live.finish()  # its last stretches arrive through hear(), before on_done
            GLib.idle_add(lambda: (self.save(), self.on_change(), on_done()) and False)
        threading.Thread(target=finish, daemon=True).start()

    # --- what's in the transcript ---
    def kept(self):
        """What was heard, minus what was muted and the microphone's echoes of the speakers, in time order."""
        them = [h for h in self.heard if h[0] == "them"]
        return sorted((h for h in self.heard if not self.left_out(*h[:4], them)), key=lambda h: h[1])

    def left_out(self, who, start, end, text, them):
        """Whether what who said from start to end is left out: muted, or (me) an echo of them saying it."""
        if any(a < end and (b is None or b > start) for a, b in self.muted[who]):
            return True
        words = set(re.findall(r"\w+", text.lower()))
        if who != "me" or not words:
            return False
        heard = set()  # what they said at the same moment, give or take a second (a stretch here can span
        for _, s, e, t, _ in them:  # several of theirs: the microphone and the speakers pause at different times)
            if s < end + 1 and e > start - 1:
                heard |= set(re.findall(r"\w+", t.lower()))
        return len(words & heard) >= ECHO * len(words)

    def name(self, who, vid):
        return self.voices.label(vid) if vid is not None else NAMES[who]

    def paragraphs(self):
        """[(clock time, who's name, text)]: each person's consecutive stretches run together."""
        out, last = [], None
        for who, start, end, text, vid in self.kept():
            name = self.name(who, vid)
            if last and last[0] == name and start - last[1] < JOIN:
                out[-1][2] += " " + text
            else:
                clock = f"{self.started + timedelta(seconds=start):%H:%M:%S}"
                out.append([clock, name, text])
            last = (name, end)
        return [tuple(p) for p in out]

    def markdown(self):
        head = f"# Transcript, {self.started:%A %-d %B %Y, %H:%M}\n\nLasted {length(self.now())}, until {datetime.now():%H:%M}.\n"
        return head + "".join(f"\n**{clock} {who}:** {text}\n" for clock, who, text in self.paragraphs())

    def save(self):
        self.path.write_text(self.markdown())
        if self.voices and voices.remembering():  # so its voices can be named, and remembered, later
            voiceprints(self.path).write_text(json.dumps(self.voices.labelled()))
