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
beside it too, so a voice can be named (and remembered) after the call.

Its topics (topics.py) are kept up to date as it's heard, listed at the top of the transcript, and saved
beside it with which paragraph is on which, by their place in it (a paragraph ends where the topic changes). So
is a live summary (summary.py), with a final pass when it's stopped; above the topics."""
import json, re, threading, time
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from gi.repository import GLib
from . import DATA, echo, osio, refine, stt, summary, topics, voices

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


def summary_file(path):
    """Where the summary of the transcript at path is kept."""
    return path.with_name(f"{path.stem} summary.json")


def read_summary(path):
    """The summary of the saved transcript at path, or None."""
    try:
        data = json.loads(summary_file(path).read_text())
        return summary.Summary(data["text"], data.get("final", False))
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


def mixdown(path, start=0.0):
    """The transcript's recordings (this computer's audio and the microphone) mixed into one WAV from start
    seconds on, to play back; its path, or None if they're gone (they're kept for "keep recordings")."""
    import soundfile
    tracks, rate = [], stt.RATE
    for rec in recordings(path):
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
    out = Path(GLib.get_user_cache_dir()) / "dictate" / "playback.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(str(out), np.clip(mix[int(start * rate):], -1, 1), rate, subtype="PCM_16")
    return out


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
    """A saved transcript: {"path", "started", "length", "paragraphs": [(clock, who, text)], "changed"}, or None."""
    try:
        started, text, changed = datetime.strptime(path.stem, STAMP), path.read_text(), path.stat().st_mtime
    except (ValueError, OSError):
        return None
    lasted = LASTED.search(text)
    return {"path": path, "started": started, "length": lasted[1] if lasted else "", "paragraphs": PARAGRAPH.findall(text),
            "changed": changed}


def saved():
    """Every saved transcript, newest first."""
    return [t for t in map(read, sorted(FOLDER.glob("*.md"), reverse=True)) if t]


def delete(path):
    """Delete a saved transcript, its recordings, voiceprints, topics and summary."""
    for f in [path, *recordings(path), voiceprints(path), topics_file(path), summary_file(path)]:
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
        self.topics, self.asked, self.asking, self.last_topics = topics.Topics(), set(), False, self.now()
        self.last_merge = self.now()
        self.summary, self.last_summary = summary.Summary(), self.now()
        self.gpu_free_for = 0.0  # seconds the GPU has been free while the smaller model is loaded on the CPU
        refine.keep(True)  # the model, loaded for the whole call (from now, so it's ready for the first topics)
        refine.warm(hold=False)
        GLib.timeout_add(int(topics.TICK * 1000), self.tick)
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

    def stop(self, on_done, last_topics=True):
        """Stop recording, transcribe what's left, save, sort what's left into topics, merge any that are one
        subject and write the final summary (unless not last_topics: quitting doesn't wait for the model), then
        on_done() on the GTK thread. If nothing was heard, nothing is kept: the transcript and its recordings are deleted."""
        self.stopped = True
        def finish():
            for rec in self.recorders:
                rec.stop()
            for live in self.lives:
                live.finish()  # its last stretches arrive through hear(), before on_done
            GLib.idle_add(saved)
        def saved():
            if not self.kept():
                delete(self.path)
                self.on_change()
                return done()
            self.save()
            self.on_change()
            final = lambda: self.summarise(final=True, then=done) or done()
            tidy = lambda: self.merge_topics(then=final) or final()
            if not last_topics:
                done()
            elif not self.sort_topics(then=tidy):
                tidy()
        def done():
            refine.keep(False)
            on_done()
        threading.Thread(target=finish, daemon=True).start()

    def quiet_for(self):
        """Seconds since anything was last added to the transcript (or since it started)."""
        return self.now() - max((end for _, _, end, _, _ in self.kept()), default=0.0)

    # --- topics ---
    def lines(self):
        """[(start, who's name, text)]: what's in the transcript, a line per stretch."""
        return [(start, self.name(who, vid), text) for who, start, _, text, vid in self.kept()]

    def tick(self):
        """Every few seconds: sort what's been said into topics, when it's due."""
        if self.stopped:
            return False
        lines = [l for l in self.lines() if l[0] not in self.asked]
        if not self.asking and self.topics.due(lines, self.now() - self.last_topics):
            self.sort_topics()
        elif not self.asking and self.now() - self.last_merge >= topics.MERGE:
            self.merge_topics()
        elif not self.asking and self.summary.due(self.lines(), self.now() - self.last_summary):
            self.summarise()
        self.back_to_gpu()
        return True

    def back_to_gpu(self):
        """With the smaller model on the CPU (the GPU was busy), switch to the larger one on the GPU once it's
        been free for a while (not just a game's loading screen), between topic updates and dictations."""
        if refine.mode() != "cpu" or self.asking:
            self.gpu_free_for = 0.0
            return
        self.gpu_free_for = self.gpu_free_for + topics.TICK if refine.gpu_ok() else 0.0
        if self.gpu_free_for >= topics.FREE_FOR:
            self.gpu_free_for, self.asking = 0.0, True  # no topics while it loads
            def switch():
                switched = refine.to_gpu()
                GLib.idle_add(lambda: (setattr(self, "asking", False), switched and self.on_change()) and False)
            threading.Thread(target=switch, daemon=True).start()

    def sort_topics(self, then=None):
        """Ask the model for the topics of what hasn't been sorted yet (on a thread), then save and show
        them, then then(). Returns False if there was nothing to sort (and then() isn't called)."""
        lines = self.lines()
        new = [l for l in lines if l[0] not in self.asked]
        if not new:
            return False
        before = [l for l in lines if l[0] in self.asked]
        self.asked.update(l[0] for l in new)
        self.asking, self.last_topics = True, self.now()
        def ask():
            try:
                reply = self.topics.ask(new, before)
            except (OSError, ValueError, KeyError) as err:
                print("topics: couldn't ask the model:", err, flush=True)
                reply = None
            GLib.idle_add(answered, reply, refine.mode())
        def answered(reply, model):
            self.asking = False
            if model == "cpu":
                self.topics.small = True
            if reply is None:
                self.asked.difference_update(l[0] for l in new)  # try again next time
            elif self.topics.apply(new, reply):
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
                reply = self.summary.ask_final(lines, self.topics) if final else self.summary.ask(lines, self.topics)
            except (OSError, ValueError, KeyError) as err:
                print("summary: couldn't ask the model:", err, flush=True)
                reply = None
            GLib.idle_add(answered, reply)

        def answered(reply):
            self.asking = False
            if reply is not None and self.summary.take(reply, lines, final):
                self.save()
                self.on_change()
            if then:
                then()
        threading.Thread(target=ask, daemon=True).start()
        return True

    def merge_topics(self, then=None):
        """Ask the larger model (on a thread) which topics turned out to be one subject, and merge them, then
        then(). Returns False if it isn't asked (too few topics, or the smaller model's loaded: then() isn't
        called)."""
        self.last_merge = self.now()
        if len(self.topics.topics) < topics.MERGE_FROM or refine.mode() != "gpu":
            return False
        self.asking = True
        def ask():
            try:
                reply = self.topics.merge_ask()
            except (OSError, ValueError, KeyError) as err:
                print("topics: couldn't ask the model:", err, flush=True)
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
        head = f"# Transcript, {self.started:%A %-d %B %Y, %H:%M}\n\nLasted {length(self.now())}, until {datetime.now():%H:%M}.\n"
        above = summary.markdown(self.summary.text) + topics_markdown(self.topics, self.topics.people(self.lines()))
        head += above + ("\n## Transcript\n" if above else "")
        return head + "".join(f"\n**{clock} {who}:** {text}\n" for clock, who, text in self.paragraphs())

    def save(self):
        self.path.write_text(self.markdown())
        if self.topics.topics:
            marks = self.topic_view()[1]  # saved by paragraph: a saved transcript has no stretches
            topics_file(self.path).write_text(json.dumps({**self.topics.data(), "of": list(marks.items())}))
        if self.summary.text:
            summary_file(self.path).write_text(json.dumps(self.summary.data()))
        if self.voices and voices.remembering():  # so its voices can be named, and remembered, later
            voiceprints(self.path).write_text(json.dumps(self.voices.labelled()))
