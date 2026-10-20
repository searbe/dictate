"""Speech-to-text: Silero VAD strips non-speech, then Parakeet TDT 0.6B v3 (int8, CPU)."""
import os, wave
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


def transcribe(wav_path):
    load()
    with wave.open(str(wav_path)) as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    speech = speech_only(samples)
    if speech is None:
        return ""
    s = _rec.create_stream()
    s.accept_waveform(RATE, speech)
    _rec.decode_stream(s)
    return s.result.text.strip()
