"""Telling voices apart: a voiceprint for each stretch of speech (NVIDIA's TitaNet small, via sherpa-onnx),
matched against the voices heard so far in the transcript. A close enough match is the same person;
otherwise it's someone new. When people reply without pausing, one stretch holds both of them: turns()
finds where the voice changes within it, from voiceprints of short overlapping slices, so each part gets its
own voice. Once two voices have been heard for a while, by_word() does better: it asks which of them each word
sounds like, so a "yeah" or a quick answer in the middle of someone's turn goes to whoever said it. A voice
found from a few words that turns out to sound like another becomes it (merge()). scripts/bench_voices.py
measures how well this works.

Remembering voices is opt-in (data/voices.json): once on, a voice you name in a transcript is remembered,
on this computer only, and named automatically in later transcripts. Turning it off forgets them all."""
import threading
from datetime import datetime

import numpy as np

from . import DATA, ROOT, store

MODEL = ROOT / "models/titanet_small.onnx"
SETTINGS = DATA / "voices.json"
SAME = {"wide": 0.42, "narrow": 0.6}  # how similar two voiceprints must be to be the same voice; phone audio
# (nothing above 3.4 kHz) makes everyone sound more alike, so it needs a closer match
REMEMBERED = 0.55  # a remembered voice: a closer match, as a wrong name is worse than "Speaker 3"
SHORT = 2.0  # seconds: a part this short is too little to tell a new voice by; it goes to the closest one
SLICE, STEP = 1.5, 0.5  # seconds: the slices turns() compares, and how far apart they start
CHANGE = {"wide": 0.45, "narrow": 0.6}  # the voice changes where before and after are less similar than this
KNOWN = 15.0  # seconds of a voice heard, for words to be told apart by it (by_word)
WINDOW, HOP = 0.8, 0.2  # seconds: by_word's windows, and how far apart they start
BRIEF = 0.7  # seconds: a run of a word or two shorter than this is another voice only if it's a sentence of its own
MERGE = {"wide": 0.5, "narrow": 0.7}  # a voice heard less than KNOWN seconds this like another (all their parts) is it
SHORT_COUNTS = 0.3  # how much a short part counts towards its voice's sound, for each second of it
REGROUP = 2  # times every part is given again to the voice it's closest to, after each new one
_ex, _lock = None, threading.Lock()


def available():
    return MODEL.exists()


def voiceprint(samples):
    """samples: 16 kHz float32. A unit vector; voiceprints of the same voice point the same way."""
    global _ex
    import sherpa_onnx
    with _lock:
        if not _ex:
            _ex = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(MODEL), num_threads=2))
        stream = _ex.create_stream()
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        v = np.array(_ex.compute(stream), np.float32)
    if not v.size:  # too short to tell (a few ms): like nobody
        return np.zeros(_ex.dim, np.float32)
    return v / (np.linalg.norm(v) or 1)


def turns(samples, narrow):
    """[(start, end)] in seconds: the parts of a stretch spoken by one voice each (the whole of it, mostly)."""
    seconds = len(samples) / 16000
    if seconds < 2 * SLICE:
        return [(0.0, seconds)]
    starts = np.arange(0, seconds - SLICE + 1e-6, STEP)
    prints = np.array([voiceprint(samples[int(t * 16000):int((t + SLICE) * 16000)]) for t in starts])

    apart = round(SLICE / STEP)  # slices this many apart don't overlap

    def split(a, b):  # slices a..b-1; returns the cut points (seconds), each with a slice or more either side
        best, at = 1.0, None
        for k in range(a + apart, b):  # cut where slice k starts: before it, the slices that end by then
            before, after = prints[a:k - apart + 1].sum(0), prints[k:b].sum(0)
            similar = float(before @ after) / float(np.linalg.norm(before) * np.linalg.norm(after))
            if similar < best:
                best, at = similar, k
        if at is None or best >= CHANGE["narrow" if narrow else "wide"]:
            return []
        return split(a, at - apart + 1) + [float(starts[at])] + split(at, b)  # left: slices ending by the cut

    def exact(cut):  # to the tenth of a second: where the slice before and the slice after differ most
        near = [c for c in np.arange(cut - STEP, cut + STEP + 1e-6, 0.1) if SLICE <= c <= seconds - SLICE] or [cut]
        def similar(c):
            return float(voiceprint(samples[int((c - SLICE) * 16000):int(c * 16000)]) @
                         voiceprint(samples[int(c * 16000):int((c + SLICE) * 16000)]))
        return float(min(near, key=similar))

    cuts = [exact(c) for c in split(0, len(starts))]
    edges = [0.0, *cuts, seconds]
    return list(zip(edges, edges[1:]))


def by_word(samples, words, known, narrow=False):
    """[(start, end, voiceprint, voice)] in seconds: the parts of a stretch spoken by one voice each, told apart a word
    at a time by which of the known voices ({voice: unit vector}, two or more, each heard KNOWN seconds or more) it
    sounds most like, in short windows around it; voice is None if it's long enough to tell (SHORT) and like none
    of them (SAME): someone new, for Voices to find. Catches a "yeah" or a quick reply between someone's sentences,
    which turns() (comparing 1.5 s slices, with no idea who's who) can't. A run of a word or two that isn't a
    sentence of its own (BRIEF) stays with the voice around it: one word's window often hears its neighbours."""
    seconds = len(samples) / 16000
    if not words or seconds < WINDOW:  # (it's whoever it sounds like as a whole)
        return [(0.0, seconds, voiceprint(samples), None)]
    ids = list(known)
    centres = np.stack([known[v] for v in ids])
    whole = voiceprint(samples)
    if seconds >= SHORT and float((centres @ whole).max()) < SAME["narrow" if narrow else "wide"]:
        return [(0.0, seconds, whole, None)]
    mids = np.arange(WINDOW / 2, max(seconds - WINDOW / 2, WINDOW / 2) + 1e-6, HOP)
    prints = np.array([voiceprint(samples[int((m - WINDOW / 2) * 16000):int((m + WINDOW / 2) * 16000)]) for m in mids])
    similar = prints @ centres.T
    starts = [t for t, _ in words]
    ends = starts[1:] + [seconds]
    who = []
    for t, e in zip(starts, ends):
        mid = (t + min(e, t + 0.6)) / 2  # (a word's end isn't given: the next one's start, or 0.6 s on at most)
        near = np.abs(mids - mid) <= max(WINDOW / 2, HOP)
        who.append(int((similar[near].mean(0) if near.any() else similar[np.argmin(np.abs(mids - mid))]).argmax()))

    ends_sentence = lambda w: w.rstrip().endswith((".", "?", "!"))
    changed = True
    while changed:  # a brief run that isn't a sentence of its own joins the voice before it (or after, first)
        changed = False
        runs = [[who[0], 0, 1]]
        for i in range(1, len(who)):
            if who[i] == runs[-1][0]:
                runs[-1][2] = i + 1
            else:
                runs.append([who[i], i, i + 1])
        for k, (_, a, b) in enumerate(runs):
            if len(runs) == 1:
                break
            brief = b - a <= 2 or ends[b - 1] - starts[a] < BRIEF
            sentence = ((a == 0 or ends_sentence(words[a - 1][1]))
                        and (b == len(words) or ends_sentence(words[b - 1][1])))
            if brief and not sentence:
                other = runs[k - 1][0] if k > 0 else runs[k + 1][0]
                for i in range(a, b):
                    who[i] = other
                changed = True
                break

    edges, out = [0], []
    for i in range(1, len(who)):
        if who[i] != who[i - 1]:  # a change of voice: at the end of a sentence, if one's within two words of it
            ends = [j for j in range(max(edges[-1] + 1, i - 2), min(len(who), i + 3)) if ends_sentence(words[j - 1][1])]
            edges.append(min(ends, key=lambda j: abs(j - i), default=i))
    edges = sorted(set(edges))
    voice = []  # each part's: most of its words'
    for k, i in enumerate(edges):
        theirs = who[i:edges[k + 1] if k + 1 < len(edges) else len(who)]
        voice.append(max(set(theirs), key=theirs.count))
    edges = [i for k, i in enumerate(edges) if k == 0 or voice[k] != voice[k - 1]]  # (two the same now: one)
    voice = [v for k, v in enumerate(voice) if k == 0 or v != voice[k - 1]]
    for k, i in enumerate(edges):
        a = 0.0 if k == 0 else starts[i] - 0.01  # just before the word that starts the part
        b = seconds if k == len(edges) - 1 else starts[edges[k + 1]] - 0.01
        inside = (mids >= a) & (mids <= b)
        vector = whole if len(edges) == 1 else \
            voiceprint(samples[int(a * 16000):int(b * 16000)]) if b - a >= SHORT else \
            (prints[inside].mean(0) if inside.any() else prints[np.argmin(np.abs(mids - (a + b) / 2))])
        out.append((a, b, vector / (float(np.linalg.norm(vector)) or 1), ids[voice[k]]))
    return out


def band(samples):
    """(power above 4 kHz, all the power) of samples."""
    power = np.abs(np.fft.rfft(samples)) ** 2
    return float(power[len(power) // 2:].sum()), float(power.sum())


def narrowband(samples=None, power=None):
    """Whether this sounds like a phone line: next to no sound above 4 kHz. Decide it for a whole call (power:
    band()s added up), not stretch by stretch: a short "uh" has next to none either, on any line."""
    high, total = band(samples) if power is None else power
    return high < 0.0005 * (total or 1)


class Voices:
    """The voices in one transcript. Each part of a stretch heard is given to the voice it's closest to, or
    (if it's long enough to tell, and close to none) to a new voice; then every part heard so far is given
    again to the voice it's now closest to, a couple of times over, as each voice's sound becomes clearer
    with more of it heard (so a voice found early on from a little speech doesn't split one person in two).
    A voice has a name (None until named, unless it was a remembered voice); else it's "Speaker N", N for the
    order the voices first spoke in, named or not (so naming one doesn't change the others' numbers), apart from
    those recognised as remembered voices (which never had a number)."""

    def __init__(self, remembered=()):
        self.prints, self.seconds, self.of = [], [], []  # each part's voiceprint, length and voice
        self.told = []  # whether each part's voice was told word by word (by_word), so stays (see regroup)
        self.names, self.next_id, self.narrow, self.recognised = {}, 0, False, set()
        self.known = [(name, np.asarray(v, np.float32)) for name, v in remembered]

    def voice(self, vector, seconds, narrow, likely=None):
        """Add a part heard; returns its id (its voice can change as more is heard: see label()). likely: the voice
        by_word told it was, word by word: a short part's is (too short to tell by its voiceprint as a whole)."""
        centres = self.centres()
        best, similar = max(((v, float(vector @ c)) for v, c in centres.items()), key=lambda t: t[1],
                            default=(None, -1.0))
        told = likely in centres and seconds < SHORT
        if told:
            best, similar = likely, 1.0
        self.told.append(told)
        self.narrow = narrow
        self.prints.append(np.asarray(vector, np.float32))
        self.seconds.append(seconds)
        if best is not None and (similar >= SAME["narrow" if narrow else "wide"] or seconds < SHORT):
            self.of.append(best)
        else:
            self.of.append(self.next_id)
            name = self.recognise(vector)
            if name:
                self.names[self.next_id] = name
                self.recognised.add(self.next_id)
            self.next_id += 1
        self.regroup()
        return len(self.of) - 1

    def weights(self):
        """How much each part counts towards its voice's sound: how long it is, but a short part (too little to
        tell a voice by, given to whichever it's closest to) next to nothing, so that two people's first few
        words given to one voice don't make a voice that sounds like both of them."""
        seconds = np.array(self.seconds)
        return np.where(seconds >= SHORT, seconds, SHORT_COUNTS * seconds)

    def centres(self):
        """{voice: unit vector}: the average of its parts' voiceprints, weighted (weights())."""
        total = {}
        for v, p, w in zip(self.of, self.prints, self.weights()):
            total[v] = total.get(v, 0) + p * w
        return {v: t / (float(np.linalg.norm(t)) or 1) for v, t in total.items()}

    def regroup(self):
        """Give every part to the voice it's closest to: its own as it would be without it, or another. A part
        that is a voice on its own goes only if it's the same voice (SAME) as another."""
        prints, seconds = np.array(self.prints), self.weights()
        for _ in range(REGROUP):
            ids = list(dict.fromkeys(self.of))
            of = np.array([ids.index(v) for v in self.of])
            totals = np.array([(prints[of == k] * seconds[of == k, None]).sum(0) for k in range(len(ids))])
            for i in range(len(prints)):
                if self.told[i]:  # by_word compared its words with the voices: better than its voiceprint as a whole
                    continue
                own = totals[of[i]] - prints[i] * seconds[i]  # its voice, without it
                alone = float(np.linalg.norm(own)) < 1e-6
                norms = np.linalg.norm(totals, axis=1)
                similar = (totals @ prints[i]) / np.where(norms > 0, norms, 1)
                similar[of[i]] = -1.0 if alone else float(own @ prints[i]) / float(np.linalg.norm(own))
                best = int(similar.argmax())
                if best != of[i] and not (alone and similar[best] < SAME["narrow" if self.narrow else "wide"]):
                    totals[of[i]], totals[best] = own, totals[best] + prints[i] * seconds[i]
                    of[i] = best
            self.of = [ids[k] for k in of]
        self.merge()

    def merge(self):
        """Make a voice heard only a little (less than KNOWN seconds) that sounds like another overall (MERGE)
        part of it: a voice found from a few words unlike the rest of someone's can keep a few more of theirs,
        each a little closer to it than to anyone (regroup() moves parts one at a time). Two people each heard
        for a while are left apart, however alike (two voices on one line can be). A named voice stays."""
        while True:
            centres, heard = self.centres(), {}
            for v, s in zip(self.of, self.seconds):
                heard[v] = heard.get(v, 0.0) + s
            pairs = sorted(((float(centres[a] @ centres[b]), a, b) for a in centres for b in centres
                            if a != b and heard[a] < KNOWN and a not in self.names), reverse=True)
            if not pairs or pairs[0][0] < MERGE["narrow" if self.narrow else "wide"]:
                return
            _, drop, keep = pairs[0]
            self.of = [keep if v == drop else v for v in self.of]

    def recognise(self, vector):
        """The remembered voice this is, if any (and not already in this transcript)."""
        taken = set(self.names.values())
        matches = [(float(vector @ v), name) for name, v in self.known if name not in taken]
        similar, name = max(matches, default=(0, None))
        return name if similar >= REMEMBERED else None

    def label(self, part):
        """What the voice of this part is called."""
        vid = self.of[part]
        numbered = [v for v in dict.fromkeys(self.of) if v not in self.recognised]
        return self.names.get(vid) or f"Speaker {numbered.index(vid) + 1}"

    def find(self, label):
        """The voice shown as label."""
        return next((self.of[i] for i in range(len(self.of)) if self.label(i) == label), None)

    def rename(self, vid, name):
        """Name a voice. Naming it the same as another voice in this transcript makes them one voice."""
        other = self.find(name)
        if other is not None and other != vid:
            self.of = [other if v == vid else v for v in self.of]
            self.names.pop(vid, None)
            return other
        self.names[vid] = name
        return vid

    def vector(self, vid):
        return self.centres()[vid]

    def told_apart(self, at_least=KNOWN):
        """{voice: unit vector} of the voices heard for at_least seconds (enough to tell words apart by)."""
        heard = {}
        for v, s in zip(self.of, self.seconds):
            heard[v] = heard.get(v, 0.0) + s
        return {v: c for v, c in self.centres().items() if heard.get(v, 0.0) >= at_least}

    def labelled(self):
        """{label: voiceprint} of every voice in this transcript."""
        centres = self.centres()
        return {self.label(self.of.index(v)): centres[v].tolist() for v in centres}


# --- remembered voices (opt-in) ---
def settings():
    return {"remember": False, "voices": [], **store.read_json(SETTINGS, {})}


def _save(s):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    store.write_json(SETTINGS, s)


def remembering():
    return settings()["remember"]


def remembered():
    """[(name, voiceprint)] of the remembered voices, if remembering is on."""
    s = settings()
    return [(v["name"], v["vector"]) for v in s["voices"]] if s["remember"] else []


def set_remembering(on):
    """Turning it off forgets every remembered voice."""
    s = settings()
    s["remember"] = on
    if not on:
        s["voices"] = []
    _save(s)


def remember(name, vector):
    """Remember (or update) the voice called name, if remembering is on."""
    s = settings()
    if not s["remember"]:
        return
    s["voices"] = [v for v in s["voices"] if v["name"] != name] + [
        {"name": name, "vector": [round(x, 5) for x in vector], "t": datetime.now().isoformat(timespec="seconds")}]
    _save(s)


def forget(name):
    s = settings()
    s["voices"] = [v for v in s["voices"] if v["name"] != name]
    _save(s)

