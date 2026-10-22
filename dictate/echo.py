"""Telling the speakers' sound picked up again by the microphone (an echo) from you speaking. Without
headphones the microphone hears the speakers too, often as loud as you, and PipeWire's echo canceller (where
there is one: see osio.Recorder's echo_cancel) only takes some of it out.

An echo is the speakers' sound a moment later, changed by the room: louder or quieter at each pitch, and
ringing on for a little while. So for each stretch the microphone hears, find how well the speakers' sound
just before can make it, in 16 bands of pitch, by gains of its own for each band. Nearly all of an echo can be
made that way; when you speak, your voice can't be, as the speakers never played it. Measured on a desktop
microphone a metre from its speakers: at most 38% of an echo was left over; with you speaking over the
speakers, at least 44% (as loud as them) to 77% (louder).

Through PipeWire's echo canceller it's less clear-cut: it changes what's left of the echo unevenly, so up to 70%
of an echo can be left over (what it says is checked against what the speakers said, too: see transcript.py),
and by its sound alone that can't be told from you saying something over the speakers. But an echo is about as
loud each time, relative to the speakers (measured: -1 to -18 dB, mostly -3 to -10), and you speaking into your
microphone makes it louder than that. So a stretch is an echo too if most of it could be the speakers' sound
(LOOSE) and it's no louder than the echoes so far on this call (LOUDER)."""
import statistics
import threading
import numpy as np

RATE, FRAME = 16000, 320  # 20 ms frames
EDGES = np.geomspace(100, 8000, 17)  # 16 bands of pitch, each a fixed share of an octave
LAGS = range(-15, 26)  # frames: the microphone hears the speakers 0.3 s before (the recordings start at
# slightly different moments) to 0.5 s after
RINGS = (0, 2, 5, 10)  # frames: the speakers' sound now, and 40, 100 and 200 ms ago (a room rings on)
KEEP = 120 * RATE // FRAME  # frames of the speakers' sound kept: two minutes
LEFT_OVER = 0.42  # an echo: at most this share of the microphone's sound left over once the speakers' is
LOOSE = 0.6  # or at most this much, if it's no louder than LOUDER dB above the echoes so far (their median),
LOUDER = 4.0  # relative to the speakers
ECHOES = 3, 50  # echoes needed before a stretch's loudness can be judged, and the most remembered
PLAYING = 0.5  # and the speakers were playing for at least this share of it
QUIET = 1e-4  # frame power (about -90 dB) below which the speakers aren't playing anything
_window, _hz = np.hanning(FRAME), np.fft.rfftfreq(FRAME, 1 / RATE)
_band = [(_hz >= a) & (_hz < b) for a, b in zip(EDGES, EDGES[1:])]


def bands(samples):
    """(frames, 16): the power in each band of each 20 ms frame of samples (16 kHz float32)."""
    n = len(samples) // FRAME * FRAME
    power = np.abs(np.fft.rfft(samples[:n].reshape(-1, FRAME) * _window, axis=1)) ** 2
    return np.stack([power[:, b].sum(1) for b in _band], 1)


def left_over(mic, speakers):
    """The share of mic's sound (bands) that speakers' (bands, len(mic) + max(RINGS) frames, ending together)
    can't make: the least squares fit of each band from the speakers' now and just before, by gains >= 0."""
    n, rest, total = len(mic), 0.0, float(mic.sum()) or 1.0
    made = np.stack([speakers[len(speakers) - n - k:len(speakers) - k] for k in RINGS], 2)  # (n, bands, rings)
    for b in range(mic.shape[1]):
        gains = np.maximum(0, np.linalg.lstsq(made[:, b], mic[:, b], rcond=None)[0])
        rest += float(np.maximum(0, mic[:, b] - made[:, b] @ gains).sum())
    return rest / total


class Echo:
    """played() is given what the speakers play as it's recorded; echo() says whether a stretch the
    microphone heard was them, at the same time, give or take LAGS."""

    def __init__(self):
        self.frames, self.first, self.leftover, self.lock = [], 0, b"", threading.Lock()
        self.gains = []  # dB: how loud the latest echoes were, relative to the speakers

    def played(self, chunk):
        """More of the speakers' sound: bytes of 16-bit samples (on the recorder's thread)."""
        data = self.leftover + chunk
        whole = len(data) // (2 * FRAME) * 2 * FRAME
        self.leftover = data[whole:]
        if whole:
            new = bands(np.frombuffer(data[:whole], np.int16).astype(np.float32) / 32768)
            with self.lock:
                self.frames.extend(new)
                if len(self.frames) > KEEP:
                    self.first += len(self.frames) - KEEP
                    del self.frames[:len(self.frames) - KEEP]

    def echo(self, start, samples):
        """Whether samples (16 kHz float32), heard by the microphone from start seconds, were the speakers."""
        mic = bands(samples)
        a, n = round(start * RATE / FRAME), len(mic)
        if n < 10:
            return False
        with self.lock:
            first, frames = self.first, self.frames
            fits = []
            for lag in LAGS:  # the speakers' frames a - lag - max(RINGS) .. a - lag + n
                lo, hi = a - lag - max(RINGS) - first, a - lag + n - first
                if 0 < hi <= len(frames) and (lo >= 0 or not first):  # before the recording began: silence
                    fits.append(np.concatenate([np.zeros((max(0, -lo), len(EDGES) - 1)), frames[max(0, lo):hi]]))
        playing = [float((f[max(RINGS):].sum(1) > QUIET).mean()) for f in fits]
        if not fits or max(playing) < PLAYING:
            return False
        left, f = min(((left_over(mic, f), i) for i, f in enumerate(fits)))
        gain = 10 * np.log10(max(float(mic.sum()), 1e-12) / max(float(fits[f][max(RINGS):].sum()), 1e-12))
        if left <= LEFT_OVER:
            self.gains = (self.gains + [gain])[-ECHOES[1]:]
            return True
        return left <= LOOSE and len(self.gains) >= ECHOES[0] and gain <= statistics.median(self.gains) + LOUDER
