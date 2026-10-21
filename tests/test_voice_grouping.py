"""How voices.Voices groups what it hears into people, on made-up voiceprints as alike as real ones from a
call: two parts of one person are about 0.57 alike, of two people about 0.23 (everyone shares the line's
sound), so a part can easily look more like someone else than like the person's own first few parts."""
import numpy as np
from dictate import voices


def call(people=3, parts=150, seed=0):
    """[(voiceprint, seconds, who)] of a made-up call."""
    rng = np.random.default_rng(seed)
    means = rng.standard_normal((people, 192))
    means /= np.linalg.norm(means, axis=1, keepdims=True)
    line = rng.standard_normal(192)
    line /= np.linalg.norm(line)
    out = []
    for _ in range(parts):
        who = int(rng.integers(people))
        v = 0.9 * line + means[who] + 0.08 * rng.standard_normal(192)
        out.append((v / np.linalg.norm(v), float(rng.uniform(0.5, 5)), who))
    return out


def heard(parts):
    found = voices.Voices()
    ids = [found.voice(v, s, False) for v, s, _ in parts]
    return [found.label(i) for i in ids]


def one_voice_each(parts, labels):
    """Whether there are as many voices as people, each person's speaking time almost all under one."""
    people = sorted(set(w for _, _, w in parts))
    for who in people:
        theirs = [(l, s) for (_, s, w), l in zip(parts, labels) if w == who]
        if max(sum(s for l, s in theirs if l == label) for label in set(labels)) < 0.9 * sum(s for _, s in theirs):
            return False
    return len(set(labels)) == len(people)


def test_each_person_on_a_call_is_one_voice():
    """On most calls: it can't be sure of everyone on every call (scripts/bench_voices.py measures how often
    it is, with real voices)."""
    calls = [call(seed=seed) for seed in range(10)]

    right = sum(one_voice_each(parts, heard(parts)) for parts in calls)

    assert right >= 7


def test_short_parts_never_make_a_new_person():
    parts = [(v, min(s, voices.SHORT - 0.1), w) for v, s, w in call()]
    parts[0] = (parts[0][0], 3.0, parts[0][2])  # someone has to be heard first

    assert len(set(heard(parts))) == 1


def test_a_voice_keeps_its_number_when_another_is_named():
    found = voices.Voices()
    a, b = (np.eye(192, dtype=np.float32)[i] for i in (0, 1))
    first, second = found.voice(a, 3.0, False), found.voice(b, 3.0, False)

    found.rename(found.find("Speaker 1"), "Sarah")

    assert (found.label(first), found.label(second)) == ("Sarah", "Speaker 2")
