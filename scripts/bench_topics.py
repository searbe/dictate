#!/usr/bin/env python3
"""How topics come out on real conversations: python scripts/bench_topics.py [transcript.md ...] [--cpu]

Replays saved transcripts (by default the three longest in data/transcripts/) as transcribe mode would hear
them: each paragraph cut into sentences, about its stretches, spread over its time; topics updated on the live
schedule (topics.EVERY, MOST, WORDS) and merged every topics.MERGE seconds and at the end, as a call is. Prints
each update's time and the topic now, then each topic with what was said on it and its lines, and what no topic
claimed. Nothing is saved. --cpu uses the smaller model, as when the graphics card is busy."""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dictate

dictate.bootstrap(gui=False)
from dictate import llm, topics, transcript


def stretches(path):
    """[(start, end, who, text)] in seconds from the first paragraph: its sentences, spread over each paragraph."""
    paragraphs = transcript.PARAGRAPH.findall(path.read_text())
    seconds = lambda clock: sum(int(x) * f for x, f in zip(clock.split(":"), (3600, 60, 1)))
    t0, out = seconds(paragraphs[0][0]), []
    for k, (clock, who, text) in enumerate(paragraphs):
        a = seconds(clock) - t0
        b = seconds(paragraphs[k + 1][0]) - t0 if k + 1 < len(paragraphs) else a + 5
        parts = [x for x in re.split(r"(?<=[.?!])\s+", text) if x]
        total, at = sum(map(len, parts)), a
        for x in parts:
            out.append((at, at + (b - a) * len(x) / total, who, x))
            at += (b - a) * len(x) / total
    return out


def replay(path):
    lines = stretches(path)
    print(f"\n=== {path.name}: {len(lines)} stretches", flush=True)
    found, sorted_upto, last, merged = topics.Topics(), 0, 0.0, 0.0
    for n in range(len(lines) + 1):
        now = lines[n][1] if n < len(lines) else float("inf")
        new = [(s, w, t) for s, e, w, t in lines[sorted_upto:n]]
        if new and (n == len(lines) or found.due(new, now - last)):
            took = time.time()
            found.update(new, [(s, w, t) for s, e, w, t in lines[:sorted_upto]])
            sorted_upto, last = n, now
            title = found.topics[found.now]["title"] if found.now is not None else None
            print(f"--- {min(now, lines[-1][1]) / 60:4.1f} min: {len(new):3} lines, "
                  f"{time.time() - took:4.1f} s; now: {title}", flush=True)
            if (n == len(lines) or now - merged >= topics.MERGE) and llm.server.mode == "gpu":
                found.merge()
                merged = now
    people = found.people([(s, w, t) for s, e, w, t in lines])
    for i, t in enumerate(found.topics):
        print(f"\n[{i}] {t['title']} ({', '.join(people[i])}): " + " / ".join(t["points"]))
        print("    lines:", " | ".join(text[:40] for s, e, w, text in lines if found.of.get(s) == i))
    print("\nno topic:", " | ".join(text[:30] for s, e, w, text in lines if s not in found.of))


def main():
    paths = [Path(a) for a in sys.argv[1:] if not a.startswith("--")] or \
        sorted(transcript.FOLDER.glob("*.md"), key=lambda p: -len(p.read_text()))[:3]
    llm.server.warm("cpu" if "--cpu" in sys.argv else None, hold=False)
    for path in paths:
        replay(path)
    llm.server.stop()


if __name__ == "__main__":
    main()
