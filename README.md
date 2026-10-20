# Dictate

Hold **Ctrl+Win** to record, release to transcribe and paste into the focused text box.
- **Tap Alt** while holding: when you let go, a window shows the cleaned-up text and asks which refinement style to apply (press its letter, Enter to paste as is, or Esc to only copy it).
- **Alt+letter** while holding (e.g. Alt+S): applies that style directly, with no window.
- **Default style** (right-click > Default style): a style applied to every plain Ctrl+Win dictation after cleanup. Choose "None" for cleanup only.
- **Per-app styles**: a style whose "Use automatically in apps" keywords match the focused app or window title (e.g. "slack") is used instead of the default. The app's name and title are also given to the model as context.
- **Vocabulary** (Refinement styles… > Vocabulary): names and terms you use, so cleanup spells them right and fixes mis-hearings.
- Terminals get Ctrl+Shift+V instead of Ctrl+V.

The floating dot is dark when idle, red with pulsing rings while recording, and shows a spinner while transcribing. Drag it to move it. Right-click it for Refine text, History, Refinement styles… and Quit.

## Setup (self-contained)
`./setup.sh` installs everything inside this folder and nothing anywhere else:
- `.venv/`: Python packages (sherpa-onnx, numpy). It reuses the system's GTK/evdev bindings read-only.
- `models/`: Parakeet TDT 0.6B v3 int8 (~640 MB), the Silero VAD speech filter, and Qwen3.5 4B (~2.7 GB, CPU) and 9B (~5.7 GB, GPU) for refinement.
- `bin/llama/`: a llama.cpp release (Vulkan build), used for refinement.
- `data/`: history, settings, and refinement styles (`data/styles.json`, managed via right-click > Refinement styles…).

Run it with `python dictate.py` (it switches to `.venv` automatically). Delete the folder to remove the app completely.
If a SteamOS update breaks the app, run `./setup.sh` again; it rebuilds `.venv` for the new system Python.
To start it at login (optional, writes outside this folder): `cp dictate.desktop ~/.config/autostart/`

## Code
- `dictate.py`: floating icon, hotkey, recording, paste
- `stt.py`: transcription. The VAD strips non-speech, then Parakeet runs on the CPU.
- `windows.py`: History, the refinement style manager, and the style picker.
- `activewin.py` + `kwin_active.js`: tracks the focused window. KWin loads the script at runtime and unloads it on exit; it's never installed.
- `bench.py`: compares every `models/*.gguf` on your recent dictations: `python bench.py`.
- `refine.py`: the default cleanup (toggle with right-click > Refine text), then any additional style on top. Pressing the hotkey (or Alt) starts loading the model: the larger GPU model if the card has enough free VRAM and is under 30% busy, otherwise the smaller CPU model (`MODELS` in refine.py). It's unloaded after 30 s of no use. History keeps the raw transcript as "Original".
