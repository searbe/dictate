#!/bin/sh
# macOS (Apple Silicon or Intel). Needs Homebrew (https://brew.sh) for Python 3.14 and GTK 3.
# Everything else goes into this folder: .venv (Python deps), bin/ (llama.cpp) and models/. Safe to re-run.
set -e
cd "$(dirname "$0")"
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
brew install python@3.14 gtk+3 pygobject3 adwaita-icon-theme
PY="$(brew --prefix python@3.14)/bin/python3.14"

# --system-site-packages: reuse Homebrew's GTK bindings (gi, cairo)
.venv/bin/python -c "import gi" 2>/dev/null || { rm -rf .venv; "$PY" -m venv --system-site-packages .venv; }
.venv/bin/pip install -q --no-cache-dir --disable-pip-version-check --upgrade --upgrade-strategy eager -e .
.venv/bin/python scripts/fetch.py

cat <<'EOD'

Done. Run: .venv/bin/python dictate.py
Hold Ctrl+Cmd to dictate (Alt = Option). The first time, macOS will ask for permissions for the app
you launch it from (e.g. Terminal) under System Settings > Privacy & Security:
  - Microphone          (recording)
  - Input Monitoring    (the global Ctrl+Cmd hotkey)
  - Accessibility       (pasting with Cmd+V)
  - Screen Recording    (optional: lets per-app refinements see window titles, not just app names)
Restart Dictate after granting them.
EOD
