#!/usr/bin/env python3
"""Replay a transcribed call through transcribe mode again:
python scripts/replay_call.py "data/transcripts/<stem>" [out.md]

Takes a transcript's two recordings (`<stem> them.ogg` and `<stem> me.ogg`, while they're kept) and feeds them
through transcript.Session as a call would be heard (stt.Live, speaker voices, the echo check), then writes the
new transcript to out.md (by default a temporary file; never over the original) and prints who was heard, for how
long and how alike their voices are. Use it to see what a change to stt.py, voices.py, echo.py or transcript.py
does to a real call. Topics and the summary aren't made (no model is loaded). Remembered voices are only used
with --remembered (they're read, never changed)."""
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dictate

dictate.bootstrap(gui=False)
import numpy as np
import soundfile

from dictate import echo, stt, summary, topics, transcript, voices


def session(stem, out, remembered=()):
    """A Session as Session() makes one, without its recorders, model or timers."""
    s = transcript.Session.__new__(transcript.Session)
    s.started, s.t0, s.on_change = datetime.strptime(Path(stem).name, transcript.STAMP), time.monotonic(), lambda: None
    s.path, s.heard, s.voices, s.known, s.band = Path(out), [], voices.Voices(remembered), {}, (0.0, 0.0)
    s.previewing, s.echo, s.muted = {}, echo.Echo(), {who: [] for who, _ in transcript.SOURCES}
    s.paused = s.stopped = s.asking = False
    s.topics, s.asked, s.summary = topics.Topics(), set(), summary.Summary()
    s.start_settling()
    return s


def samples(audio):
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(" ".join(__doc__.splitlines()[:2]))  # the usage line
    stem = args[0].removesuffix(".md")
    out = args[1] if len(args) > 1 else tempfile.mkstemp(suffix=".md")[1]
    them = soundfile.read(f"{stem} them.ogg", dtype="float32")[0]
    me = soundfile.read(f"{stem} me.ogg", dtype="float32")[0]
    stt.load()
    lock = threading.Lock()
    transcript.GLib.idle_add = lambda f, *a: (lock.acquire(), f(*a), lock.release()) and False  # (no GTK loop here)
    echo.KEEP = len(them)  # (the speakers are given all at once, not as they play: keep all of it)
    s = session(stem, out, voices.remembered() if "--remembered" in sys.argv else ())
    voices.remembering = lambda: False  # (so nothing is written beside out.md)
    s.echo.played(samples(them))
    s.recent = transcript.Recent(len(them) / stt.RATE + 1)  # (all of it: it's given at once, not as it plays)
    s.recent.add(samples(them))
    for who, audio in (("them", them), ("me", me)):
        live = stt.Live(pause=transcript.PAUSE, on_text=lambda *heard, who=who: s.hear(who, *heard))
        live.push(samples(audio))
        live.finish()
    s.stopped = True
    s.finish_settling()
    s.now = lambda: len(them) / stt.RATE
    s.save()

    names = [who for _, who, _ in s.paragraphs()]
    print(f"{len(names)} paragraphs, written to {out}")
    centres, heard = s.voices.centres(), {}
    for v, seconds in zip(s.voices.of, s.voices.seconds):
        heard[v] = heard.get(v, 0.0) + seconds
    label = lambda v: s.voices.label(s.voices.of.index(v))
    for v in centres:
        alike = ", ".join(f"{label(o)} {float(centres[v] @ centres[o]):.2f}" for o in centres if o != v)
        print(f"  {label(v)}: {names.count(label(v))} paragraphs, {heard[v]:.0f} s heard; alike: {alike or '-'}")
    if "Me" in names:
        print(f"  Me: {names.count('Me')} paragraphs")


if __name__ == "__main__":
    main()
