"""Dictate's settings (state.json): where the capsule is, and the choices in its menu and on the Settings page.

The refinement choices (the default refinement, here and on another computer) are kept with the refinements
instead (refinements.py), and whether Dictate runs at startup is the operating system's (osio.py)."""

from pathlib import Path
from typing import Any

from . import DATA, store

FILE = DATA / "state.json"
KEEP_AUDIO = ((0, "Don't keep"), (1, "1 hour"), (3, "3 hours"), (12, "12 hours"), (24, "1 day"), (72, "3 days"),
              (168, "1 week"), (None, "Forever"))  # hours, for dictations' and calls' recordings; None: never deleted
REMOTE_MODES = (("type", "Type the text there"), ("ignore", "Ignore the hotkey"))  # when another computer has the keys
SAME = "same"  # the other computer's default refinement: the same as here
DEFAULTS = {
    "pos": [100, 100],  # the capsule's window, on screen
    "anchor": "left",  # which end of the capsule is its dot (it grows away from the nearer screen edge)
    "refine": True,  # cleanup and refinements; off pastes what was heard
    "remote_mode": "type",  # one of REMOTE_MODES
    "keep_audio_hours": 24,  # how long dictations' recordings are kept: one of KEEP_AUDIO
    "keep_call_hours": 168,  # and transcripts'
    "microphones": [],  # [name, description] of each microphone seen, in the order to prefer them
    "share_with_claude": False,  # Claude Code may ask for transcripts (you choose, each time): sharing.py
}


class Settings:
    """The settings, read once; update() changes some and saves them all."""

    def __init__(self, path: Path = FILE) -> None:
        self.path = path
        saved = store.read_json(path, {})
        self._values = {**DEFAULTS, **(saved if isinstance(saved, dict) else {})}

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def update(self, **changes: Any) -> None:
        self._values.update(changes)
        store.write_json(self.path, self._values)
