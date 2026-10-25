#!/usr/bin/env python3
"""How well transcribe mode does on real calls with human transcripts:
python scripts/bench_calls.py [ids...] [--minutes N] [--label NAME]

Earnings calls from Earnings-21 (Rev, CC BY-SA 4.0: https://github.com/revdotcom/speech-datasets): a company's
presenters, then analysts' questions over phone lines, as low-bitrate MP3. Each is played through transcribe mode
as if from the speakers (scripts/replay_call.py) and scored against its transcript (nlp/<id>.nlp, with who said
each word) and who spoke when (rttms/<id>.rttm), from data/bench/earnings21 (media/<id>.mp3 and those two):
- WER: words wrong (substituted, left out or added) per word said, ignoring case and punctuation;
  formatted, with them (a word with the wrong capital, or the wrong punctuation after it, is wrong);
- speakers: of the time one person was speaking, the share given to the voice that is theirs (each person
  matched to the voice given most of their time, one voice each), DER (diarisation error: time missed, given
  to nobody's voice, or to the wrong one, per second spoken), and how many voices were found;
- by speaker: WER with each person's words compared with their voice's (so words given to the wrong voice
  count as wrong).
--minutes N scores only the first N minutes' speakers (WER needs all of it: the transcript has no times).
Results are added to data/bench/results.jsonl, with --label's name."""
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from replay_call import replay  # (sets Dictate up, as a script)

from dictate import DATA, stt, transcript

BENCH = DATA / "bench"
CALLS = BENCH / "earnings21"
DEFAULT = ["4394084", "4387383", "4387865", "4385939"]  # short with many turns, one at 11 kHz, Hershey's 19 people
FRAME = 0.1  # seconds: speakers are scored in tenths of a second
NOT_PEOPLE = {"4387383": {"3", "5"}}  # "speakers" that are the hold line's recording over music: not scored


def audio(path, minutes=None):
    cut = ["-t", str(minutes * 60)] if minutes else []
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), *cut, "-ac", "1", "-ar", str(stt.RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def reference(path):
    """[(speaker, word as written, with its punctuation)] from an Earnings-21 .nlp file."""
    out = []
    for line in path.read_text().splitlines()[1:]:
        token, speaker, _, _, punctuation, *_ = line.split("|")
        if speaker not in NOT_PEOPLE.get(path.stem, ()):
            out.append((speaker, token + punctuation))
    return out


def turns(path):
    """[(start, end, speaker)] from an RTTM file."""
    out = []
    for line in path.read_text().splitlines():
        f = line.split()
        if f[7] not in NOT_PEOPLE.get(path.stem, ()):
            out.append((float(f[3]), float(f[3]) + float(f[4]), f[7]))
    return out


def plain(words):
    return [w for w in re.findall(r"[\w'%]+", " ".join(words).lower().replace("-", " "))]


def formatted(words):
    return " ".join(words).replace("-", " ").split()


def errors(ref, hyp):
    """Words substituted, deleted or inserted to make hyp of ref (Levenshtein over words, a row at a time)."""
    ids = {w: i for i, w in enumerate(dict.fromkeys(ref + hyp))}
    r, h = np.array([ids[w] for w in ref]), np.array([ids[w] for w in hyp])
    row = np.arange(len(h) + 1)
    for k, w in enumerate(r, 1):
        new = np.empty_like(row)
        new[0] = k
        new[1:] = np.minimum(row[1:] + 1, row[:-1] + (h != w))  # deleted, or substituted (free if the same)
        row = np.minimum.accumulate(new - np.arange(len(new))) + np.arange(len(new))  # inserted
    return int(row[-1])


def frames(segments, n):
    """[set of labels speaking] for each FRAME up to n frames."""
    out = [set() for _ in range(n)]
    for a, b, who in segments:
        for i in range(int(a / FRAME), min(n, int(b / FRAME))):
            out[i].add(who)
    return out


def matching(ref, hyp):
    """{person: voice}, one voice each, matched greedily by the time they share."""
    shared = {}
    for r, h in zip(ref, hyp):
        for p in r:
            for v in h:
                shared[p, v] = shared.get((p, v), 0) + 1
    out, used = {}, set()
    for (p, v), _ in sorted(shared.items(), key=lambda kv: -kv[1]):
        if p not in out and v not in used:
            out[p] = v
            used.add(v)
    return out


def score(call, s, seconds, whole):
    hyp = [(start, end, s.name(who, vid), text) for who, start, end, text, vid in s.kept() if who == "them"]
    n = int(seconds / FRAME)
    ref_frames, hyp_frames = frames(turns(CALLS / "rttms" / f"{call}.rttm"), n), frames(
        [(a, b, v) for a, b, v, _ in hyp], n)
    hyp_frames = [h and {sorted(h)[-1]} for h in hyp_frames]  # (one voice at a time, as in the transcript)
    match = matching(ref_frames, hyp_frames)
    single = [(r, h) for r, h in zip(ref_frames, hyp_frames) if len(r) == 1]
    right = sum(1 for r, h in single if h and match.get(next(iter(r))) in h)
    spoken = sum(len(r) for r in ref_frames)
    missed = wrong = extra = 0
    for r, h in zip(ref_frames, hyp_frames):
        missed += max(0, len(r) - len(h))
        extra += max(0, len(h) - len(r))
        wrong += min(len(r), len(h)) - (1 if any(match.get(p) in h for p in r) else 0)
    out = {"call": call, "seconds": round(seconds), "people": len({p for r in ref_frames for p in r}),
           "voices": len({v for h in hyp_frames for v in h}), "speakers_right": right / max(1, len(single)),
           "der": (missed + extra + wrong) / max(1, spoken), "missed": missed / max(1, spoken),
           "extra": extra / max(1, spoken), "confused": wrong / max(1, spoken)}
    if not whole:  # (only part of it: the words can't be scored)
        return out
    ref = reference(CALLS / "nlp" / f"{call}.nlp")
    said = [w for _, w in ref]
    heard = " ".join(t for *_, t in hyp).split()
    out["wer"] = errors(plain(said), plain(heard)) / len(plain(said))
    out["formatted_wer"] = errors(formatted(said), formatted(heard)) / len(formatted(said))
    total = 0
    for person, voice in [(p, match.get(p)) for p in dict.fromkeys(p for p, _ in ref)]:
        theirs = plain(w for p, w in ref if p == person)
        given = plain(t for *_, v, t in hyp if v == voice) if voice else []
        total += errors(theirs, given)
    unmatched = set(v for *_, v, _ in hyp) - set(match.values())
    total += sum(len(plain(t for *_, v, t in hyp if v == u)) for u in unmatched)  # all inserted
    out["speaker_wer"] = total / len(plain(said))
    return out


def main():
    args, minutes, label = [], None, ""
    argv = iter(sys.argv[1:])
    for a in argv:
        if a == "--minutes":
            minutes = float(next(argv))
        elif a == "--label":
            label = next(argv)
        else:
            args.append(a)
    if not (CALLS / "media").is_dir():
        sys.exit(f"No calls in {CALLS}: see this script's docstring for where they come from.")
    results = []
    for call in args or DEFAULT:
        t0 = time.monotonic()
        them = audio(CALLS / "media" / f"{call}.mp3", minutes)
        stem = datetime(2026, 1, 1).strftime(transcript.STAMP)
        out = tempfile.mkstemp(suffix=".md")[1]
        s = replay(stem, them, np.zeros(stt.RATE, np.float32), out)
        r = score(call, s, len(them) / stt.RATE, whole=not minutes)
        r["took"] = round(time.monotonic() - t0)
        results.append(r)
        words = (f"WER {r['wer']:.1%}, formatted {r['formatted_wer']:.1%}, by speaker {r['speaker_wer']:.1%}; "
                 if "wer" in r else "")
        print(f"{call} ({r['seconds'] / 60:.0f} min, {r['took']} s): {words}speakers right "
              f"{r['speakers_right']:.1%}, DER {r['der']:.1%} (missed {r['missed']:.1%}, extra {r['extra']:.1%}, "
              f"confused {r['confused']:.1%}), {r['voices']} voices for {r['people']} people; {out}", flush=True)
    keys = [k for k in ("wer", "formatted_wer", "speaker_wer", "speakers_right", "der") if all(k in r for r in results)]
    weights = [r["seconds"] for r in results]
    mean = {k: float(np.average([r[k] for r in results], weights=weights)) for k in keys}
    print("all (by length): " + ", ".join(f"{k} {v:.1%}" for k, v in mean.items()))
    BENCH.mkdir(parents=True, exist_ok=True)
    with open(BENCH / "results.jsonl", "a") as f:
        f.write(json.dumps({"t": f"{datetime.now():%Y-%m-%dT%H:%M:%S}", "label": label, "minutes": minutes,
                            "mean": mean, "calls": results}) + "\n")


if __name__ == "__main__":
    main()
