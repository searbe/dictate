"""The built-in prompts for the local model, one text file each, kept apart from the code that uses them.

Cleanup, the default refinements and the live summary's prompt are only where the user's own copies start
from: theirs are kept in DATA and edited on the Refinements page."""

from functools import cache
from pathlib import Path

FOLDER = Path(__file__).parent


@cache
def load(name: str) -> str:
    """The text of prompts/<name>.txt, exactly as it is in the file."""
    return (FOLDER / f"{name}.txt").read_text()
