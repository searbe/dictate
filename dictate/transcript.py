"""Transcribe mode: what's said through this computer's speakers ("Them") and into its microphone ("Me"),
written into a transcript as it's heard. Each stretch of speech is transcribed by stt.Live as soon as
there's a pause, so the transcript grows while people talk.

Left out: your dictations (the microphone is muted while you hold Ctrl+Win), Dictate playing a recording
back, anything said while paused, and the speakers' sound picked up again by the microphone (the same
words at the same time as Them are an echo, not you).

Saved as Markdown in data/transcripts/, rewritten after every new stretch, with an Ogg Opus recording per
source beside it (about 12 MB an hour each, kept as long as dictation recordings are)."""
import re, threading, time
from datetime import datetime, timedelta
from gi.repository import GLib
from . import DATA, osio, stt

FOLDER = DATA / "transcripts"
SOURCES = (("me", False), ("them", True))  # who, recorded from the speakers
NAMES = {"me": "Me", "them": "Them"}
JOIN = 10  # seconds: a stretch this soon after the same person's last one continues their paragraph
ECHO = 0.6  # share of a stretch's words also heard through the speakers at the same time, for it to be an echo


class Session:
    """A transcript being recorded. on_change() runs on the GTK thread whenever the transcript changes."""

    def __init__(self, on_change=lambda: None):
        FOLDER.mkdir(parents=True, exist_ok=True)
        self.started, self.t0, self.on_change = datetime.now(), time.monotonic(), on_change
        stamp = f"{self.started:%Y-%m-%d %H.%M.%S}"
        self.path = FOLDER / f"{stamp}.md"
        self.heard = []  # (who, start, end, text), in seconds since the start
        self.muted = {who: [] for who, _ in SOURCES}  # [start, end] (end None: still muted)
        self.paused = self.stopped = False
        self.recorders, self.lives, self.recordings = [], [], []
        for who, speakers in SOURCES:
            path = str(FOLDER / f"{stamp} {who}.ogg")
            live = stt.Live(on_text=lambda s, e, text, who=who: self.hear(who, s, e, text))
            rec = osio.Recorder()
            rec.start(path, speakers=speakers, on_audio=live.push)
            self.recorders.append(rec)
            self.recordings.append(path)
            self.lives.append(live)
        self.save()

    def now(self):
        return time.monotonic() - self.t0

    def hear(self, who, start, end, text):
        """A stretch of speech has been transcribed (on Live's thread)."""
        GLib.idle_add(self._add, (who, start, end, text))

    def _add(self, stretch):
        self.heard.append(stretch)
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
        def muted(who, start, end):
            return any(a < end and (b is None or b > start) for a, b in self.muted[who])
        them = [h for h in self.heard if h[0] == "them"]
        def echo(start, end, text):
            words = set(re.findall(r"\w+", text.lower()))
            for _, s, e, t in them:
                if s < end + 1 and e > start - 1 and words:  # the same moment, give or take a second
                    if len(words & set(re.findall(r"\w+", t.lower()))) >= ECHO * len(words):
                        return True
            return False
        return sorted((h for h in self.heard if not muted(*h[:3]) and not (h[0] == "me" and echo(*h[1:]))),
                      key=lambda h: h[1])

    def paragraphs(self):
        """[(clock time, who's name, text)]: each person's consecutive stretches run together."""
        out, last = [], None
        for who, start, end, text in self.kept():
            if last and last[0] == who and start - last[1] < JOIN:
                out[-1][2] += " " + text
            else:
                clock = f"{self.started + timedelta(seconds=start):%H:%M:%S}"
                out.append([clock, NAMES[who], text])
            last = (who, end)
        return [tuple(p) for p in out]

    def markdown(self):
        head = f"# Transcript, {self.started:%A %-d %B %Y, %H:%M}\n"
        return head + "".join(f"\n**{clock} {who}:** {text}\n" for clock, who, text in self.paragraphs())

    def save(self):
        self.path.write_text(self.markdown())
