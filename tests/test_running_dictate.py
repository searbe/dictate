"""Starting, stopping and the things that outlive a session: run at startup, one copy only, the quit log."""
import os, signal, socket, subprocess, sys
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
def test_run_at_startup_adds_a_login_entry_that_starts_dictate_and_removes_it_again(start):
    app = start(styles=[])
    entry = app.home / ".config/autostart/dictate.desktop"

    app.send("menu", path=["Run at startup"])

    exec_line = next(l for l in entry.read_text().splitlines() if l.startswith("Exec="))
    python, script = [Path(p) for p in exec_line[5:].strip('"').split('" "')]
    assert python.exists() and script == ROOT / "dictate.py"
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
