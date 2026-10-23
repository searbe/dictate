#!/usr/bin/env python3
"""Downloads the models and the llama.cpp build for this OS into models/ and bin/. Run by the setup scripts.

Safe to re-run: anything already present is skipped."""
import platform
import shutil
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the project folder
MODELS, BIN = ROOT / "models", ROOT / "bin"
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
HF = "https://huggingface.co/unsloth"
LLAMA = "b11755"  # llama.cpp release
LLAMA_BUILD = {  # Vulkan builds run on AMD, NVIDIA and Intel GPUs (or the CPU); macOS builds use Metal
    "linux": "ubuntu-vulkan-x64.tar.gz",
    "win32": "win-vulkan-x64.zip",
    "darwin": "macos-arm64.tar.gz" if platform.machine() == "arm64" else "macos-x64.tar.gz",
}


def download(url, dest):
    """Fetch url to dest via a .part file, so an interrupted download is never mistaken for a finished one."""
    if dest.exists():
        return
    part = dest.with_name(dest.name + ".part")
    print(f"Downloading {dest.name} ...", flush=True)
    with urllib.request.urlopen(url) as r, open(part, "wb") as f:
        total, done, shown = int(r.headers.get("Content-Length", 0)), 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total and done * 10 // total != shown:
                shown = done * 10 // total
                print(f"  {shown * 10}%", flush=True)
    if total and done < total:  # a dropped connection just ends the stream early; it doesn't raise
        raise OSError(f"{dest.name}: download interrupted at {done} of {total} bytes; run setup again")
    part.rename(dest)


def unpack(archive, dest):
    """Extract a .zip or .tar.* archive into dest."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="tar")


def main():
    MODELS.mkdir(exist_ok=True)
    BIN.mkdir(exist_ok=True)
    # speech recognition: Parakeet TDT 0.6B v3 + the Silero speech detector
    if not (MODELS / "parakeet").exists():
        name = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
        download(f"{SHERPA}/{name}.tar.bz2", MODELS / f"{name}.tar.bz2")
        unpack(MODELS / f"{name}.tar.bz2", MODELS)
        (MODELS / name).rename(MODELS / "parakeet")
        (MODELS / f"{name}.tar.bz2").unlink()
    download(f"{SHERPA}/silero_vad.onnx", MODELS / "silero_vad.onnx")
    # telling voices apart in transcripts: TitaNet small (see voices.py; compare with bench_voices.py)
    download("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"  # sic
             "nemo_en_titanet_small.onnx", MODELS / "titanet_small.onnx")
    # where the voice changes in a transcript, every ~17 ms: pyannote's segmentation model (see voices.py)
    if not (MODELS / "segmentation.onnx").exists():
        name = "sherpa-onnx-pyannote-segmentation-3-0"
        download("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
                 f"{name}.tar.bz2", MODELS / f"{name}.tar.bz2")
        unpack(MODELS / f"{name}.tar.bz2", MODELS)
        (MODELS / name / "model.onnx").rename(MODELS / "segmentation.onnx")
        shutil.rmtree(MODELS / name)
        (MODELS / f"{name}.tar.bz2").unlink()
    # refinement: 4B for the CPU, 9B for the GPU (see MODELS in refine.py; compare others with bench.py)
    download(f"{HF}/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf", MODELS / "qwen3.5-4b-q4_k_m.gguf")
    download(f"{HF}/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf", MODELS / "qwen3.5-9b-q4_k_m.gguf")
    # llama.cpp, which runs the refinement model
    if not (BIN / "llama").exists():
        build = LLAMA_BUILD["linux" if sys.platform.startswith("linux") else sys.platform]
        archive = BIN / f"llama-{LLAMA}-bin-{build}"
        download(f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA}/{archive.name}", archive)
        tmp = BIN / "llama-unpack"
        unpack(archive, tmp)
        server = next(tmp.rglob("llama-server*"))  # archive layouts differ by platform; find the binaries
        server.parent.rename(BIN / "llama")
        shutil.rmtree(tmp, ignore_errors=True)
        archive.unlink()
        if sys.platform != "win32":  # zip doesn't keep the executable bit
            for f in (BIN / "llama").iterdir():
                f.chmod(f.stat().st_mode | stat.S_IXUSR)
    print("Models and llama.cpp are ready.")


if __name__ == "__main__":
    main()
