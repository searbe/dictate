"""What's being played back: the one place that knows. A dictation's recording, or part of a transcript's call
(both its recordings, mixed). The pages draw their Play / Stop buttons and the paragraph being played from it, and
nothing else, so two of them can never disagree or play over each other.

A transcript's part is prepared on a thread first (the call is mixed once, then the part cut from it: see
transcript.cut), which for a long call takes a few seconds; meanwhile it's already what's playing ("preparing"),
so a second click stops it instead of starting another. Each request is its own: one that's been replaced or
stopped by the time it's ready is thrown away, and its file deleted."""
import itertools
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from gi.repository import GLib

from . import transcript

log = logging.getLogger(__name__)

TICK = 250  # ms between telling the pages where it's got to, while a transcript plays
_parts = itertools.count()


@dataclass(eq=False)
class Playing:
    """What's playing: source, a dictation's recording or a transcript (its .md); of a transcript, start and end
    seconds into the call (end None: to the end). began: when the sound started (monotonic), None while it's
    being prepared."""
    source: Path
    start: float = 0.0
    end: float | None = None
    began: float | None = None
    file: Path | None = None  # the part cut for it, deleted once it's done

    @property
    def preparing(self):
        return self.began is None

    def at(self):
        """Seconds into the call it's got to (its start while it's being prepared)."""
        if self.began is None:
            return self.start
        at = self.start + time.monotonic() - self.began
        return min(at, self.end) if self.end is not None else at


class Playback:
    """player: osio.Player. listen(fn): fn() on the GTK thread whenever what's playing changes, and every TICK
    while a transcript plays; returns a function that stops telling it."""

    def __init__(self, player):
        self.player, self.now, self.listeners, self.ticking = player, None, [], None
        for left in (Path(GLib.get_user_cache_dir()) / "dictate").glob("part-*.wav"):  # (if Dictate didn't exit)
            left.unlink(missing_ok=True)

    def listen(self, fn):
        self.listeners.append(fn)
        return lambda: fn in self.listeners and self.listeners.remove(fn)

    def changed(self):
        for fn in list(self.listeners):
            fn()

    def playing(self, source):
        """What's playing of source (a dictation's recording or a transcript), or None."""
        return self.now if self.now and self.now.source == source else None

    def play_file(self, path):
        """Play a recording (a dictation's) as it is."""
        self.stop(quietly=True)
        self.now = now = Playing(Path(path), began=time.monotonic())
        self.player.play(str(path), lambda: self.done(now))
        self.changed()

    def play_transcript(self, path, start=0.0, end=None):
        """Play a transcript's call from start to end seconds (end None: to its end)."""
        self.stop(quietly=True)
        self.now = now = Playing(Path(path), start, end)
        out = Path(GLib.get_user_cache_dir()) / "dictate" / f"part-{next(_parts)}.wav"

        def prepare():
            ok = transcript.cut(path, start, end, out)
            GLib.idle_add(lambda: ready(ok) and False)

        def ready(ok):
            if self.now is not now:  # stopped or replaced meanwhile
                out.unlink(missing_ok=True)
                return
            if not ok:  # its recordings have gone
                self.now = None
                self.changed()
                return
            now.file, now.began = out, time.monotonic()
            self.player.play(str(out), lambda: self.done(now))
            self.tick_on()
            self.changed()
        threading.Thread(target=prepare, daemon=True).start()
        self.changed()

    def done(self, now):
        """now has finished playing, or been stopped or replaced (on the GTK thread)."""
        if now.file:
            now.file.unlink(missing_ok=True)
        if self.now is now:
            self.now = None
            self.changed()

    def stop(self, quietly=False):
        """Stop whatever's playing or being prepared (quietly: without telling the pages, as something else is
        about to play)."""
        now, self.now = self.now, None
        if now and not now.preparing:
            self.player.stop()  # (its done() follows, and deletes its file)
        if now and not quietly:
            self.changed()

    def tick_on(self):
        if not self.ticking:
            self.ticking = GLib.timeout_add(TICK, self.tick)

    def tick(self):
        if not (self.now and not self.now.preparing and self.now.source.suffix == ".md"):
            self.ticking = None
            return False
        self.changed()
        return True
