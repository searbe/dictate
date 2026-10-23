"""The user's cleanup prompt, refinements and vocabulary, kept in DATA (edited on the Refinements page).

refinements.json holds {"cleanup": prompt, "refinements": [Refinement, ...], "remote_default": name}; it's
created from the built-in prompts (prompts/) on first use."""

import json
from typing import NotRequired, TypedDict

from . import DATA, prompts, store

FILE = DATA / "refinements.json"
VOCAB = DATA / "vocab.txt"  # one name/term per line, fed to cleanup
CLEANUP = prompts.load("cleanup")


class Refinement(TypedDict):
    name: str
    key: str  # its letter: Ctrl+Win with Alt and this picks it
    apps: str  # comma-separated words matched against the focused window, to use it there automatically
    prompt: str
    default: NotRequired[bool]  # applied when no app's refinement matches


def _builtin(name: str, key: str, apps: str, prompt: str) -> Refinement:
    return {"name": name, "key": key, "apps": apps, "prompt": prompts.load(f"refinement-{prompt}")}


DEFAULTS = [
    _builtin("Slack", "s", "slack", "slack"),
    _builtin("WhatsApp", "w", "whatsapp", "whatsapp"),
    _builtin("Email", "e", "gmail, outlook, thunderbird, proton mail", "email"),
    _builtin("AI agent", "a", "claude, chatgpt, codex, cursor, copilot, gemini", "ai-agent"),
]


def load() -> dict:
    """Everything in refinements.json (see the module's docstring), created with the defaults on first use."""
    if not FILE.exists():
        save({"cleanup": CLEANUP, "refinements": DEFAULTS})
    return json.loads(FILE.read_text())


def save(data: dict) -> None:
    store.write_json(FILE, data, indent=2)


def default(remote: bool = False) -> Refinement | None:
    """The refinement applied to a plain Ctrl+Win dictation (after cleanup), or None.
    remote: for text typed on another computer, which has its own default ("remote_default"):
    a refinement name, None for cleanup only, or absent for the same as here."""
    data = load()
    if remote and "remote_default" in data:
        return next((r for r in data["refinements"] if r["name"] == data["remote_default"]), None)
    return next((r for r in data["refinements"] if r.get("default")), None)


def set_default(name: str | None) -> None:
    data = load()
    for r in data["refinements"]:
        r["default"] = r["name"] == name
    save(data)


def set_remote_default(name: str | None, same: bool = False) -> None:
    """The other computer's default: name (None for cleanup only), or with same, whatever it is here."""
    data = load()
    if same:
        data.pop("remote_default", None)
    else:
        data["remote_default"] = name
    save(data)


def for_key(key: str) -> Refinement | None:
    return next((r for r in load()["refinements"] if r["key"] == key), None)


def for_app(app: str) -> Refinement | None:
    """The first refinement whose comma-separated "apps" keywords appear in the focused app's class/title."""
    app = app.lower()
    return next((r for r in load()["refinements"]
                 if any(k.strip() and k.strip().lower() in app for k in r.get("apps", "").split(","))), None)


def letters() -> set[str]:
    """The letters that pick a refinement."""
    return {r["key"] for r in load()["refinements"]}


def load_vocab() -> str:
    return store.read_text(VOCAB)


def save_vocab(text: str) -> None:
    store.write_text(VOCAB, text.strip() + "\n")
