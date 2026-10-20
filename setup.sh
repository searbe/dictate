#!/bin/sh
# Linux (SteamOS / KDE). Installs everything into this folder only: .venv (Python deps),
# bin/ (llama.cpp) and models/. Safe to re-run (e.g. after a SteamOS update changes the system Python).
set -e
cd "$(dirname "$0")"

# --system-site-packages: reuse the system's GTK (gi) and evdev bindings, read-only
.venv/bin/python -c "" 2>/dev/null || { rm -rf .venv; python3 -m venv --system-site-packages .venv; }
.venv/bin/pip install -q --no-cache-dir --disable-pip-version-check --upgrade sherpa-onnx numpy
.venv/bin/python fetch.py

cat > dictate.desktop <<EOD
[Desktop Entry]
Type=Application
Name=Dictate
Exec="$PWD/.venv/bin/python" "$PWD/dictate.py"
Icon=audio-input-microphone
EOD
echo "Done. Run: python dictate.py"
