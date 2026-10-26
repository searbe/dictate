"""Dictate in Claude Code: the /meeting-notes skill (skills/meeting-notes), installed for all your sessions
(~/.claude/skills/meeting-notes), through which a session can ask for transcripts (sharing.py); and blocking
Claude Code from reading Dictate's data folder itself, so that's the only way it gets them.

The block is a deny rule in ~/.claude/settings.json (permissions.deny: Read of the data folder, which also stops
writing there). Claude Code applies it to its file tools and to the shell commands it recognises as reading a
file (cat, head, tail, sed, redirections...), from the next request, in every session; not to a program that opens
the files itself (a Python script): only its sandbox would stop that (Claude Code's docs, permissions). It's on
unless you turn it off (Settings: e.g. while developing Dictate with Claude Code), and installing the skill turns
it on. Only Dictate's own rules are added or removed: nothing else in the file is changed."""
import json
import shutil
from pathlib import Path

from . import DATA, ROOT, store

SKILL = ROOT / "skills" / "meeting-notes" / "SKILL.md"
SCRIPT = ROOT / "scripts" / "meeting_notes.py"


def settings_file():
    return Path.home() / ".claude" / "settings.json"


def skill_dir():
    return Path.home() / ".claude" / "skills" / "meeting-notes"


def rules(data=DATA):
    """The deny rules that block reading data (and writing there): "//" makes the path absolute."""
    return [f"Read(/{Path(data).resolve()}/**)"]


def _settings():
    """~/.claude/settings.json, or {} if there isn't one. Raises ValueError if it isn't JSON: it's not ours to
    overwrite."""
    try:
        text = settings_file().read_text()
    except FileNotFoundError:
        return {}
    found = json.loads(text) if text.strip() else {}
    if not isinstance(found, dict):
        raise ValueError(f"{settings_file()} isn't a JSON object")
    return found


def blocked():
    """Whether Claude Code is blocked from reading Dictate's data folder (all of Dictate's rules are there)."""
    try:
        deny = _settings().get("permissions", {}).get("deny", [])
    except (OSError, ValueError, AttributeError):
        return False
    return all(r in deny for r in rules())


def set_blocked(on):
    """Add Dictate's deny rules to ~/.claude/settings.json (on), or take them out, leaving everything else as it
    was. Raises ValueError (the file isn't JSON) or OSError."""
    found = _settings()
    permissions = found.setdefault("permissions", {})
    deny = [r for r in permissions.get("deny", []) if r not in rules()]
    permissions["deny"] = deny + rules() if on else deny
    if not permissions["deny"]:
        del permissions["deny"]
    if not permissions:
        del found["permissions"]
    settings_file().parent.mkdir(parents=True, exist_ok=True)
    store.write_text(settings_file(), json.dumps(found, indent=2) + "\n")


def skill_installed():
    return (skill_dir() / "SKILL.md").exists()


def install_skill():
    """Install /meeting-notes for every Claude Code session (pointing at this copy of Dictate's script), and
    block reading Dictate's data folder."""
    skill_dir().mkdir(parents=True, exist_ok=True)
    store.write_text(skill_dir() / "SKILL.md", SKILL.read_text().replace("{SCRIPT}", str(SCRIPT)))
    set_blocked(True)


def remove_skill():
    """Take /meeting-notes out of Claude Code (the block stays as it is: it's turned off on its own)."""
    shutil.rmtree(skill_dir(), ignore_errors=True)
