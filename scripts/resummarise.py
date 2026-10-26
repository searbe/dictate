"""Write a saved transcript's final summary again, from its paragraphs, as transcribe mode's final pass would (a
long one a slice at a time, the slices' summaries merged): e.g. after the summary was cut off, or the prompt
changed. Replaces its summary (and the Summary section of its Markdown); the old summary is kept beside it as
"<name> summary.json.old".

Usage: python scripts/resummarise.py "data/transcripts/2026-10-26 07.30.30.md" [...]
Uses the larger model on the GPU if it's free (as Dictate does), in a llama-server of its own."""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dictate

dictate.bootstrap()
from dictate import llm, store, summary, transcript


def resummarise(path):
    item = transcript.read(path)
    # (a saved transcript has paragraphs, not stretches: one line each, in order, by when they started)
    lines = [(at + i * 1e-6, who, text) for i, (at, (_, who, text))
             in enumerate(zip(transcript.offsets(item), item["paragraphs"]))]
    t = time.monotonic()
    s = summary.Summary()
    reply, slices = s.ask_final(lines, transcript.read_topics(path))
    if not s.take(reply, lines, final=True, slices=slices):
        raise SystemExit(f"{path.name}: the model's answer isn't a summary: {reply[:200]}")
    old = transcript.summary_file(path)
    if old.exists():
        old.replace(old.with_name(old.name + ".old"))
    store.write_json(old, s.data())
    text = path.read_text()
    section = re.compile(r"\n## Summary\n.*?(?=\n## )", re.S)
    new = summary.markdown(s.text).rstrip("\n")
    text = section.sub(lambda _: new, text, count=1) if section.search(text) else text
    store.write_text(path, text)
    words = sum(len(t.split()) for _, _, t in lines)
    print(f"{path.name}: {words} words, {len(slices)} slices, {len(s.text.split())}-word summary "
          f"in {time.monotonic() - t:.0f} s")


if __name__ == "__main__":
    llm.server.keep(True)  # (as transcribe mode does: not unloaded after IDLE seconds, mid-request on the CPU)
    try:
        for arg in sys.argv[1:]:
            resummarise(Path(arg).resolve())
    finally:
        llm.server.stop()
