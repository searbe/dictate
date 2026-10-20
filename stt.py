"""Speech-to-text: Silero VAD strips non-speech, then Parakeet TDT 0.6B v3 (int8, CPU).

Live transcribes while recording: at each pause, the speech so far is transcribed in the background,
so when recording stops only the stretch since the last pause is left. transcribe() does a whole file."""
import os, threading, time, wave
from pathlib import Path
import numpy as np
import sherpa_onnx

MODELS = Path(__file__).parent / "models"
RATE = 16000
THREADS = min(8, os.cpu_count() or 4)
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
    _vad_cfg = sherpa_onnx.VadModelConfig()
    _vad_cfg.silero_vad.model = str(MODELS / "silero_vad.onnx")
    _vad_cfg.silero_vad.min_silence_duration = 0.4
    _vad_cfg.sample_rate = RATE


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
    s = _rec.create_stream()
    s.accept_waveform(RATE, samples)
    _rec.decode_stream(s)
    return s.result.text.strip()


def transcribe(wav_path):
    load()
    with wave.open(str(wav_path)) as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    speech = speech_only(samples)
    return _decode(speech) if speech is not None else ""


class Live:
    """Follows a WAV file while it's being recorded. Each stretch of speech the VAD closes off
    (i.e. after a pause) is transcribed in the background; finish() does the rest and returns the text."""

    def __init__(self, wav_path):
        self.path, self.data, self.leftover, self.texts, self.done = wav_path, None, b"", [], False
        self.thread = threading.Thread(target=self._follow, daemon=True)
        self.thread.start()

    def _follow(self):
        load()  # a no-op unless dictating straight after launch
        self.vad = sherpa_onnx.VoiceActivityDetector(_vad_cfg, buffer_size_in_seconds=600)
        self.window = _vad_cfg.silero_vad.window_size
        while not self.done:
            self._feed()
            time.sleep(0.1)

    def _feed(self):
        """Read the audio appended since last time and transcribe any stretch of speech that has ended."""
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
        new = self.leftover + new
        usable = len(new) - len(new) % (2 * self.window)  # whole VAD windows of 16-bit samples
        self.leftover = new[usable:]
        samples = np.frombuffer(new[:usable], dtype=np.int16).astype(np.float32) / 32768
        for i in range(0, len(samples), self.window):
            self.vad.accept_waveform(samples[i:i + self.window])
        self._decode_ready()

    def _decode_ready(self):
        while not self.vad.empty():
            self.texts.append(_decode(np.array(self.vad.front.samples, dtype=np.float32)))
            self.vad.pop()

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
