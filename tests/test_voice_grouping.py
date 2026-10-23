"""How voices.Voices groups what it hears into people, on made-up voiceprints as alike as real ones from a
call: two parts of one person are about 0.57 alike, of two people about 0.23 (everyone shares the line's
sound), so a part can easily look more like someone else than like the person's own first few parts."""
import numpy as np
import pytest

from conftest import needs_models, sample_speech
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
        theirs = [(lab, s) for (_, s, w), lab in zip(parts, labels) if w == who]
        if max(sum(s for lab, s in theirs if lab == label) for label in set(labels)) < 0.9 * sum(s for _, s in theirs):
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


def test_a_part_told_apart_word_by_word_keeps_the_voice_it_was_given():
    """voices.by_word compares each word with the voices known so far; what it finds stands, even for a part
    that sounds a little more like someone else as a whole (a "yeah" heard over the other person's last word)."""
    found = voices.Voices()
    a, b = (np.eye(192, dtype=np.float32)[i] for i in (0, 1))
    first, second = found.voice(a, 5.0, False), found.voice(b, 5.0, False)
    mostly_b = (0.4 * a + 0.9 * b) / np.linalg.norm(0.4 * a + 0.9 * b)

    part = found.voice(mostly_b, 1.0, False, likely=found.of[first])

    assert found.label(part) == found.label(first) != found.label(second)


def test_a_long_part_unlike_the_voice_it_was_given_is_someone_new():
    found = voices.Voices()
    a, b, c = (np.eye(192, dtype=np.float32)[i] for i in (0, 1, 2))
    first, _ = found.voice(a, 5.0, False), found.voice(b, 5.0, False)

    part = found.voice(c, 6.0, False, likely=found.of[first])

    assert found.label(part) == "Speaker 3"


def drifting(starts, then):
    """Someone heard for 20 s, then a new voice from starts seconds of words 0.4 like theirs, then more words (then
    seconds each) that are closer to the new voice than to them but make it sound more like them (0.6 alike)."""
    found = voices.Voices()
    a, b = (np.eye(192, dtype=np.float32)[i] for i in (0, 1))
    first = [found.voice(a, 5.0, False) for _ in range(4)][0]
    found.voice(0.4 * a + np.sqrt(1 - 0.16) * b, starts, False)
    for _ in range(3):
        found.voice(0.6 * a + 0.8 * b, then, False)
    return found, first


def test_a_voice_from_a_few_words_that_turns_out_to_sound_like_another_becomes_it():
    """Someone's first few words can sound unlike the rest of what they say."""
    found, first = drifting(starts=2.5, then=2.5)  # 10 s in all

    assert {found.label(i) for i in range(len(found.of))} == {found.label(first)}


def test_two_people_each_heard_for_a_while_stay_apart_however_alike():
    found, first = drifting(starts=16.0, then=6.0)

    assert len({found.label(i) for i in range(len(found.of))}) == 2


@needs_models
@pytest.mark.models
@pytest.mark.parametrize("rate", [0.8, 1.2])
def test_a_quick_reply_between_someones_sentences_is_the_other_voices_with_the_real_models(tmp_path, rate):
    """One voice, then another's sentence and the first again, without a pause: once both are known, each
    word goes to whoever it sounds like (voices.by_word). The other voice is the sample slowed down or sped up."""
    import soundfile

    from dictate import stt
    stt.load()
    one = soundfile.read(str(sample_speech(tmp_path / "one.wav")), dtype="float32")[0]
    other = np.interp(np.arange(0, len(one), rate), np.arange(len(one)), one).astype(np.float32)
    reply = other[:int((next(t for t, w in stt.words(stt._recognise(other))[1:] if w.strip() == "Ask") - 0.05) * 16000)]
    known = {"one": voices.voiceprint(one), "other": voices.voiceprint(other)}
    stretch = np.concatenate([one, reply, one])
    words = stt.words(stt._recognise(stretch))

    parts = voices.by_word(stretch, words, known)

    said = [(who, "".join(w for t, w in words if a <= t < b).strip()) for a, b, _, who in parts]
    whole = "Ask not what your country can do for you. Ask what you can do for your country."
    assert said == [("one", whole), ("other", "Ask not what your country can do for you."), ("one", whole)]
