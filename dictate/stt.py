"""Speech-to-text: Silero VAD strips non-speech, then Parakeet TDT 0.6B v3 (int8, CPU).

Live transcribes while recording: at each pause, the speech so far is transcribed in the background,
so when recording stops only the stretch since the last pause is left. transcribe() does a whole file."""
import collections
import os
import threading
import time
import wave

import numpy as np
import sherpa_onnx

from . import ROOT

MODELS = ROOT / "models"
RATE = 16000
PREVIEW = 1.0  # seconds between previews of the stretch still being spoken (transcribe mode)
PREVIEW_PAUSE = 0.25  # seconds: a preview is built from the stretch's pieces between pauses this short
THREADS = min(4, os.cpu_count() or 4)  # more only spin: 8 cost twice the CPU of 4 for the same speed
_rec = _vad_cfg = None


def load():
    """Load models once (slow, ~1s); called in the background at startup."""
    global _rec, _vad_cfg
    if _rec:
        return
    p = MODELS / "parakeet"
    _rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(p / "encoder.int8.onnx"), decoder=str(p / "decoder.int8.onnx"),
        joiner=str(p / "joiner.int8.onnx"), tokens=str(p / "tokens.txt"),
        model_type="nemo_transducer", num_threads=THREADS)
    _vad_cfg = vad_config(0.4)


def vad_config(pause):
    """Silero VAD's settings, ending a stretch of speech at a pause of this many seconds."""
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(MODELS / "silero_vad.onnx")
    cfg.silero_vad.min_silence_duration = pause
    cfg.sample_rate = RATE
    return cfg


def stretches(samples, pause=0.4):
    """[(start sample, samples)]: the stretches of speech in samples, as Live would find them."""
    vad = sherpa_onnx.VoiceActivityDetector(vad_config(pause),
                                            buffer_size_in_seconds=max(60, len(samples) // RATE + 10))
    win = _vad_cfg.silero_vad.window_size
    for i in range(0, len(samples), win):
        vad.accept_waveform(samples[i:i + win])
    vad.flush()
    out = []
    while not vad.empty():
        out.append((vad.front.start, np.array(vad.front.samples, dtype=np.float32)))
        vad.pop()
    return out


def speech_only(samples):
    """Keep only the segments Silero thinks are speech (stops noise/music becoming text)."""
    vad = sherpa_onnx.VoiceActivityDetector(_vad_cfg, buffer_size_in_seconds=600)
    win = _vad_cfg.silero_vad.window_size
    for i in range(0, len(samples), win):
        vad.accept_waveform(samples[i:i + win])
    vad.flush()
    pad = np.zeros(RATE // 5, dtype=np.float32)  # 200ms gap between segments
    parts = []
    while not vad.empty():
        parts += [np.array(vad.front.samples, dtype=np.float32), pad]
        vad.pop()
    return np.concatenate(parts) if parts else None


def _decode(samples):
    return _recognise(samples).text.strip()


def _recognise(samples):
    s = _rec.create_stream()
    s.accept_waveform(RATE, samples)
    _rec.decode_stream(s)
    return s.result


def words(result):
    """[(seconds into the stretch, word)] from a result's pieces; the words joined are exactly its text."""
    out = []
    for piece, t in zip(result.tokens, result.timestamps):
        if not out or piece.startswith(" "):
            out.append([t, piece])
        else:
            out[-1][1] += piece
    return [tuple(w) for w in out]


def transcribe(wav_path):
    load()
    with wave.open(str(wav_path)) as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    speech = speech_only(samples)
    return _decode(speech) if speech is not None else ""


class Live:
    """Follows a WAV file while it's being recorded, or (no wav_path) the 16-bit samples given to push().
    Each stretch of speech the VAD closes off (i.e. after a pause) is transcribed in the background;
    finish() does the rest and returns the text. on_text(start, end, text, samples, words), if given, is called
    (on Live's thread) for each stretch as it's transcribed, with its start and end in seconds from the start
    and words() for when each word was said. on_preview(start, text), if given, is called about every PREVIEW
    seconds while a stretch is still being spoken, with what it says so far (for showing only: the stretch is
    transcribed whole once it ends)."""

    def __init__(self, wav_path=None, on_text=None, on_preview=None, pause=None):
        self.pause = pause  # seconds of silence that end a stretch (default: 0.4, for dictation)
        self.path, self.data, self.leftover, self.texts, self.done = wav_path, None, b"", [], False
        self.on_text, self.on_preview, self.previewed, self.pushed = on_text, on_preview, 0.0, collections.deque()
        self.pieces = {}  # the stretch being spoken: its pieces' text so far, by where they start (see _preview)
        self.thread = threading.Thread(target=self._follow, daemon=True)
        self.thread.start()

    def _follow(self):
        load()  # a no-op unless dictating straight after launch
        self.vad = sherpa_onnx.VoiceActivityDetector(vad_config(self.pause) if self.pause else _vad_cfg,
                                                     buffer_size_in_seconds=600)
        self.window = _vad_cfg.silero_vad.window_size
        while not self.done:
            self._feed()
            self._preview()
            time.sleep(0.1)

    def push(self, samples):
        """More audio (bytes of 16-bit mono samples), from any thread."""
        self.pushed.append(samples)

    def _new(self):
        """The audio recorded since last time, or None if there's none yet."""
        if self.path is None:
            chunks = []
            while self.pushed:
                chunks.append(self.pushed.popleft())
            return b"".join(chunks)
        try:
            with open(self.path, "rb") as f:
                if self.data is None:  # find where the samples start, once the header has been written
                    header = f.read(4096)
                    if header.find(b"data") < 0:
                        return
                    self.data = header.find(b"data") + 8
                f.seek(self.data)
                new = f.read()
        except OSError:  # not created yet
            return
        self.data += len(new)
        return new

    def _feed(self):
        """Read the audio recorded since last time and transcribe any stretch of speech that has ended."""
        new = self._new()
        if new is None:
            return
        new = self.leftover + new
        usable = len(new) - len(new) % (2 * self.window)  # whole VAD windows of 16-bit samples
        self.leftover = new[usable:]
        samples = np.frombuffer(new[:usable], dtype=np.int16).astype(np.float32) / 32768
        for i in range(0, len(samples), self.window):
            self.vad.accept_waveform(samples[i:i + self.window])
        self._decode_ready()

    def _decode_ready(self):
        while not self.vad.empty():
            seg = self.vad.front
            samples = np.array(seg.samples, dtype=np.float32)
            result = _recognise(samples)
            self.texts.append(text := result.text.strip())
            if self.on_text and text:
                self.on_text(seg.start / RATE, (seg.start + len(samples)) / RATE, text, samples, words(result))
            self.vad.pop()

    def _preview(self):
        """What the stretch still being spoken says so far, about every PREVIEW seconds. It grows as it's said:
        the stretch is cut at its short pauses (PREVIEW_PAUSE), each piece before the last is transcribed once
        and kept, and only the last, still being said, again each time; so what's shown doesn't jump about.
        (The whole stretch is transcribed again once it ends, with all of it to go on: that's what's kept.)"""
        if not self.on_preview or not self.vad.is_speech_detected() or time.monotonic() - self.previewed < PREVIEW:
            return
        self.previewed = time.monotonic()
        seg = self.vad.current_segment
        samples = np.array(seg.samples, dtype=np.float32)
        if len(samples) <= RATE // 2:
            return
        if self.pieces.get("stretch") != seg.start:  # a new stretch
            self.pieces = {"stretch": seg.start}
        pieces = stretches(samples, PREVIEW_PAUSE) or [(0, samples)]
        texts = []
        for k, (at, piece) in enumerate(pieces):
            last = k == len(pieces) - 1
            done = self.pieces.get(at)
            if last or done is None or done[0] != len(piece):  # (a finished piece's text is kept)
                done = (len(piece), _decode(piece))
                if not last:
                    self.pieces[at] = done
            texts.append(done[1])
        text = " ".join(t for t in texts if t)
        at, tail = pieces[-1]
        if text:
            self.on_preview(seg.start / RATE, text, tail, (seg.start + at) / RATE)

    def finish(self):
        """Call once recording has stopped and the file is complete. Returns the whole transcript."""
        self.done = True
        self.thread.join()
        self._feed()
        tail = self.leftover[:len(self.leftover) // 2 * 2]  # a final partial window, whole samples only
        if tail:
            self.vad.accept_waveform(np.frombuffer(tail, dtype=np.int16).astype(np.float32) / 32768)
        self.vad.flush()
        self._decode_ready()
        return " ".join(t for t in self.texts if t)
