"""Transcribe mode: what's said through this computer's speakers and into its microphone ("Me"), written
into a transcript as it's heard. Each stretch of speech is transcribed by stt.Live as soon as there's a
pause, so the transcript grows while people talk; meanwhile, previews() shows what's being said so far,
updated every second (shown only: it isn't saved). Voices through the speakers are told apart by voices.py
("Speaker 1", "Speaker 2", …, or their names once named; "Them" without the voice model), and a stretch is
split between voices where the voice changes in it, between words, by when each word was said.

Left out: your dictations (the microphone is muted while you hold Ctrl+Win), Dictate playing a recording
back, anything said while paused (the recordings get silence instead: see hush), and the speakers' sound picked
up again by the microphone (without headphones): PipeWire's echo canceller takes some of it out of the
microphone (osio.Recorder's echo_cancel), echo.py tells what's left from you speaking, and the same words at the
same time as Them are an echo too.

Saved as Markdown in data/transcripts/, rewritten after every new stretch, with an Ogg Opus recording per
source beside it (about 12 MB an hour each, kept as long as dictation recordings are). saved() reads them
back for the Transcripts window. While remembering voices is on, each transcript's voiceprints are saved
beside it too, so a voice can be named (and remembered) after the call.

Its topics (topics.py) are kept up to date as it's heard, listed at the top of the transcript, and saved
beside it with which paragraph is on which, by their place in it (a paragraph ends where the topic changes). So
is a live summary (summary.py), with a final pass when it's stopped; above the topics."""
import json
import logging
import queue
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from gi.repository import GLib

from . import DATA, echo, llm, osio, store, stt, summary, topics, voices

log = logging.getLogger(__name__)

FOLDER = DATA / "transcripts"
SOURCES = (("me", False), ("them", True))  # who, recorded from the speakers
NAMES = {"me": "Me", "them": "Them"}
JOIN = 10  # seconds: a stretch this soon after the same person's last one continues their paragraph
PAUSE = 1.2  # seconds of silence that end a stretch: transcribed whole, more around each word makes it clearer
PIECE = 0.4  # but who said it is worked out between its shorter pauses, where people usually take turns
ECHO = 0.6  # share of a stretch's words also heard through the speakers at the same time, for it to be an echo
STAMP = "%Y-%m-%d %H.%M.%S"  # a transcript's file name: when it started
AHEAD = 10.0  # seconds of the speakers heard after a stretch before it's split between voices (the segmenter
WINDOW = 60.0  # tells a change better hearing what follows), and how much before it the segmenter hears too
SOUND = 0.01  # loudness (RMS, full scale 1) of a tenth of a second heard while paused that counts as a sound
RECENT = 300.0  # seconds of the speakers kept for that: longer than a stretch can be, plus both of those
PENDING, UNKNOWN = "pending", -1  # a stretch from the speakers still to be split between voices; whose it is so far
LASTED = re.compile(r"^Lasted (.+), until \d\d:\d\d\.$", re.M)
PARAGRAPH = re.compile(r"^\*\*(\d\d:\d\d:\d\d) (.+?):\*\* (.*)$", re.M)


def clock(seconds):
    """How long a call has been going, as a timer shows it: e.g. "4:07", "1:02:09"."""
    seconds = int(seconds)
    hours, minutes, seconds = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def length(seconds):
    """e.g. "under a minute", "27 min", "1 h 05 min"."""
    minutes = round(seconds / 60)
    if seconds < 60:
        return "under a minute"
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def recordings(path):
    """The recordings saved beside the transcript at path."""
    return [f for f in path.parent.glob(f"{path.stem} *") if f.suffix in (".ogg", ".wav")]


def summary_file(path):
    """Where the summary of the transcript at path is kept."""
    return path.with_name(f"{path.stem} summary.json")


def read_summary(path):
    """The summary of the saved transcript at path, or None."""
    try:
        data = json.loads(summary_file(path).read_text())
        return summary.Summary(data["text"], data.get("final", False), data.get("slices", ()), data.get("waiting"))
    except (OSError, ValueError, KeyError):
        return None


def topics_file(path):
    """Where the topics of the transcript at path are kept, with which paragraph is on which."""
    return path.with_name(f"{path.stem} topics.json")


def read_topics(path):
    """The topics of the saved transcript at path (its paragraphs keyed by their place in it), or None."""
    try:
        return topics.Topics(json.loads(topics_file(path).read_text()))
    except (OSError, ValueError):
        return None


def numbered(paragraphs):
    """[(place, who, text)]: a saved transcript's paragraphs as lines for topics.py."""
    return [(i, who, text) for i, (_, who, text) in enumerate(paragraphs)]


def topics_markdown(found, people):
    """The topics as Markdown, to go above the transcript ("" if there are none)."""
    if not found.topics:
        return ""
    lines = "".join(f"- **{t['title']}**" + (f" ({', '.join(who)})" if who else "") + f": {' '.join(t['points'])}\n"
                    for t, who in zip(found.topics, people))
    return f"\n## Topics\n\n{lines}"


MIXES = 2  # mixed calls kept, to play from again without decoding them again (a WAV is about 115 MB an hour)
_mixing = threading.Lock()


def mixes():
    """Where mixdown keeps the mixed calls."""
    return Path(GLib.get_user_cache_dir()) / "dictate" / "mixes"


def forget_mixes():
    """Delete the mixed copies of calls whose recordings have gone, or some of them (the transcript deleted, or its
    recordings past "keep recordings"): a copy is never kept longer than the recordings it was made from. Each is
    named by its transcript and how many recordings it was made from."""
    for mix in mixes().glob("*.wav"):  # (one being made is checked once it's made)
        stem, _, n = mix.stem.rpartition(" ")
        if not n.isdigit() or len(recordings(FOLDER / f"{stem}.md")) != int(n):
            mix.unlink(missing_ok=True)


def mixdown(path):
    """The transcript's recordings (this computer's audio and the microphone) mixed into one WAV, to play back:
    its path, or None if they're gone (they're kept for "keep recordings"). Made once and kept (the latest MIXES
    of them), unless the recordings change; deleted with them (forget_mixes)."""
    import soundfile
    recs = recordings(path)
    folder = mixes()
    out = folder / f"{path.stem} {len(recs)}.wav"
    with _mixing:  # (two at once would make the same one twice)
        if out.exists() and recs and out.stat().st_mtime >= max(r.stat().st_mtime for r in recs):
            return out
        tracks, rate = [], stt.RATE
        for rec in recs:
            try:
                data, rate = soundfile.read(str(rec), dtype="float32")
            except RuntimeError:
                continue
            tracks.append(data.mean(1) if data.ndim > 1 else data)
        if not tracks:
            return None
        mix = np.zeros(max(map(len, tracks)), np.float32)
        for track in tracks:
            mix[:len(track)] += track
        folder.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part")
        soundfile.write(str(part), np.clip(mix, -1, 1), rate, subtype="PCM_16", format="WAV")
        part.replace(out)
        if len(recordings(path)) != len(recs):  # deleted while it was being made
            out.unlink(missing_ok=True)
            return None
        for old in sorted(folder.glob("*.wav"), key=lambda f: f.stat().st_mtime)[:-MIXES]:
            old.unlink(missing_ok=True)
        return out


def cut(path, start, end, out):
    """Write the transcript's call (mixdown) from start to end seconds (end None: to its end) to the WAV out.
    False if its recordings are gone."""
    import soundfile
    mix = mixdown(path)
    if not mix:
        return False
    with soundfile.SoundFile(str(mix)) as f:
        f.seek(min(int(start * f.samplerate), f.frames))
        samples = f.read(-1 if end is None else max(0, int((end - start) * f.samplerate)), dtype="int16")
        out.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(out), samples, f.samplerate, subtype="PCM_16")
    return True


def offsets(item):
    """Where each of a saved transcript's paragraphs starts, in seconds into its call (by their clocks)."""
    started = item["started"]
    first = started.hour * 3600 + started.minute * 60 + started.second
    out = []
    for clock, _, _ in item["paragraphs"]:
        h, m, s = map(int, clock.split(":"))
        out.append((h * 3600 + m * 60 + s - first) % 86400)
    return out


def waiting():
    """[(since, path)]: the saved transcripts whose final pass is still to do (Dictate quit first), oldest first;
    since: when the call stopped (time.time)."""
    found = []
    for f in FOLDER.glob("* summary.json"):
        path = f.with_name(f.name.removesuffix(" summary.json") + ".md")
        s = read_summary(path)
        if s and s.waiting and path.exists():
            found.append((s.waiting, path))
    return sorted(found)


def final_summary(path):
    """Write a saved transcript's final summary (slow: not on the GTK thread), from its paragraphs, as a call's
    final pass does: a long one from its slices' summaries (those saved, and the rest made now), merged. Its
    topics are left as they are. Replaces the summary (and the Summary section of its Markdown). Returns whether
    there was one (an error from the model is raised)."""
    item, before = read(path), read_summary(path) or summary.Summary()
    if not item or not item["paragraphs"]:
        return False
    # (a saved transcript has paragraphs, not stretches: one line each, by when they started, which is close
    # enough to the stretches' times the saved slices end at)
    lines = [(at + i * 1e-6, who, text) for i, (at, (_, who, text))
             in enumerate(zip(offsets(item), item["paragraphs"]))]
    s = summary.Summary(slices=before.slices)
    reply, slices = s.ask_final(lines, read_topics(path) or topics.Topics())
    if not s.take(reply, lines, final=True, slices=slices):
        raise ValueError(f"the model's answer isn't a summary: {reply[:100]}")
    if not path.exists():  # deleted meanwhile
        return False
    store.write_json(summary_file(path), s.data())
    section = re.compile(r"\n## Summary\n.*?(?=\n## )", re.S)
    text, new = path.read_text(), summary.markdown(s.text).rstrip("\n")
    if section.search(text):
        text = section.sub(lambda _: new, text, count=1)
    else:  # (none yet: above the rest, after the heading and how long it lasted)
        head, _, rest = text.partition("\n## ")
        text = f"{head.rstrip()}\n{new}\n\n## {rest}" if rest else f"{text.rstrip()}\n{new}\n"
    store.write_text(path, text)
    return True


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
    text = re.sub(rf"^(\*\*\d\d:\d\d:\d\d ){re.escape(label)}(:\*\*)", lambda m: m[1] + name + m[2], path.read_text(),
                  flags=re.M)
    store.write_text(path, text)
    prints = store.read_json(voiceprints(path))
    if prints and label in prints:
        vector = np.asarray(prints.pop(label), np.float32)
        if name in prints:  # two voices with one name are one voice
            vector = vector + np.asarray(prints[name], np.float32)
        prints[name] = (vector / np.linalg.norm(vector)).tolist()
        store.write_json(voiceprints(path), prints)
        voices.remember(name, prints[name])


def read(path):
    """A saved transcript: {"path", "started", "length", "paragraphs": [(clock, who, text)], "changed"}, or None."""
    try:
        started, text, changed = datetime.strptime(path.stem, STAMP), path.read_text(), path.stat().st_mtime
    except (ValueError, OSError):
        return None
    lasted = LASTED.search(text)
    return {"path": path, "started": started, "length": lasted[1] if lasted else "",
            "paragraphs": PARAGRAPH.findall(text), "changed": changed}


def saved():
    """Every saved transcript, newest first."""
    return [t for t in map(read, sorted(FOLDER.glob("*.md"), reverse=True)) if t]


def delete(path):
    """Delete a saved transcript, its recordings (and the copy mixed from them to play back), voiceprints, topics
    and summary."""
    for f in [path, *recordings(path), voiceprints(path), topics_file(path), summary_file(path)]:
        f.unlink(missing_ok=True)
    forget_mixes()


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


def voiced_parts(samples, words, narrow, known):
    """[(start, end, voiceprint, voice or None)]: the parts of a stretch said by one voice each (as parts_of), with
    their voiceprints. Once two voices or more are known ({voice: unit vector}: Voices.told_apart), a piece
    between short pauses that has words is told apart word by word (voices.by_word), giving each part the voice
    it is; else, and before then, by where the voice changes (voices.turns), leaving which voice to Voices."""
    if len(known) < 2 or not words:
        parts = parts_of(samples, words, narrow)
        return [(a, b, voices.voiceprint(samples[int(a * stt.RATE):int(b * stt.RATE)]), None) for a, b in parts]
    out = []
    for at, piece in stt.stretches(samples, PIECE) or [(0, samples)]:
        a, b = at / stt.RATE, (at + len(piece)) / stt.RATE
        inside = [(t - a, w) for t, w in words if a - 0.1 <= t < b]  # (a word can start just before its audio)
        out += [(a + s, a + e, v, who) for s, e, v, who in voices.by_word(piece, inside, known, narrow)]
    return out


def said_in(parts, words, text):
    """The words of each part: from its start to the next one's (so a word in a pause between them is kept)."""
    if len(parts) == 1:
        return [text]
    starts = [a for a, _ in parts[1:]]
    return ["".join(w for t, w in words
                    if (i == 0 or t >= parts[i][0]) and (i == len(parts) - 1 or t < starts[i])).strip()
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


class Recent:
    """The last few minutes of what the speakers played, as recorded (16-bit chunks), for the segmenter."""

    def __init__(self, seconds):
        self.most, self.chunks, self.kept, self.total = int(seconds * stt.RATE), deque(), 0, 0
        self.lock = threading.Lock()

    def add(self, chunk):
        samples = np.frombuffer(chunk, np.int16)
        with self.lock:
            self.chunks.append(samples)
            self.kept += len(samples)
            self.total += len(samples)
            while self.kept - len(self.chunks[0]) >= self.most:
                self.kept -= len(self.chunks.popleft())

    def end(self):
        """Seconds recorded so far."""
        return self.total / stt.RATE

    def audio(self, a, b):
        """(start, samples): what was played from a to b seconds, as float32 (from start, if a is no longer kept)."""
        with self.lock:
            first = self.total - self.kept
            whole = np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.int16)
        i, j = max(0, int(a * stt.RATE) - first), max(0, int(b * stt.RATE) - first)
        return (first + i) / stt.RATE, whole[i:j].astype(np.float32) / 32768


class Session:
    """A transcript being recorded. on_change() runs on the GTK thread whenever the transcript changes; on_sound()
    whenever something is heard while it's paused."""

    def __init__(self, on_change=lambda: None, mic=None):
        self.on_sound = lambda: None
        FOLDER.mkdir(parents=True, exist_ok=True)
        self.started, self.t0, self.on_change = datetime.now().replace(microsecond=0), time.monotonic(), on_change
        while (FOLDER / f"{self.started:{STAMP}}.md").exists():  # another started within the same second
            self.started += timedelta(seconds=1)
        stamp = f"{self.started:{STAMP}}"
        self.path = FOLDER / f"{stamp}.md"
        self.heard = []  # (who, start, end, text, voice id or None), in seconds since the start
        self.voices = voices.Voices(voices.remembered()) if voices.available() else None
        self.known = {}  # the voices heard long enough to tell words apart by, as of the latest stretch
        self.band = (0.0, 0.0)  # the speakers' power above 4 kHz, and in all: is it a phone line?
        self.previewing = {}  # who: (start, text) of what they're saying, before it's transcribed whole
        self.echo = echo.Echo()  # what the speakers played, to tell the microphone's echoes of it
        self.muted = {who: [] for who, _ in SOURCES}  # [start, end] (end None: still muted)
        self.paused = self.stopped = self.deleted = False
        self.resumed = 0.0  # when it was last resumed
        self.topics, self.asked, self.asking, self.last_topics = topics.Topics(), set(), False, self.now()
        self.last_merge = self.now()
        self.summary, self.last_summary = summary.Summary(), self.now()
        self.gpu_free_for = 0.0  # seconds the GPU has been free while the smaller model is loaded on the CPU
        self.start_settling()
        llm.server.keep(True)  # the model, loaded for the whole call (from now, so it's ready for the first topics)
        llm.server.warm(hold=False)
        GLib.timeout_add(int(topics.TICK * 1000), self.tick)
        self.recorders, self.lives, self.recordings = [], [], []
        for who, speakers in SOURCES:
            path = str(FOLDER / f"{stamp} {who}.ogg")
            live = stt.Live(pause=PAUSE, on_text=lambda *heard, who=who: self.hear(who, *heard),
                            on_preview=lambda *so_far, who=who: self.preview(who, *so_far))
            rec = osio.Recorder()
            rec.start(path, speakers=speakers, echo_cancel=not speakers, mic=mic, hush=self.hush,
                      on_audio=(lambda chunk, push=live.push: (self.echo.played(chunk), self.recent.add(chunk),
                                                               push(chunk))) if speakers else live.push)
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
            heard = [((who, start + a, start + b, said), None)
                     for (a, b), said in zip(parts, said_in(parts, words, text))
                     if said and not self.echo.echo(start + a, samples[int(a * stt.RATE):int(b * stt.RATE)])]
        elif who == "them" and self.voices and real and voices.segmenter_available():
            high, total = voices.band(samples)
            self.band = (self.band[0] + high, self.band[1] + total)
            heard = [((who, start, end, text), PENDING)]  # whose it is, provisionally: split once more is heard
            self.settling.put((start, end, text, samples, words, voices.narrowband(power=self.band)))
        elif who == "them" and self.voices and real:  # (no segmentation model: told apart by voiceprints alone)
            high, total = voices.band(samples)
            self.band = (self.band[0] + high, self.band[1] + total)
            narrow = voices.narrowband(power=self.band)
            found = voiced_parts(samples, words, narrow, self.known)  # (self.known: the GTK thread's latest, see _add)
            parts = [(a, b) for a, b, _, _ in found]
            heard = [((who, start + a, start + b, said), (v, b - a, narrow, w))
                     for (_, _, v, w), (a, b), said in zip(found, parts, said_in(parts, words, text)) if said]
        elif who == "them" and self.voices:
            heard = [((who, start, end, text), (voices.voiceprint(samples), end - start, False))]
        GLib.idle_add(self._add, who, heard)

    def _add(self, who, heard):
        for stretch, voice in heard:
            if voice == PENDING:  # until it's settled: the voice heard last, as most stretches carry on from it
                self.pending.add(stretch[1])
                vid = len(self.voices.of) - 1 if self.voices.of else UNKNOWN
            else:
                vid = self.voices.voice(*voice) if voice else None
            self.heard.append((*stretch, vid))
        if self.voices:
            self.known = self.voices.told_apart()  # (for hear(), on Live's thread: a new dict, never changed)
        self.previewing.pop(who, None)  # now transcribed whole
        self.save()
        self.on_change()

    # --- who said what, once more has been heard ---
    def start_settling(self):
        self.recent = Recent(RECENT)  # what the speakers played lately, for the segmenter
        self.settling = queue.Queue()  # stretches from the speakers to split between voices (hear(), _settle())
        self.pending = set()  # the starts of those in the transcript, not split yet
        self.settled = threading.Event()  # set once the last one has been (after stop())
        threading.Thread(target=self._settle, daemon=True).start()

    def _settle(self):
        """On its own thread: split each stretch from the speakers between voices where the segmenter hears the
        voice change, once AHEAD seconds more have been heard (or recording has stopped), then hand the parts
        to Voices (on the GTK thread)."""
        while (item := self.settling.get()) is not None:
            start, end, text, samples, words, narrow = item
            while not self.stopped and self.recent.end() < end + AHEAD:
                time.sleep(0.2)
            try:
                heard = self._split(start, end, text, samples, words, narrow)
            except Exception:  # never lose what was said: keep it whole
                log.exception("couldn't split a stretch between voices")
                heard = [(("them", start, end, text), (voices.voiceprint(samples), end - start, narrow, None))]
            GLib.idle_add(self._settled, start, heard)
        self.settled.set()

    def _split(self, start, end, text, samples, words, narrow):
        """The parts of a stretch said by one voice each: cut where the segmenter, hearing from up to WINDOW
        seconds before it to AHEAD after, hears the voice change; each change moved to the gap between words."""
        at, window = self.recent.audio(min(start, end - WINDOW), end + AHEAD)
        length = len(samples) / stt.RATE
        cuts = [c + at - start for c in voices.changes(window)] if len(window) else []
        edges = [0.0, *(c for c in cuts if 0.3 < c < length - 0.3), length]
        parts = list(zip(edges, edges[1:]))
        if words and len(parts) > 1:
            parts = between_words(parts, words)
        parts = [(a, b) for a, b in parts if b - a >= 0.05]
        return [(("them", start + a, start + b, said),
                 (voices.voiceprint(samples[int(a * stt.RATE):int(b * stt.RATE)]), b - a, narrow, None))
                for (a, b), said in zip(parts, said_in(parts, words, text)) if said]

    def _settled(self, start, heard):
        """A stretch from the speakers has been split between voices: its parts replace it."""
        self.heard = [h for h in self.heard if not (h[0] == "them" and h[1] == start)]
        self.pending.discard(start)
        self._add("them", heard)
        return False

    def finish_settling(self):
        """Split what's still to be split now (recording has stopped), and wait until it's been handed over."""
        self.settling.put(None)
        self.settled.wait()

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
            if self.left_out(who, start, self.now(), text,
                             [("them", them[0], self.now(), them[1], None)] if them else []):
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

    def hush(self, chunk):
        """While paused (on the recorder's thread): True, so the recordings get silence instead of what's heard,
        and nothing is transcribed (the recordings stay as long as the transcript's clock). What's heard is still
        listened to, and on_sound() runs if it's louder than SOUND."""
        if not self.paused:
            return False
        samples = np.frombuffer(chunk, np.int16).astype(np.float32) / 32768
        if len(samples) and float(np.sqrt(np.mean(samples ** 2))) > SOUND:
            GLib.idle_add(lambda: self.on_sound() and False)
        return True

    def pause(self, on):
        if self.paused and not on:
            self.resumed = self.now()
        self.paused = on
        for who in self.muted:
            self.mute(who, on)
        self.on_change()

    def stop(self, on_done):
        """Stop recording, transcribe what's left and save it, then on_done(kept) on the GTK thread. If nothing was
        heard, nothing is kept: the transcript and its recordings are deleted. Otherwise its final pass is still to
        do (final_pass): it's saved as waiting for it, so it's done even if Dictate quits first."""
        self.stopped = True
        def finish():
            for rec in self.recorders:
                rec.stop()
            for live in self.lives:
                live.finish()  # its last stretches arrive through hear(), before on_done
            self.finish_settling()
            GLib.idle_add(saved)
        def saved():
            llm.server.keep(False)
            if not self.kept():
                delete(self.path)
                self.on_change()
                return on_done(False)
            self.summary.waiting = self.summary.waiting or time.time()
            self.save()
            self.on_change()
            on_done(True)
        threading.Thread(target=finish, daemon=True).start()

    def final_pass(self, then):
        """Once it's stopped: sort what's left into topics, merge any that are one subject, and write the final
        summary, then then() (on the GTK thread). On the larger model on the GPU, unless that's busy and you've
        said not to wait for it (waiting.py)."""
        def done():
            self.summary.waiting = None
            self.save()
            self.on_change()
            then()
        final = lambda: self.summarise(final=True, then=done) or done()
        tidy = lambda: self.merge_topics(then=final) or final()
        if not self.sort_topics(then=tidy):
            tidy()

    def quiet_for(self):
        """Seconds since anything was last added to the transcript (or since it started, or was last resumed)."""
        return self.now() - max([self.resumed, *(end for _, _, end, _, _ in self.kept())])

    # --- topics ---
    def lines(self):
        """[(start, who's name, text)]: what's in the transcript, a line per stretch (once it's known who said it:
        not those still to be split between voices)."""
        return [(start, self.name(who, vid), text) for who, start, _, text, vid in self.kept()
                if not (who == "them" and start in self.pending)]

    def tick(self):
        """Every few seconds: sort what's been said into topics, when it's due."""
        if self.stopped:
            return False
        lines, slow = [line for line in self.lines() if line[0] not in self.asked], llm.server.mode == "cpu"
        if not self.asking and self.topics.due(lines, self.now() - self.last_topics, slow):
            self.sort_topics()
        elif not self.asking and self.now() - self.last_merge >= topics.MERGE:
            self.merge_topics()
        elif not self.asking and llm.server.mode == "gpu" and (part := self.summary.slice_due(self.lines())):
            # (on the GPU only: the smaller model's slices would be rough, and they can wait for the final pass)
            self.summarise_slice(part)
        elif not self.asking and self.summary.due(self.lines(), self.now() - self.last_summary, slow):
            self.summarise()
        self.back_to_gpu()
        return True

    def back_to_gpu(self):
        """With the smaller model on the CPU (the GPU was busy), switch to the larger one on the GPU once it's
        been free for a while (not just a game's loading screen), between topic updates and dictations."""
        if llm.server.mode != "cpu" or self.asking:
            self.gpu_free_for = 0.0
            return
        self.gpu_free_for = self.gpu_free_for + topics.TICK if llm.gpu_ok() else 0.0
        if self.gpu_free_for >= topics.FREE_FOR:
            self.gpu_free_for, self.asking = 0.0, True  # no topics while it loads
            def switch():
                switched = llm.server.to_gpu()
                GLib.idle_add(lambda: (setattr(self, "asking", False), switched and self.on_change()) and False)
            threading.Thread(target=switch, daemon=True).start()

    def sort_topics(self, then=None):
        """Ask the model for the topics of what hasn't been sorted yet (on a thread), then save and show
        them, then then(). Returns False if there was nothing to sort (and then() isn't called)."""
        lines = self.lines()
        new = [line for line in lines if line[0] not in self.asked]
        if not new:
            return False
        before = [line for line in lines if line[0] in self.asked]
        self.asked.update(line[0] for line in new)
        self.asking, self.last_topics = True, self.now()
        def ask():
            try:
                reply, n = self.topics.ask(new, before)
            except (OSError, ValueError, KeyError) as err:
                log.warning("topics: couldn't ask the model: %s", err)
                reply, n = None, 0
            GLib.idle_add(answered, reply, n, llm.server.mode)
        def answered(reply, n, model):
            self.asking = False
            if model == "cpu":
                self.topics.small = True
            self.asked.difference_update(line[0] for line in new[n:])  # (those that didn't fit: next time)
            if reply is None:
                self.asked.difference_update(line[0] for line in new)  # try again next time
            elif self.topics.apply(new[:n], reply):
                self.save()
                self.on_change()
            if then:
                then()
        threading.Thread(target=ask, daemon=True).start()
        return True

    def summarise(self, final=False, then=None):
        """Ask the model (on a thread) for the summary, updated with what's been said since (or, final, the final
        pass), then save and show it, then then(). Returns False if there's nothing to summarise (then() isn't
        called)."""
        lines = self.lines()
        if not lines or (not final and not self.summary.new(lines)):
            return False
        self.asking, self.last_summary = True, self.now()

        def ask():
            try:
                reply, slices = (self.summary.ask_final(lines, self.topics) if final
                                 else (self.summary.ask(lines, self.topics), None))
            except (OSError, ValueError, KeyError) as err:
                log.warning("summary: couldn't ask the model: %s", err)
                reply = slices = None
            GLib.idle_add(answered, reply, slices)

        def answered(reply, slices):
            self.asking = False
            if reply is not None and self.summary.take(reply, lines, final, slices):
                self.save()
                self.on_change()
            if then:
                then()
        threading.Thread(target=ask, daemon=True).start()
        return True

    def summarise_slice(self, part):
        """Ask the model (on a thread) for the summary of one slice of the conversation, part (its lines), and
        keep it, for the final summary."""
        self.asking = True

        def ask():
            try:
                text = self.summary.ask_slice(part)
            except (OSError, ValueError, KeyError) as err:
                log.warning("summary: couldn't summarise a slice: %s", err)
                text = None
            GLib.idle_add(answered, text)

        def answered(text):
            self.asking = False
            if text:
                self.summary.take_slice(part, text)
                self.save()
        threading.Thread(target=ask, daemon=True).start()

    def merge_topics(self, then=None):
        """Ask the larger model (on a thread) which topics turned out to be one subject, and merge them, then
        then(). Returns False if it isn't asked (too few topics, or the smaller model's loaded: then() isn't
        called)."""
        self.last_merge = self.now()
        if len(self.topics.topics) < topics.MERGE_FROM or llm.server.mode != "gpu":
            return False
        self.asking = True
        def ask():
            try:
                reply = self.topics.merge_ask()
            except (OSError, ValueError, KeyError) as err:
                log.warning("topics: couldn't ask the model: %s", err)
                reply = None
            GLib.idle_add(answered, reply)
        def answered(reply):
            self.asking = False
            if reply is not None and self.topics.merge_apply(reply):
                self.save()
                self.on_change()
            if then:
                then()
        threading.Thread(target=ask, daemon=True).start()
        return True

    def topic_view(self):
        """(topics, {paragraph's place: topic index}, [[who started each topic, who else spoke on it]])."""
        marks = {i: p[3] for i, p in enumerate(self._paragraphs()) if p[3] is not None}
        return self.topics, marks, self.topics.people(self.lines())

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
        if vid == UNKNOWN:  # the first stretch from the speakers, not split between voices yet
            return "…"
        return self.voices.label(vid) if vid is not None else NAMES[who]

    def paragraphs(self):
        """[(clock time, who's name, text)]: each person's consecutive stretches on one topic run together."""
        return [tuple(p[:3]) for p in self._paragraphs()]

    def _paragraphs(self):
        """[[clock, who, text, topic index or None]]. What's not sorted into topics yet carries on the topic
        before it, so a paragraph isn't split until it's known that the topic changed."""
        out, last = [], None
        for who, start, end, text, vid in self.kept():
            name = self.name(who, vid)
            topic = self.topics.of.get(start) if start in self.asked else (last and last[2])
            if last and last[0] == name and start - last[1] < JOIN and topic == last[2]:
                out[-1][2] += " " + text
            else:
                clock = f"{self.started + timedelta(seconds=start):%H:%M:%S}"
                out.append([clock, name, text, topic])
            last = (name, end, topic)
        return out

    def markdown(self):
        head = (f"# Transcript, {self.started:%A %-d %B %Y, %H:%M}\n\n"
                f"Lasted {length(self.now())}, until {datetime.now():%H:%M}.\n")
        above = summary.markdown(self.summary.text) + topics_markdown(self.topics, self.topics.people(self.lines()))
        head += above + ("\n## Transcript\n" if above else "")
        return head + "".join(f"\n**{clock} {who}:** {text}\n" for clock, who, text in self.paragraphs())

    def save(self):
        if self.deleted:  # (while its final pass was waiting, or being done)
            return
        store.write_text(self.path, self.markdown())
        if self.topics.topics:
            marks = self.topic_view()[1]  # saved by paragraph: a saved transcript has no stretches
            store.write_json(topics_file(self.path), {**self.topics.data(), "of": list(marks.items())})
        if self.summary.text or self.summary.waiting:
            store.write_json(summary_file(self.path), self.summary.data())
        else:  # (one that was only there to say it was waiting)
            summary_file(self.path).unlink(missing_ok=True)
        if self.voices and voices.remembering():  # so its voices can be named, and remembered, later
            store.write_json(voiceprints(self.path), self.voices.labelled())
