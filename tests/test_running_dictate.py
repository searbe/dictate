"""Starting, stopping and the things that outlive a session: run at startup, one copy only, the quit log."""
import os, signal, socket, subprocess, sys, time
from pathlib import Path
import pytest
from conftest import ROOT, needs_session

VENV_PY = ROOT / ".venv/bin/python"


@needs_session
def test_quit_from_the_menu_exits_and_says_why_in_the_log(start):
    app = start(styles=[])

    app.send("menu", path=["Quit"])

    assert app.proc.wait(10) == 0
    assert any(l.endswith("quitting: Quit chosen from the menu") for l in app.logs)
    assert any(l.endswith("exited") for l in app.logs)


@needs_session
def test_being_stopped_by_the_system_exits_cleanly_and_says_why(start):
    app = start(styles=[])

    app.proc.send_signal(signal.SIGTERM)

    assert app.proc.wait(10) == 0
    assert any(l.endswith("quitting: got SIGTERM") for l in app.logs)


@needs_session
def test_quitting_mid_dictation_stops_the_microphone(start):
    app = start(styles=[])
    app.send("keys", down=["ctrl", "meta"])
    app.wait_for("recording")

    app.proc.send_signal(signal.SIGTERM)

    assert app.proc.wait(10) == 0
    assert app.happened("recording_stopped")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux records with pw-record")
@pytest.mark.parametrize("kind", ["dictation", "transcript"])
def test_a_recorder_never_outlives_dictate_even_if_it_crashes(tmp_path, kind):
    """pw-record is a program of its own: without this, a Dictate that crashed (or was killed) mid-recording
    would leave it recording the microphone, indefinitely. (A stand-in pw-record here: no microphone.)"""
    bin_dir, pid_file = tmp_path / "bin", tmp_path / "recorder.pid"
    bin_dir.mkdir()
    (bin_dir / "pw-record").write_text(f"#!/bin/sh\necho $$ > {pid_file}\nexec sleep 60\n")
    (bin_dir / "pw-record").chmod(0o755)
    start = (f"osio.Recorder().start({str(tmp_path / 'r.wav')!r})" if kind == "dictation" else
             f"osio.Recorder().start({str(tmp_path / 'r.ogg')!r}, on_audio=lambda chunk: None)")
    code = f"import sys, time; sys.path.insert(0, {str(ROOT)!r}); from dictate import osio; {start}; time.sleep(60)"
    dictate = subprocess.Popen([str(VENV_PY), "-c", code], env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    deadline = time.monotonic() + 10
    while not (pid_file.exists() and pid_file.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.05)
    recorder = int(pid_file.read_text())

    dictate.kill()  # SIGKILL: no chance to tidy up
    dictate.wait()

    deadline = time.monotonic() + 5
    while _running(recorder) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _running(recorder)


def _running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


@needs_session
def test_run_at_startup_adds_a_login_entry_that_starts_dictate_and_removes_it_again(start):
    app = start(styles=[])
    entry = app.home / ".config/autostart/dictate.desktop"

    app.send("menu", path=["Run at startup"])

    exec_line = next(l for l in entry.read_text().splitlines() if l.startswith("Exec="))
    python, script = [Path(p) for p in exec_line[5:].strip('"').split('" "')]
    assert python.exists() and script == ROOT / "dictate.py"
    icon = next(l for l in entry.read_text().splitlines() if l.startswith("Icon="))[5:]
    assert icon == str(ROOT / "dictate/icon.png") and Path(icon).exists()  # Dictate's own icon
    assert {"label": "Run at startup", "ticked": True} in app.send("menu_items")["items"]

    app.send("menu", path=["Run at startup"])
    assert not entry.exists()


def test_a_second_copy_refuses_to_start(tmp_path):
    """Two copies would both hear the hotkey and paste everything twice."""
    holder = socket.socket()
    try:
        holder.bind(("127.0.0.1", 47613))  # stands in for the first copy (unless a real Dictate holds it already)
    except OSError:
        pass
    try:
        result = subprocess.run([sys.executable, "-c", "import dictate; dictate.bootstrap(); from dictate import app; "
                                 "app.only_instance()"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                                env={**os.environ, "HOME": str(tmp_path), "DICTATE_DATA": str(tmp_path)})
    finally:
        holder.close()
    assert result.returncode == 1 and "Dictate is already running." in result.stderr


@pytest.mark.skipif(not VENV_PY.exists(), reason="no .venv: run the setup script")
def test_started_with_the_system_python_it_switches_to_its_own_environment(tmp_path):
    script = tmp_path / "launcher.py"  # like dictate.py: a script that bootstraps first
    script.write_text(f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
                      "import dictate; dictate.bootstrap(gui=False); print(sys.prefix)\n")
    system_python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"
    result = subprocess.run([system_python, str(script)], capture_output=True, text=True, timeout=60)
    assert Path(result.stdout.strip()) == ROOT / ".venv"
