"""Dictate's own files: saved whole or not at all, read back safely when missing or damaged, and old recordings
deleted when their time is up (but never one being recorded)."""
import os
import time

import pytest

from dictate import store


def test_a_save_replaces_the_file_whole_and_leaves_nothing_behind(tmp_path):
    path = tmp_path / "state.json"
    store.write_json(path, {"refine": True})
    store.write_json(path, {"refine": False})

    assert store.read_json(path) == {"refine": False}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_save_that_fails_leaves_the_old_file_as_it_was(tmp_path, monkeypatch):
    path = tmp_path / "refinements.json"
    store.write_json(path, {"cleanup": "old"})

    def full_disk(src, dst):
        raise OSError("No space left on device")
    monkeypatch.setattr(os, "replace", full_disk)
    with pytest.raises(OSError):
        store.write_json(path, {"cleanup": "new"})

    assert store.read_json(path) == {"cleanup": "old"}
    assert [p.name for p in tmp_path.iterdir()] == ["refinements.json"]


def test_a_missing_or_damaged_file_reads_as_the_default(tmp_path):
    (tmp_path / "damaged.json").write_text('{"refine": tr')

    assert store.read_json(tmp_path / "missing.json", {}) == {}
    assert store.read_json(tmp_path / "damaged.json", {}) == {}
    assert store.read_text(tmp_path / "missing.txt") == ""


def recordings(folder, *ages_in_hours):
    paths = []
    for i, hours in enumerate(ages_in_hours):
        path = folder / f"{i}.wav"
        path.write_bytes(b"")
        when = time.time() - hours * 3600
        os.utime(path, (when, when))
        paths.append(path)
    return paths


def test_recordings_older_than_their_setting_are_deleted(tmp_path):
    new, old = recordings(tmp_path, 1, 30)

    store.prune([new, old], 24, keep=set())

    assert new.exists() and not old.exists()


def test_the_recording_being_made_is_never_deleted(tmp_path):
    (recording,) = recordings(tmp_path, 30)

    store.prune([recording], 24, keep={recording})

    assert recording.exists()


def test_kept_forever_means_nothing_is_deleted(tmp_path):
    (old,) = recordings(tmp_path, 10_000)

    store.prune([old], None, keep=set())

    assert old.exists()
