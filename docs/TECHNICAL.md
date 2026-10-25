# Dictate: the technical details

What's under the hood, how to set it up on each platform, and how to check it stays on your computer. For what
Dictate does, see the [README](../README.md).

## How it works
- **Hotkey:** the keyboard is read directly (evdev on Linux), so **Ctrl+Win** works in every app, and any other key
  pressed with it (e.g. Ctrl+Win+→ to switch desktop) is left to its own shortcut.
- **Speech:** [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) on the CPU, via
  [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), with [Silero VAD](https://github.com/snakers4/silero-vad)
  finding the pauses. Each stretch is transcribed as soon as you pause, so the text is ready 0.1 s or so after you
  let go.
- **Cleanup and refinements:** [Qwen3.5](https://huggingface.co/Qwen/Qwen3.5-9B) in
  [llama.cpp](https://github.com/ggml-org/llama.cpp): 9B on the GPU (Vulkan on Linux and Windows, Metal on macOS)
  when one's free, 4B on the CPU otherwise. It's loaded while you speak and unloaded after 30 seconds unused, so it
  doesn't hold the graphics card while you game. A change that looks wrong (too much reworded, an answer instead of a
  cleanup) is thrown away and your words are pasted as they were.
- **Pasting:** the text goes on the clipboard and into the focused app with Ctrl+V (Ctrl+Shift+V in terminals); while
  your keyboard controls another computer (Synergy and similar), it's typed instead. Both are decided when you
  release Ctrl+Win: which computer has the keyboard, and the focused app (found through KWin, for per-app
  refinements).
- **Transcribe mode** records the computer's speakers (PipeWire's monitor) and your microphone separately:
  - **Speakers:** a segmentation model ([pyannote segmentation 3.0](https://huggingface.co/pyannote/segmentation-3.0))
    finds where the voice changes, however quick the turns, and voiceprints
    ([TitaNet small](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small)) tell which person
    each part is. A line is shown at once with the voice heard last, and settled about 10 seconds later: the
    segmenter tells a change better once it has heard what follows.
  - **Echo:** without headphones, the microphone hears the speakers too: what it heard is checked against what the
    speakers played (sound and words), so the call isn't written down twice as you.
  - **Topics and summary:** the refinement model updates the topics about every 20 seconds and the summary about
    every 30, from what's been said since, and makes a careful final pass when you stop.

Each module in `dictate/` explains itself at the top, with what was measured to choose how it works.

## Recommended hardware
| | Minimum | Recommended |
|---|---|---|
| **CPU** | Any 64-bit x86 or Apple Silicon from the last ~6 years | 8 cores or more, if refining text on the CPU |
| **RAM** | 8 GB | 16 GB or more |
| **GPU** | None: everything can run on the CPU | 8 GB+ of free video memory (12 GB+ card), any Vulkan GPU on Linux, NVIDIA on Windows, or an Apple Silicon Mac with 16 GB+ |
| **Disk** | ~12 GB for the models | SSD, so the models load quickly |
| **Microphone** | Built-in | A headset or close-up mic: the biggest single help in noisy rooms |

Transcription takes 0.1 s or less after you let go. Refining is the slow part: about 0.5–1.5 s with a free GPU
(tested on a Radeon RX 9070 XT), 1–2 s on a recent 8-core CPU, longer on laptops.

## Setup (self-contained)
Each setup script installs into this folder and nothing anywhere else, and is safe to re-run:
- `models/`: Parakeet TDT 0.6B v3 (~2.5 GB, speech), Silero VAD, TitaNet small (40 MB, voices), pyannote segmentation (6 MB, where voices change), and Qwen3.5 4B (~2.7 GB, CPU) and 9B (~5.7 GB, GPU) for refinement.
- `bin/llama/`: a llama.cpp release (Vulkan on Linux/Windows, Metal on macOS), used for refinement.
- `.venv/`: Python packages.
- `data/`: your dictations, recordings, transcripts, settings, refinements and vocabulary.

Delete the folder to remove the app completely.

### Linux (SteamOS / KDE Plasma): the main platform
`./setup.sh`, then `python dictate.py` (it switches to `.venv` automatically). It reuses the system's GTK and evdev bindings read-only.
If a SteamOS update breaks the app, run `./setup.sh` again; it rebuilds `.venv` for the new system Python.
To start it at login, tick **Run at startup** in the menu (adds `~/.config/autostart/dictate.desktop`; unticking removes it).

### Ubuntu 24.04+ / Debian
`./setup.sh` as above. On Ubuntu and Debian (and derivatives such as Mint and Pop!_OS) it first asks for your sudo password to:
- install the system packages SteamOS already ships, if missing: the GTK, evdev and dbusmenu Python bindings, `python3-venv`, PipeWire's `pw-record`/`pw-play`, and the Vulkan loader;
- add `/etc/udev/rules.d/70-dictate.rules`, if your session can't already read the keyboards and `/dev/uinput`. It gives the logged-in user access (as Steam's rules do on SteamOS); log out and back in if the hotkey doesn't work at once. This lets any program you run read your keyboard, which is how the global hotkey works.

Focused-app detection uses KWin, so per-app refinements need KDE (Kubuntu); on GNOME everything else works, and the tray icon needs Ubuntu's AppIndicator extension (on by default). Tested in an Ubuntu 24.04 container (setup and transcription), not on a desktop.

Other distributions need the same pieces by hand: read access to `/dev/input/event*` and `/dev/uinput`, PyGObject with GTK 3, python-evdev, the dbusmenu GObject bindings, and PipeWire's `pw-record`/`pw-play`.

### Windows 10/11 (untested)
1. Install Python 3.14: `winget install -e --id Python.Python.3.14` (GTK's Python bindings are built for 3.14).
2. `powershell -ExecutionPolicy Bypass -File setup-windows.ps1`. This also downloads a GTK 3 runtime into `gtk\` (~300 MB, from [gvsbuild](https://github.com/wingtk/gvsbuild)).
3. Double-click `Dictate.lnk`. **Run at startup** in the menu adds or removes it from the login items (the per-user Run registry key).

Hold **Ctrl+Win**. The GPU model is used on NVIDIA cards with enough free memory (checked with `nvidia-smi`); otherwise refinement runs on the CPU. Transcribe mode is Linux only.

### macOS (untested)
1. Install [Homebrew](https://brew.sh).
2. `./setup-mac.sh` (installs Python 3.14 and GTK 3 with Homebrew).
3. `.venv/bin/python dictate.py`

Hold **Ctrl+Cmd** (Option is Alt). There's no menu-bar icon on macOS (GTK 3 can't make one), so use the capsule's menu. **Run at startup** adds a LaunchAgent (`~/Library/LaunchAgents/local.dictate.plist`). macOS will ask for Microphone, Input Monitoring (hotkey) and Accessibility (paste) permissions for the app you launch it from; restart Dictate after granting them. Screen Recording is optional and lets per-app refinements see window titles. Macs with 16 GB of RAM or more use the 9B model on the GPU (Metal). Transcribe mode is Linux only.

## Checking that it's local only
To check that Dictate makes no network connections, on Linux after setup, run:

```sh
python scripts/prove_local.py
```

It runs Dictate, with the real models, in a sandbox with no network, records every network call of every process,
and ends with `RESULT: LOCAL ONLY` only if they all stayed on this computer. `--live` does the same with your actual
Dictate, keyboard and microphone (quit Dictate first). It needs `bubblewrap` and `strace` (SteamOS has both; on
Ubuntu: `sudo apt install bubblewrap strace`).

## Code
- `dictate.py` starts the app; the app is the `dictate/` package. Each module explains itself at the top:
  - **The app:** `app.py` (the dictation pipeline and transcribe mode, tying the rest together), `capsule.py`,
    `menu.py` (the capsule's menu, also in the tray), `tray.py`.
  - **Dictating:** `osio.py` (hotkey, recording and pasting, per OS), `stt.py` (speech to text), `refine.py`
    (cleanup and refinements), `llm.py` (the local model: llama-server, started on demand), `activewin.py` (the
    focused window), `remote.py` (another computer has the keyboard).
  - **Transcribe mode:** `transcript.py`, `voices.py`, `echo.py`, `topics.py`, `summary.py`.
  - **The Dictate window:** `hub.py` (the window and its sidebar), one module per page (`dictations_page.py`,
    `transcripts_page.py`, `refinements_page.py`, `voices_page.py`, `settings_page.py`), `huds.py` (the picker,
    reminders and dialogs), `design.py` and `style.css` (the design system).
  - **Your data:** `settings.py`, `history.py` (dictations), `refinements.py` (refinements and vocabulary), and
    `store.py`, which every save goes through (written to a temporary file, then swapped in, so a crash never
    leaves a half-written file). The built-in prompts are text files in `prompts/`.
- `scripts/`: `fetch.py` (downloads, used by setup), `test.py` (the tests: see [TESTING.md](TESTING.md)),
  `prove_local.py`, `bench.py` (compares refinement models), `bench_voices.py` (telling voices apart),
  `bench_topics.py` (topics on saved transcripts), `replay_call.py` (a recorded call through transcribe mode again).
- `docs/make_screenshots.py`: regenerates the screenshots.
- Lint with `.venv/bin/ruff check .` (configured in `pyproject.toml`; `pip install --group dev` installs it).
- How the UI is designed, and the rules for changing it: [design/DESIGN.md](design/DESIGN.md).

## Data
`data/` (not in git; `DICTATE_DATA` moves it): `dictations.jsonl`, recordings in `audio/` and `transcripts/`
(transcripts are Markdown, with their topics, summary and voiceprints beside them), `refinements.json`,
`summary.txt` (your live summary prompt, if you've changed it), `vocab.txt`, `voices.json` (remembered voices, if
on) and `state.json`. Logs go to `journalctl --user` when started from the desktop.

## Licenses
Dictate is MIT: see [LICENSE](../LICENSE). The models and tools the setup scripts download come under their own licenses: [Parakeet TDT](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), [Qwen3.5](https://huggingface.co/Qwen/Qwen3.5-9B), [Silero VAD](https://github.com/snakers4/silero-vad), [TitaNet](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small), [pyannote segmentation](https://huggingface.co/pyannote/segmentation-3.0), [llama.cpp](https://github.com/ggml-org/llama.cpp), [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) and, on Windows, [gvsbuild](https://github.com/wingtk/gvsbuild)'s GTK runtime.
