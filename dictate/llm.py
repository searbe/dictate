"""The local language model: a llama-server started on demand, and asking it things.

server.warm() (at hotkey-down) picks the GPU (Vulkan, or Metal on a Mac: the larger model) if the card is idle
with enough free VRAM, else the CPU (the smaller model), so the model is loading while you speak. It's stopped
after IDLE seconds unused, so it doesn't hold the graphics card while you game. It only listens on 127.0.0.1.
"""

import atexit
import ctypes
import json
import logging
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import ROOT

log = logging.getLogger(__name__)

SERVER = ROOT / "bin/llama" / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
MODELS = {"gpu": ROOT / "models/qwen3.5-9b-q4_k_m.gguf", "cpu": ROOT / "models/qwen3.5-4b-q4_k_m.gguf"}
IDLE = 30  # seconds unused before unloading
SPARE_VRAM_MB = 2000  # free VRAM needed beyond the model's own size to use the GPU
MAX_GPU_BUSY = 30  # % busy above which we assume a game/app is using the GPU
DISCRETE = 8 << 30  # bytes of VRAM: more than this is the discrete card, not the iGPU
CONTEXT = 8192  # tokens: the prompt and the answer together
OVERHEAD = 64  # tokens the chat template adds around a prompt
LOAD_TIMEOUT = 60  # seconds to wait for the model to load


# --- the graphics card ---
def gpu_free(need_mb: int) -> bool:
    """True if the GPU has need_mb of memory free and isn't busy.
    Linux: AMD cards via amdgpu sysfs. Windows: NVIDIA cards via nvidia-smi (others use the CPU).
    macOS: Apple Silicon shares system RAM with the GPU, so just require 16 GB or more."""
    if sys.platform == "darwin":
        mem = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout
        return mem.strip().isdigit() and int(mem) >= 16 << 30
    if sys.platform == "win32":
        if not shutil.which("nvidia-smi"):
            return False
        query = ["nvidia-smi", "--query-gpu=memory.free,utilization.gpu", "--format=csv,noheader,nounits"]
        out = subprocess.run(query, capture_output=True, text=True, **SPAWN).stdout.split(",")
        return len(out) == 2 and int(out[0]) > need_mb and int(out[1]) < MAX_GPU_BUSY
    for dev in Path("/sys/class/drm").glob("card*/device"):
        try:
            total, used, busy = (int((dev / f).read_text())
                                 for f in ("mem_info_vram_total", "mem_info_vram_used", "gpu_busy_percent"))
        except (OSError, ValueError):
            continue
        if total > DISCRETE:
            return (total - used) >> 20 > need_mb and busy < MAX_GPU_BUSY
    return False


def gpu_ok() -> bool:
    """Whether the larger model would fit on the GPU now."""
    model = MODELS["gpu"]
    return model.exists() and gpu_free((model.stat().st_size >> 20) + SPARE_VRAM_MB)


def gpu_present() -> bool:
    """Whether there's a GPU the larger model could use, when it's free (else it's always the CPU)."""
    if not MODELS["gpu"].exists():
        return False
    if sys.platform == "darwin":
        return gpu_free(0)
    if sys.platform == "win32":
        return bool(shutil.which("nvidia-smi"))
    for dev in Path("/sys/class/drm").glob("card*/device"):
        try:
            if int((dev / "mem_info_vram_total").read_text()) > DISCRETE:
                return True
        except (OSError, ValueError):
            continue
    return False


# --- the server process ---
def _die_with_parent() -> None:  # Linux, in the child: if Dictate exits or crashes, the server (and its VRAM) goes too
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG; llama-server can hang on SIGTERM


# how each OS starts the server: no console window on Windows; tied to our lifetime on Linux
SPAWN: dict[str, Any] = ({"creationflags": 0x08000000} if sys.platform == "win32" else  # CREATE_NO_WINDOW
                         {"preexec_fn": _die_with_parent} if sys.platform.startswith("linux") else {})


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Launcher:
    """Starts processes from one thread that lives as long as the app: Linux's parent-death signal fires when
    the *thread* that started a child exits, so a short-lived worker must never start the server itself."""

    def __init__(self) -> None:
        self._requests: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def popen(self, cmd: list) -> subprocess.Popen:
        with self._lock:
            if not self._thread:
                self._thread = threading.Thread(target=self._run, daemon=True, name="llm-launcher")
                self._thread.start()
        done: queue.Queue = queue.Queue()
        self._requests.put((cmd, done))
        proc = done.get()
        if isinstance(proc, OSError):
            raise proc
        return proc

    def _run(self) -> None:
        while True:
            cmd, done = self._requests.get()
            try:
                done.put(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SPAWN))
            except OSError as err:  # e.g. llama-server missing: report it, and keep this thread for next time
                done.put(err)


class Server:
    """The one llama-server everything shares: dictations (held from hotkey-down until pasted), and while
    transcribing, the topics and the summary (kept loaded for the whole call)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._launcher = _Launcher()
        self._proc: subprocess.Popen | None = None
        self._mode: str | None = None
        self._hold = False  # a dictation is using it
        self._keep = 0  # calls being transcribed, or finished (keep(True) each, keep(False) when they're done)
        self._busy = 0  # requests being answered (never unloaded mid-answer: on the CPU one can take minutes)
        self._last = 0.0  # when it was last used (monotonic)
        self._port: int | None = None  # chosen at first start: per instance, so bench.py never talks to another's
        self._started = False

    @property
    def mode(self) -> str | None:
        """"gpu" or "cpu": where the loaded model runs (the larger one on the GPU), or None if none is loaded."""
        return self._mode if self._running() else None

    def _running(self) -> bool:
        return bool(self._proc) and self._proc.poll() is None

    def warm(self, mode: str | None = None, hold: bool = True) -> None:
        """Start the server if it isn't running (without waiting for it to load); with hold, keep it loaded until
        release(). mode forces "gpu" or "cpu" (bench.py); by default it's decided from the GPU's current load."""
        with self._lock:
            self._start_once()
            if hold:
                self._hold = True
            self._last = time.monotonic()
            if self._running():
                return
            self._mode = mode or ("gpu" if gpu_ok() else "cpu")
            gpu = ["-ngl", "99"] if sys.platform == "darwin" else ["--device", "Vulkan0", "-ngl", "99"]  # Metal/Vulkan
            device = gpu if self._mode == "gpu" else ["--device", "none", "-ngl", "0"]
            threads = str(min(8, os.cpu_count() or 4))
            try:
                self._proc = self._launcher.popen([SERVER, "-m", MODELS[self._mode], "--host", "127.0.0.1",
                                                   "--port", str(self._port), "-c", str(CONTEXT), "--no-webui",
                                                   "--reasoning", "off", "-t", threads, *device])
            except OSError as err:  # refining is skipped (the transcript is used as it is) until this is fixed
                self._proc = None
                log.warning("can't start llama-server: %s", err)
                return
            log.info("loading %s on %s", MODELS[self._mode].name, self._mode)

    def _start_once(self) -> None:
        """The first time it's wanted: pick a port, unload it when unused, and stop it when Dictate exits."""
        if self._started:
            return
        self._started, self._port = True, _free_port()
        threading.Thread(target=self._reap, daemon=True, name="llm-reaper").start()
        atexit.register(self.stop)

    def release(self) -> None:
        """The dictation that warmed it is done: it may be unloaded once it's been unused for IDLE seconds."""
        self._hold, self._last = False, time.monotonic()

    def keep(self, on: bool) -> None:
        """Keep the server loaded (while transcribing, for its topics), however long it's unused, until as many
        keep(False) as keep(True)."""
        with self._lock:
            self._keep, self._last = max(0, self._keep + (1 if on else -1)), time.monotonic()

    def busy(self, on: bool) -> None:
        """A request is being answered (on), or has been."""
        with self._lock:
            self._busy, self._last = max(0, self._busy + (1 if on else -1)), time.monotonic()

    def stop(self, if_idle: bool = False) -> None:
        with self._lock:
            if not self._proc or (if_idle and (self._hold or self._keep or self._busy
                                               or time.monotonic() - self._last < IDLE)):
                return
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:  # llama-server sometimes ignores SIGTERM
                self._proc.kill()
                self._proc.wait()
            self._proc = None
            log.info("unloaded")

    def _reap(self) -> None:
        while True:
            time.sleep(5)
            self.stop(if_idle=True)

    def to_gpu(self) -> bool:
        """If the smaller model is loaded on the CPU (the GPU was busy), nothing is being refined, and the GPU is
        free now: load the larger one there instead. Returns whether it did. Slow: not on the GTK thread."""
        with self._lock:
            if not (self._running() and self._mode == "cpu" and not self._hold and gpu_ok()):
                return False
        self.stop()
        self.warm(hold=False)
        return True

    def ready(self, hold: bool = True) -> None:
        """Start the model if need be, and wait for it to finish loading."""
        self.warm(hold=hold)
        deadline = time.monotonic() + LOAD_TIMEOUT
        while time.monotonic() < deadline:
            if not self._running():
                raise OSError("llama-server isn't running")
            try:
                self.post("/health", timeout=1)
                return
            except OSError:
                time.sleep(0.1)

    def post(self, path: str, body: dict | None = None, timeout: float = 60) -> Any:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(f"http://127.0.0.1:{self._port}{path}", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as reply:
            return json.loads(reply.read())


server = Server()


# --- asking it ---
class Cut(ValueError):
    """The model's answer stopped at max_tokens, or at the end of the context: it isn't whole."""


def tokens(text: str) -> int:
    """How many tokens text is, to the model loaded."""
    server.ready(hold=False)
    return len(server.post("/tokenize", {"content": text}, timeout=10)["tokens"])


def fits(system: str, user: str, max_tokens: int) -> bool:
    """Whether a prompt leaves room in the context for an answer of max_tokens."""
    return tokens(system) + tokens(user) + OVERHEAD + max_tokens <= CONTEXT


def chat(system: str, user: str, *, max_tokens: int, temperature: float = 0.0, schema: dict | None = None,
         timeout: float = 60, hold: bool = True) -> str:
    """The model's answer to user under system (as JSON matching schema, if given). Waits for it to load.
    hold: the caller is a dictation, which releases the server once it's pasted. Raises Cut if the answer was cut
    off (so half an answer is never taken for a whole one)."""
    server.ready(hold=hold)
    body: dict[str, Any] = {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
    server.busy(True)
    try:
        choice = server.post("/v1/chat/completions", body, timeout=timeout)["choices"][0]
    finally:
        server.busy(False)
    if choice.get("finish_reason") == "length":
        raise Cut(f"the answer was cut off after {max_tokens} tokens: …{choice['message']['content'][-60:]!r}")
    return choice["message"]["content"].strip()


def ask(system: str, user: str, schema: dict, max_tokens: int = 500) -> str:
    """The model's answer as JSON matching schema (the topics of a call)."""
    return chat(system, user, max_tokens=max_tokens, schema=schema, timeout=120, hold=False)


def write(system: str, user: str, max_tokens: int = 1500) -> str:
    """The model's answer as text (the live summary of a call)."""
    return chat(system, user, max_tokens=max_tokens, temperature=0.2, timeout=180, hold=False)
