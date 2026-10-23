"""Reading and writing Dictate's own files (settings, refinements, transcripts).

Every write goes to a temporary file first and then replaces the old one, so a crash or a full disk never
leaves a half-written file, and a reader (e.g. the Transcripts page, while a call is being saved) always sees
a whole one."""

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(path: Path, data: Any, indent: int | None = None) -> None:
    write_text(path, json.dumps(data, indent=indent))


def read_json(path: Path, default: Any = None) -> Any:
    """The file's contents, or default if it's missing or isn't valid JSON."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text()
    except OSError:
        return default


def prune(files: Iterable[Path], hours: float | None, keep: set[Path]) -> None:
    """Delete the files older than hours (None: keep them forever), except those in keep (e.g. being recorded)."""
    if hours is None:
        return
    cutoff = time.time() - hours * 3600
    for path in files:
        try:
            if path.stat().st_mtime < cutoff and path not in keep:
                path.unlink(missing_ok=True)
        except OSError:  # gone already
            continue
