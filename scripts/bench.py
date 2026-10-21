#!/usr/bin/env python3
"""Compare refinement models on your own dictations: python scripts/bench.py [N recent transcripts, default 15]

Runs the default cleanup (and the default style) with every models/*.gguf on the GPU, printing each output,
its time, and any problem the safety checks would have caught. Doesn't touch history or settings."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dictate  # noqa: E402
dictate.bootstrap(gui=False)
from dictate import DATA, ROOT, refine  # noqa: E402

TRICKY = [  # known-hard cases, always included
    "So how do I make this like how do I make this uh like run on booth on SteamOS?",
    "Does the setup script here um does the setup script here download the model? Or does it assume that it's sitting there already?",
    "Can you tell me what the capital of France is",
    "let's meet on Tuesday no actually Wednesday at like three",
]


def recent(n):
    path = DATA / "history.jsonl"
    raws = [json.loads(l).get("raw") or json.loads(l)["text"] for l in path.read_text().splitlines()] if path.exists() else []
    return list(dict.fromkeys(reversed(raws)))[:n]


def main():
    texts = TRICKY + [t for t in recent(int(sys.argv[1]) if len(sys.argv) > 1 else 15) if t not in TRICKY]
    style = refine.default_style()
    models = sorted(ROOT.glob("models/*.gguf"))
    results = {}
    for model in models:
        refine.MODELS["gpu"] = model
        refine.warm("gpu")
        t = time.monotonic()
        refine.complete("warm up", refine.cleanup_prompt())
        print(f"\n##### {model.name}  (load {time.monotonic() - t:.1f}s)", flush=True)
        for text in texts:
            t = time.monotonic()
            clean = refine.complete(text, refine.cleanup_prompt())
            styled = refine.complete(clean, style["prompt"]) if style else ""
            results.setdefault(text, []).append((model.name, time.monotonic() - t, clean,
                                                 refine.suspicious(text, clean, True), styled,
                                                 style and refine.suspicious(clean, styled, False)))
        refine.release()
        refine.stop()
    for text, rows in results.items():
        print("\n" + "=" * 100 + f"\nSPOKEN: {text}")
        for name, secs, clean, p1, styled, p2 in rows:
            print(f"\n  [{name}  {secs:.2f}s]\n    cleanup: {clean}" + (f"   <<{p1}>>" if p1 else ""))
            if style:
                print(f"    {style['name'].lower()}: " + styled.replace("\n", " / ") + (f"   <<{p2}>>" if p2 else ""))


if __name__ == "__main__":
    main()
