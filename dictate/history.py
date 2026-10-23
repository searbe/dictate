"""Every dictation, shown on the Dictations page: dictations.jsonl (a JSON line each, oldest first) and each
one's recording in AUDIO, kept for "keep_audio_hours" (settings.py)."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import DATA, store
from .activewin import Window

FILE = DATA / "dictations.jsonl"
AUDIO = DATA / "audio"


@dataclass
class Dictation:
    """One dictation, as it goes through the pipeline: recorded → heard (raw) → cleaned up → refined (text)."""
    window: Window  # where the text goes
    audio: str  # the recording's path
    raw: str = ""  # what was heard
    cleaned: str = ""  # after cleanup, before the refinement
    text: str = ""  # what's pasted
    cleanup: bool = False  # whether cleanup was applied
    refinement: str | None = None  # the refinement applied after cleanup, by name

    def entry(self, keep_audio: bool) -> dict:
        """Its line in dictations.jsonl. keep_audio: whether its recording is kept, for playing back."""
        entry = {"t": datetime.now().isoformat(timespec="seconds"), "text": self.text,
                 "app": "other computer" if self.window.remote else self.window.cls, "cleanup": self.cleanup}
        if self.window.title:
            entry["title"] = self.window.title  # what per-app refinements matched against
        if self.raw != self.text:
            entry["raw"] = self.raw
        if self.refinement:
            entry["refinement"] = self.refinement
            entry["cleaned"] = self.cleaned  # (so what the refinement changed can be seen, apart from cleanup)
        if keep_audio:
            entry["audio"] = Path(self.audio).name
        return entry


def add(entry: dict) -> None:
    with FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def lines() -> list[str]:
    """Every entry as it is in the file (a JSON line each), oldest first."""
    return store.read_text(FILE).splitlines()


def changed() -> int | None:
    """A stamp that changes whenever an entry is added or deleted (None: there are none yet)."""
    try:
        return FILE.stat().st_mtime_ns
    except OSError:
        return None


def remove(line: str) -> None:
    """Delete the entry that's this line of the file."""
    keep = lines()
    if line in keep:
        keep.remove(line)
        store.write_text(FILE, "".join(f"{kept}\n" for kept in keep))


def clear() -> None:
    """Delete every entry and every recording."""
    for wav in AUDIO.glob("*.wav"):  # (the recordings first: once the list is empty, they're gone)
        wav.unlink(missing_ok=True)
    store.write_text(FILE, "")

