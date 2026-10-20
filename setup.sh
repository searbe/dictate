#!/bin/sh
# Installs everything into this folder only: .venv (Python deps), bin/ (llama.cpp) and models/.
# Safe to re-run (e.g. after a SteamOS update changes the system Python).
set -e
cd "$(dirname "$0")"
REL=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
PARAKEET=sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8
LLAMA=b11755  # llama.cpp release (Vulkan build: runs on GPU or CPU)
HF=https://huggingface.co/unsloth

# --system-site-packages: reuse the system's GTK (gi) and evdev bindings, read-only
.venv/bin/python -c "" 2>/dev/null || { rm -rf .venv; python3 -m venv --system-site-packages .venv; }
.venv/bin/pip install -q --no-cache-dir --disable-pip-version-check --upgrade sherpa-onnx numpy

mkdir -p models data
[ -d models/parakeet ] || { curl -L "$REL/$PARAKEET.tar.bz2" | tar xj -C models; mv "models/$PARAKEET" models/parakeet; }
[ -f models/silero_vad.onnx ] || curl -L -o models/silero_vad.onnx "$REL/silero_vad.onnx"
# refinement models: 4B for CPU, 9B for GPU (see MODELS in refine.py; compare others with bench.py)
[ -f models/qwen3.5-4b-q4_k_m.gguf ] || curl -L -o models/qwen3.5-4b-q4_k_m.gguf "$HF/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf"
[ -f models/qwen3.5-9b-q4_k_m.gguf ] || curl -L -o models/qwen3.5-9b-q4_k_m.gguf "$HF/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf"
[ -x bin/llama/llama-server ] || { mkdir -p bin; curl -L "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA/llama-$LLAMA-bin-ubuntu-vulkan-x64.tar.gz" | tar xz -C bin; mv "bin/llama-$LLAMA" bin/llama; }

cat > dictate.desktop <<EOD
[Desktop Entry]
Type=Application
Name=Dictate
Exec="$PWD/.venv/bin/python" "$PWD/dictate.py"
Icon=audio-input-microphone
EOD
echo "Done. Run: python dictate.py"
