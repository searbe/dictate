# Dictate

Push-to-talk dictation that runs entirely on your own computer. Hold a hotkey and speak; when you let go, the transcribed and cleaned-up text is pasted into the app you're typing in. Built for Linux (SteamOS / KDE Plasma), and also sets up on Ubuntu 24.04+; Windows and macOS support is included but untested.

## Features
- **Hotkey dictation:** hold **Ctrl+Win** (Ctrl+Cmd on a Mac), speak, release to paste.
- **Local speech recognition:** Parakeet TDT 0.6B on the CPU, transcribing as you speak.
- **Clean-up:** a local language model (Qwen3.5) removes filler words, applies self-corrections and fixes punctuation and mis-heard words. It uses the GPU when one is free, otherwise the CPU.
- **Refinement styles:** reformat for Slack, WhatsApp, email or AI agents, or your own styles. Pick one per dictation, set a default, or match styles to apps automatically.
- **Vocabulary:** names and terms you use, spelled the way you spell them.
- **Transcribe mode** (Linux): transcribes your computer's audio and your microphone, e.g. a call, telling the voices apart.
- **History:** every dictation with what was applied, playback of the recording, copy, delete and clear. Recordings are kept for a time you choose.
- **Synergy:** while your keyboard is controlling another computer, the text is typed there.
- **Floating icon and system tray icon** with the same menu, and an optional **Run at startup**.
- **Self-contained:** everything installs into this folder. Dictate sends nothing over the network; models are downloaded once, during setup. [Check it yourself](#checking-that-its-local-only).

## Using it
Hold **Ctrl+Win** to record, release to transcribe and paste into the focused text box.
- **Tap Alt** while holding: pick a refinement style when you let go (its letter; Enter pastes as is, Esc only copies).
- **Alt+letter** while holding (e.g. Alt+S): use that style directly.
- **Default style** (menu): used for every other dictation. "None" means cleanup only.
- **Per-app styles:** a style can be used automatically in apps whose name or window title matches (e.g. "slack").
- **Vocabulary** (Refinement styles…): names and terms, spelled your way.
- **Refine text** (menu): off gives the raw transcript, fastest.
- **Synergy and similar:** while your keyboard controls another computer, the text is typed there. **When another computer has the keyboard** (menu) sets its style, or ignores the hotkey.
- On Linux, terminals get Ctrl+Shift+V instead of Ctrl+V.

**Transcribe mode** (Linux) transcribes your computer's audio and your microphone, e.g. a call.
- **Start / stop:** hold Ctrl+Win, lift Win and press it again. Or use **Stop**, or the menu.
- People are labelled "Speaker 1", "Speaker 2"… Click a name to rename them; naming two the same merges them.
- You can dictate as usual while it runs; your dictations stay out of the transcript.
- **Transcripts** (menu) lists them all; the live one is at the top. Saved as Markdown in `data/transcripts/`.
- **Voices…** can remember the people you name, for next time (off by default; ask people first).

The floating dot is red while recording and spins while transcribing; a blue ring means transcribe mode is on (click it to see the transcript). Drag it to move it; right-click it, or the tray icon, for the menu.

**History** (menu) lists every dictation: play it back, copy it or delete it. **Keep recordings** sets how long audio is kept (default 24 hours).

![Floating icon: idle, recording, transcribing](docs/icon-states.png)

| Style picker (tap Alt while dictating) | History |
|---|---|
| ![Style picker](docs/picker.png) | ![History](docs/history.png) |

![Refinement styles](docs/styles.png)

![Transcripts](docs/transcripts.png)

Screenshots are generated from sample data with `python docs/make_screenshots.py` (rendered off-screen).

## Checking that it's local only
Don't take our word for it. On Linux, after setup, run:

```sh
python scripts/prove_local.py
```

It seals off a sandbox with no network (only loopback, and none of the system's services, so not even a DNS
lookup can get out), shows that the internet can't be reached from inside, and checks that its recorder catches a
program that tries. Then it runs Dictate in there, with the real speech and language models transcribing and
refining a sample recording, while recording every network call of every process. It lists each call and ends with
`RESULT: LOCAL ONLY` only if all of them stayed on this computer. (Calls to 127.0.0.1 are Dictate talking to the
llama-server it started.)

`python scripts/prove_local.py --live` does the same with your actual Dictate, keyboard and microphone: quit
Dictate first, then dictate as usual in the sandboxed copy and choose Quit from its menu to see the report.

It needs `bubblewrap` and `strace` (SteamOS has both; on Ubuntu: `sudo apt install bubblewrap strace`).

## Recommended hardware
| | Minimum | Recommended |
|---|---|---|
| **CPU** | Any 64-bit x86 or Apple Silicon from the last ~6 years | 8 cores or more, if refining text on the CPU |
| **RAM** | 8 GB | 16 GB or more |
| **GPU** | None: everything can run on the CPU | 8 GB+ of free video memory (12 GB+ card), any Vulkan GPU on Linux, NVIDIA on Windows, or an Apple Silicon Mac with 16 GB+ |
| **Disk** | ~10 GB for the models | SSD, so the models load quickly |
| **Microphone** | Built-in | A headset or close-up mic: the biggest single help in noisy rooms |

Transcription runs on the CPU while you speak, so little is usually left when you let go (0.1 s or less, unless you've spoken for a long time without a pause). Refining text is the heavy part: with a free GPU it uses the 9B model, otherwise the 4B model on the CPU, which is slower (about 1–2 s per dictation on a recent 8-core desktop, longer on laptops). Tested on an AMD Ryzen 7 9800X3D with 64 GB of RAM and a Radeon RX 9070 XT (16 GB), where a cleaned-up dictation is ready about 0.5–1.5 s after letting go.

## Setup (self-contained)
Each setup script installs into this folder and nothing anywhere else, and is safe to re-run:
- `models/`: Parakeet TDT 0.6B v3 int8 (~640 MB), the Silero VAD speech filter, and Qwen3.5 4B (~2.7 GB, CPU) and 9B (~5.7 GB, GPU) for refinement.
- `bin/llama/`: a llama.cpp release (Vulkan on Linux/Windows, Metal on macOS), used for refinement.
- `.venv/`: Python packages.
- `data/`: your history, recordings, settings, styles and vocabulary (see Technical notes).

Delete the folder to remove the app completely.

### Linux (SteamOS / KDE Plasma): the main platform
`./setup.sh`, then `python dictate.py` (it switches to `.venv` automatically). It reuses the system's GTK and evdev bindings read-only.
If a SteamOS update breaks the app, run `./setup.sh` again; it rebuilds `.venv` for the new system Python.
To start it at login, tick **Run at startup** in the menu (adds `~/.config/autostart/dictate.desktop`; unticking removes it).
### Ubuntu 24.04+ / Debian
`./setup.sh` as above. On Ubuntu and Debian (and derivatives such as Mint and Pop!_OS) it first asks for your sudo password to:
- install the system packages SteamOS already ships, if missing: the GTK, evdev and dbusmenu Python bindings, `python3-venv`, PipeWire's `pw-record`/`pw-play`, and the Vulkan loader;
- add `/etc/udev/rules.d/70-dictate.rules`, if your session can't already read the keyboards and `/dev/uinput`. It gives the logged-in user access (as Steam's rules do on SteamOS); log out and back in if the hotkey doesn't work at once. This lets any program you run read your keyboard, which is how the global hotkey works.

Focused-app detection uses KWin, so per-app styles need KDE (Kubuntu); on GNOME everything else works, and the tray icon needs Ubuntu's AppIndicator extension (on by default). Tested in an Ubuntu 24.04 container (setup and transcription), not on a desktop.

Other distributions need the same pieces by hand: read access to `/dev/input/event*` and `/dev/uinput`, PyGObject with GTK 3, python-evdev, the dbusmenu GObject bindings, and PipeWire's `pw-record`/`pw-play`.

### Windows 10/11 (untested)
1. Install Python 3.14: `winget install -e --id Python.Python.3.14` (GTK's Python bindings are built for 3.14).
2. `powershell -ExecutionPolicy Bypass -File setup-windows.ps1`. This also downloads a GTK 3 runtime into `gtk\` (~300 MB, from [gvsbuild](https://github.com/wingtk/gvsbuild)).
3. Double-click `Dictate.lnk`. **Run at startup** in the menu adds or removes it from the login items (the per-user Run registry key).

Hold **Ctrl+Win**. The GPU model is used on NVIDIA cards with enough free memory (checked with `nvidia-smi`); otherwise refinement runs on the CPU.

### macOS (untested)
1. Install [Homebrew](https://brew.sh).
2. `./setup-mac.sh` (installs Python 3.14 and GTK 3 with Homebrew).
3. `.venv/bin/python dictate.py`

Hold **Ctrl+Cmd** (Option is Alt). There's no menu-bar icon on macOS (GTK 3 can't make one), so use the floating icon's menu. **Run at startup** adds a LaunchAgent (`~/Library/LaunchAgents/local.dictate.plist`). macOS will ask for Microphone, Input Monitoring (hotkey) and Accessibility (paste) permissions for the app you launch it from; restart Dictate after granting them. Screen Recording is optional and lets per-app styles see window titles. Macs with 16 GB of RAM or more use the 9B model on the GPU (Metal).

## Code
- `dictate.py`: starts the app (switching to `.venv` first). The app itself is the `dictate/` package:
  - `app.py`: floating icon, menu and the dictation pipeline (record → transcribe → cleanup → style → paste or type).
  - `osio.py`: everything OS-specific: global hotkey, recording, playback, paste, typing and run-at-startup (evdev/pw-record/pw-play/uinput on Linux, pynput/sounddevice on Windows and macOS).
  - `stt.py`: transcription. The VAD strips non-speech, then Parakeet runs on the CPU. `Live` follows the recording while it grows and transcribes each stretch of speech as soon as you pause; `transcribe()` does a whole file (the fallback).
  - `refine.py`: the default cleanup, then any style on top; style storage. Pressing the hotkey (or Alt) starts loading the model: the larger GPU model if the GPU has enough free memory and is under 30% busy, otherwise the smaller CPU model (`MODELS`). It's unloaded after 30 s of no use.
  - `dialogs.py`: History, the refinement style manager, the style picker, Transcripts and Voices.
  - `transcript.py` + `voices.py`: transcribe mode, and telling (and remembering) voices apart.
  - `remote.py`: tells when the keyboard is on another computer (so the text is typed there), from KWin's input-capture signals and Synergy's log.
  - `tray.py`: the system tray icon with the same menu (a StatusNotifierItem plus dbusmenu on KDE, GTK's status icon on Windows).
  - `activewin.py` + `kwin_active.js`: tracks the focused window and its title. On KDE, KWin loads the script at runtime and unloads it on exit; it's never installed. Windows and macOS ask the OS directly.
- `pyproject.toml`: the Python dependencies, installed into `.venv` by every setup script.
- `scripts/fetch.py`: downloads the models and the right llama.cpp build; used by every setup script.
- `scripts/bench.py`: compares every `models/*.gguf` on your recent dictations: `python scripts/bench.py`.
- `scripts/bench_voices.py`: how well transcripts tell voices apart, on mock conversations made from LibriSpeech.
- `docs/make_screenshots.py`: regenerates the README screenshots from sample data.
- `scripts/prove_local.py`: shows that Dictate makes no network connections (see above).
- `tests/` and `scripts/test.py`: the automated tests, run in their own invisible desktop: `python scripts/test.py`. [docs/TESTING.md](docs/TESTING.md) explains them and lists what to check by hand.

## Technical notes
- **Data** (`data/`, not in git; the `DICTATE_DATA` environment variable moves it elsewhere):
  - `history.jsonl`: one JSON object per dictation: `t`, `text`, `app`, `cleanup` (bool), and, when present, `title` (the window title per-app styles matched against), `raw` (the transcript, if refinement changed it), `style`, `audio`.
  - `audio/*.wav`: the recordings (16 kHz mono, about 2 MB a minute). They're pruned to the **Keep recordings** setting at startup, every 10 minutes and when it changes.
  - `styles.json`: the cleanup prompt; the styles (`name`, `key`, `apps`, `prompt`, `default`); and `remote_default` (absent means "same as here").
  - `vocab.txt`: one term per line. `state.json`: icon position and menu settings.
- **Refinement safety checks** (`refine.suspicious`): a model output is rejected, and the input kept, if it's empty, loses all the question marks, is less than half the length, adds a `[placeholder]`, or (for cleanup) changes too much, or (for styles) keeps less than 60% of the words. The fixed instructions in `refine.GUARD` sit above every style.
- **Model server:** llama-server on a random localhost port, started from one long-lived thread with a parent-death SIGKILL (Linux), so it can't outlive the app. It's stopped with SIGTERM, then SIGKILL after 3 s.
- **Single instance:** Dictate binds localhost port 47613 at startup; a second copy exits.
- **Remote screens:** KWin's input-capture broadcasts and Synergy's log are combined, as neither caught every switch alone. A capture must last 0.2 s to count, as a disconnected Synergy flickers every few milliseconds.
- **Transcribe mode:** the speakers are PipeWire's monitor of the default output; each side is kept as Ogg Opus (about 12 MB an hour) as long as dictation recordings are. A stretch is transcribed whole at a 1.2 s pause (with a greyed preview every second meanwhile), then split between voices (TitaNet small voiceprints) at its shorter pauses and where the voice changes. `scripts/bench_voices.py` measures it on mock LibriSpeech conversations: 94–99% of speaking time labelled right with pauses between turns, 82–90% with quick replies. Echoes of the speakers in the microphone are taken out by PipeWire's echo canceller and `echo.py`.
- **Logs:** written to stdout; when started from the desktop, see `journalctl --user`. It logs `started`, then `quitting: <why>` (the menu's Quit, a signal, or the icon's window closing) and `exited`, so a stop is never a mystery. Each dictation logs `recording: N ms after the key was pressed` (from the kernel's key timestamp), which is useful for spotting latency.

## License
MIT: see [LICENSE](LICENSE). The models and tools the setup scripts download come under their own licenses: Parakeet TDT (CC BY 4.0), Qwen3.5 (Apache 2.0), Silero VAD (MIT), llama.cpp (MIT), sherpa-onnx (Apache 2.0), and, on Windows, the gvsbuild GTK runtime (LGPL).
