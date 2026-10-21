#!/usr/bin/env python3
"""Runs the automated tests: python scripts/test.py [pytest arguments, e.g. -k history]

They get their own D-Bus and an invisible desktop, so they never touch your real session, your running
Dictate or your data: a headless KWin with XWayland where KDE is installed (which also runs Dictate's KWin
script for real), else Xvfb. With neither, only the tests that need no desktop run. See docs/TESTING.md."""
import os, shlex, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv/bin/python"


def main():
    python = str(VENV_PY if VENV_PY.exists() else sys.executable)
    pytest = [python, "-m", "pytest", *(["--color=yes"] if sys.stdout.isatty() else []), *sys.argv[1:]]
    tmp = Path(tempfile.mkdtemp(prefix="dictate-test-"))
    runtime = tmp / "runtime"  # a fresh XDG_RUNTIME_DIR: no access to the real session's sockets
    runtime.mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
    env.update(XDG_RUNTIME_DIR=str(runtime), HOME=str(tmp / "home"), DICTATE_TEST_SESSION="1",
               DICTATE_DATA=str(tmp / "data"), PYTHONDONTWRITEBYTECODE="1")
    (tmp / "home").mkdir()
    try:
        if sys.platform.startswith("linux") and shutil.which("kwin_wayland") and shutil.which("dbus-run-session"):
            # KWin's own chatter is dropped; pytest's output and exit code come back through files
            out, status = tmp / "out", tmp / "status"
            out.touch()
            session = f"sh -c {shlex.quote(shlex.join(pytest) + f' > {out} 2>&1; echo $? > {status}')}"
            env["DICTATE_TEST_KWIN"] = "1"
            kwin = subprocess.Popen(["dbus-run-session", "--", "kwin_wayland", "--virtual", "--xwayland",
                                     "--no-lockscreen", "--no-global-shortcuts", "--socket", "dictate-test",
                                     "--width", "1280", "--height", "800", "--exit-with-session", session],
                                    env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(out) as f:
                while True:
                    finished = kwin.poll() is not None
                    sys.stdout.write(f.read())
                    sys.stdout.flush()
                    if finished:
                        break
                    time.sleep(0.2)
            return int(status.read_text()) if status.exists() else 1
        if shutil.which("xvfb-run") and shutil.which("dbus-run-session"):
            return subprocess.run(["dbus-run-session", "--", "xvfb-run", "-a", *pytest], env=env, cwd=ROOT).returncode
        print("No headless KWin or Xvfb found: running only the tests that need no desktop.", file=sys.stderr)
        env.pop("DICTATE_TEST_SESSION")
        return subprocess.run(pytest, env=env, cwd=ROOT).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
