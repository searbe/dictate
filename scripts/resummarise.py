"""Write a saved transcript's final summary again, from its paragraphs, as transcribe mode's final pass would (a
long one a slice at a time, the slices' summaries merged): e.g. after the summary was cut off, or the prompt
changed. Replaces its summary (and the Summary section of its Markdown); the old summary is kept beside it as
"<name> summary.json.old".

Usage: python scripts/resummarise.py "data/transcripts/2026-10-26 07.30.30.md" [...]
Uses the larger model on the GPU if it's free (as Dictate does), in a llama-server of its own."""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dictate

dictate.bootstrap()
from dictate import llm, transcript


def resummarise(path):
    old = transcript.summary_file(path)
    if old.exists():
        shutil.copy(old, old.with_name(old.name + ".old"))
    t = time.monotonic()
    if not transcript.final_summary(path):
        raise SystemExit(f"{path.name}: nothing to summarise")
    s = transcript.read_summary(path)
    print(f"{path.name}: {len(s.slices)} slices, {len(s.text.split())}-word summary in {time.monotonic() - t:.0f} s")


if __name__ == "__main__":
    llm.server.keep(True)  # (as transcribe mode does: not unloaded after IDLE seconds, mid-request on the CPU)
    try:
        for arg in sys.argv[1:]:
            resummarise(Path(arg).resolve())
    finally:
        llm.server.stop()
