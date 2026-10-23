"""What the local model does to a dictation before it's pasted: cleanup (always first), then a refinement.

Each is a pass through the model (llm.py) under the user's prompt (refinements.py), behind GUARD so a message
is refined rather than answered. A result that looks wrong (suspicious()) is thrown away, and the text is used
as it was: a dictation is never lost to the model."""

import difflib
import logging
import re

from . import llm, prompts, refinements
from .refinements import Refinement

log = logging.getLogger(__name__)

GUARD = prompts.load("guard")


def cleanup(text: str, app: str = "") -> str:
    """The default cleanup pass, always applied first. app is the focused window, for context."""
    return _run(text, cleanup_prompt(), strict=True, app=app)


def cleanup_prompt() -> str:
    """The user's cleanup prompt, with their vocabulary."""
    prompt = refinements.load()["cleanup"]
    vocab = [w.strip() for w in refinements.load_vocab().splitlines() if w.strip()]
    if vocab:
        prompt += ("\n\nNames and terms the speaker uses. Prefer these spellings, and fix similar-sounding "
                   "mis-hearings of them:\n" + "\n".join(f"- {w}" for w in vocab))
    return prompt


def apply(text: str, refinement: Refinement, app: str = "") -> str:
    """A refinement, applied to already cleaned-up text."""
    return _run(text, refinement["prompt"], strict=False, app=app)


def _run(text: str, prompt: str, strict: bool, app: str = "") -> str:
    """Refine text with prompt; falls back to text on any problem."""
    try:
        out = complete(text, prompt, app)
    except (OSError, KeyError, ValueError) as err:
        log.warning("refining failed: %s", err)
        return text
    problem = suspicious(text, out, strict)
    if problem:
        log.warning("output rejected (%s), keeping input: %s", problem, out)
        return text
    return out


def complete(text: str, prompt: str, app: str = "") -> str:
    """The raw model output for text under prompt (waits for the model to finish loading)."""
    if app:
        prompt += f"\n\n(Context: the message is being typed into this window: {app})"
    return llm.chat(GUARD + prompt, f"<transcript>\n{text}\n</transcript>", max_tokens=len(text) + 200)


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def suspicious(text: str, out: str, strict: bool) -> str:
    """Why out looks like the model rewrote, cut or answered the message instead of refining it, or ""."""
    if not out:
        return "empty"
    if "?" in text and "?" not in out:
        return "lost the questions"
    if len(out) < len(text) / 2:
        return "cut by over half"
    if "[" in out and "[" not in text:
        return "added a placeholder"
    kept = set(_words(out))
    if not strict and sum(w in kept for w in _words(text)) < 0.6 * len(_words(text)):
        return "reworded too much"  # refinements reshape text, but should keep most of the speaker's words
    # compare words, not characters: on long texts the character matcher's autojunk makes near-copies score low
    alike = difflib.SequenceMatcher(None, text.lower().split(), out.lower().split(), autojunk=False).ratio
    if strict and alike() < 0.4:
        return "changed too much for cleanup"
    return ""
