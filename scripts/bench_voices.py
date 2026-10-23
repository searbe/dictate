#!/usr/bin/env python3
"""How well transcripts tell voices apart:
python scripts/bench_voices.py path/to/LibriSpeech/dev-clean [--no-turns] [--by-word]

Builds mock conversations between 2–4 LibriSpeech speakers (dev-clean, 337 MB from
https://www.openslr.org/resources/12/dev-clean.tar.gz), cuts them at pauses and between voices as transcribe
mode does (transcript.parts_of), and labels them with voices.py, as the saved transcript has them: "with pauses" between
turns, and "quick replies" (short turns, under 0.3 s apart, so stretches often hold two people), each at full quality
and as phone audio (300–3400 Hz).
Reports the share of speaking time labelled right, and how often the number of people found is right.
--no-turns labels each stretch whole (cut only at its short pauses), without looking for a change of voice
inside it."""
import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dictate

dictate.bootstrap(gui=False)
import numpy as np
import soundfile

from dictate import stt, transcript, voices

RATE, FRAME = 16000, 1600  # scored in tenths of a second
STYLES = {"with pauses": dict(gap=(0.3, 1.2), turn=None), "quick replies": dict(gap=(0.0, 0.3), turn=(1.2, 6.0))}


def conversation(rng, speakers, people, gap, turn, turns=16):
    """(audio, truth: the speaker of each frame, or None for silence)."""
    audio, truth, last = [], [], None
    for _ in range(turns):
        who = rng.choice([p for p in people if p != last])
        last = who
        clip, _ = soundfile.read(str(rng.choice(speakers[who])), dtype="float32")
        if turn:  # a short turn: part of an utterance
            n = int(RATE * rng.uniform(*turn))
            at = rng.randrange(max(1, len(clip) - n))
            clip = clip[at:at + n]
        pause = np.zeros(int(RATE * rng.uniform(*gap)), np.float32)
        audio += [clip, pause]
        truth += [who] * len(clip) + [None] * len(pause)
    return np.concatenate(audio), truth


def phone(audio):
    spectrum = np.fft.rfft(audio)
    hz = np.fft.rfftfreq(len(audio), 1 / RATE)
    spectrum[(hz < 300) | (hz > 3400)] = 0
    return np.fft.irfft(spectrum, len(audio)).astype(np.float32)


def label(audio, use_turns, by_word=False):
    """The voice labelled at each frame (None where nobody was heard), as a saved transcript has them. by_word:
    transcribe each stretch, and once two voices are known, tell its words apart by them (voices.by_word), as a
    transcript does (slower)."""
    found, labels, parts = voices.Voices(), [None] * (len(audio) // FRAME + 1), []
    narrow = voices.narrowband(audio)  # decided for the whole call, as a transcript does as it goes
    for start, samples in stt.stretches(audio, transcript.PAUSE):
        if by_word:
            words = stt.words(stt._recognise(samples))
            for a, b, vector, likely in transcript.voiced_parts(samples, words, narrow, found.told_apart()):
                parts.append((start + int(a * RATE), start + int(b * RATE), found.voice(vector, b - a, narrow, likely)))
            continue
        for a, b in transcript.parts_of(samples, None, narrow if use_turns else None):
            part = samples[int(a * RATE):int(b * RATE)]
            parts.append((start + int(a * RATE), start + int(b * RATE),
                          found.voice(voices.voiceprint(part), b - a, narrow)))
    for a, b, part in parts:  # the voice each part ended up with
        for f in range(a // FRAME, b // FRAME):
            labels[f] = found.of[part]
    return labels


def accuracy(labels, truth):
    """The share of speaking time labelled right, under the best matching of found voices to people."""
    pairs = [(truth[f * FRAME], labels[f]) for f in range(len(truth) // FRAME)
             if truth[f * FRAME] is not None and labels[f] is not None]  # someone speaking, and heard as speech
    people, found = sorted({t for t, _ in pairs}), sorted({label for _, label in pairs})
    best = 0
    for perm in itertools.permutations(found + [None] * len(people), len(people)):
        match = dict(zip(people, perm))
        best = max(best, sum(match[t] == label for t, label in pairs))
    return best / len(pairs), len(found)


def main():
    root, use_turns, by_word = Path(sys.argv[1]), "--no-turns" not in sys.argv, "--by-word" in sys.argv
    speakers = {d.name: sorted(d.rglob("*.flac")) for d in root.iterdir() if d.is_dir()}
    stt.load()
    for style, shape in STYLES.items():
        for quality, change in (("full quality", lambda a: a), ("phone", phone)):
            rng, scores, exact = random.Random(7), [], []
            for i in range(24):
                people = rng.sample(sorted(speakers), (2, 2, 3, 4)[i % 4])
                audio, truth = conversation(rng, speakers, people, **shape)
                score, found = accuracy(label(change(audio), use_turns, by_word), truth)
                scores.append(score)
                exact.append(found == len(people))
            print(f"{style}, {quality}: {np.mean(scores):.1%} of speaking time labelled right; "
                  f"the right number of people in {np.mean(exact):.0%} of conversations", flush=True)


if __name__ == "__main__":
    main()
