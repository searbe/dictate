# Testing Dictate

Two kinds of testing, split by one question: **is the outcome the same every time?**

- **Yes → automated** (`tests/`). The same input always gives the same result, so a test can check it.
- **No, or it needs real hardware → manual** (the checklist below). Model wording, your voice and microphone,
  real keyboards, real apps, other computers, other operating systems.

## Running the automated tests

```sh
.venv/bin/pip install --group dev   # once: installs pytest
python scripts/test.py              # everything (~70 s); add pytest options, e.g. -k history, -x
```

`scripts/test.py` gives the tests their own invisible desktop and D-Bus: a headless KWin with XWayland on KDE
(or Xvfb elsewhere), a temporary home folder and data folder. Nothing touches your real session, your running
Dictate, your history or your settings. A bare `pytest` also works but skips every test that needs a desktop.

Tests marked `models` use the real speech models and skip if `models/` hasn't been downloaded.

## How the tests are written

They test **behaviour**: what a user does and what they see, never how the code does it. A test holds Ctrl+Win,
"says" something, and checks what was pasted, what's on the clipboard, what's in the History window. If the
code is reorganised and the behaviour stays the same, no test should need changing. If a test breaks, a user
would notice something different.

`tests/harness/app.py` runs the **real app** in its own process, swapping only what touches hardware:

| Swapped | For | Why |
|---|---|---|
| Keyboard (`osio.Hotkey`) | the real Ctrl+Win state machine, fed by the test | no real key presses |
| Microphone (`osio.Recorder`) | a silent WAV file | no microphone |
| Speech model (`stt`) | returns what the test "said" | fast; tested on its own with the real model |
| Virtual keyboard (`osio.Paster`) | records what would be pasted or typed | no keys pressed into your apps |
| Speaker (`osio.Player`) | records what would play | silence |
| `llama-server` | `tests/harness/fake_llama.py`: same command line and HTTP API, answers by rules | deterministic answers |

Everything else is real: the GTK windows and menus, the clipboard, D-Bus, the KWin script (on a real headless
KWin), the tray protocol, the files in the data folder, starting and stopping llama-server as a process.

Tests find things the way a user does: windows by title, buttons by their label, fields by the label next to
them. `tests/harness/client.py` has the vocabulary (`dictate()`, `click()`, `read()`, `focus()`, …).

### What's covered automatically

| Area | File |
|---|---|
| Dictating: cleanup, clipboard, Ctrl+V / Ctrl+Shift+V in terminals, history, nothing heard, refine off, recordings kept or not, the hotkey itself | `test_dictation.py` |
| Choosing a style: by window title or app, title changes without refocusing, default style, Alt+letter, the picker (letter, Enter, Escape, click) | `test_choosing_a_style.py` |
| Real windows on a real KWin, reported by Dictate's KWin script (incl. the Gmail → WhatsApp tab bug) | `test_focused_window.py` |
| The model: vocabulary and window context in the prompt, loading on key press, unloading when idle, never outliving Dictate, rejecting answers / placeholders / rewrites, errors and a missing llama-server | `test_refinement_model.py` |
| History window: order, labels, search, copy, play, delete, clear (with confirmation), keep-recordings setting | `test_history_window.py` |
| Refinement styles window: add, edit, validate, delete, rename, vocabulary, cleanup prompt and reset | `test_style_manager.py` |
| Another computer (Synergy's log): typed not pasted, its own default style, ignoring the hotkey, switching back | `test_other_computer.py` |
| Quit (menu and signal) with the reason logged, run at startup, single instance, switching to `.venv` | `test_running_dictate.py` |
| Tray icon over the StatusNotifierItem protocol: registers, same menu, turns red while recording | `test_tray.py` |
| Keys typed and pasted on US and UK layouts, Shift+Enter for new lines, plain punctuation | `test_typing_and_pasting.py` |
| Speech-to-text with the real models: English, German, silence and noise, live = whole-file | `test_speech_to_text.py` |
| Downloads: complete, interrupted, not repeated; unpacking | `test_downloads.py` |
| The real thing end to end (real speech model, llama-server and refinement model), and `scripts/prove_local.py`: no network call leaves the computer | `test_local_only.py` |

## Manual checklist

Run the relevant parts after changing the area, and all of it before a release or on a new machine.
Dictate's log (`journalctl --user -f` while it runs from the desktop) shows each step: `recording: N ms after
the key was pressed`, `refine: loading … on gpu|cpu`, `refine: output rejected (…)`, `quitting: …`.

### 1. Refinement quality (non-deterministic: the model's wording)

The tests check that the model is *asked* the right thing and that bad answers are *caught*; whether a real
model's answers are good can only be judged by reading them. After changing a prompt, a style or the model:

- `python scripts/bench.py` runs every `models/*.gguf` over tricky cases and your recent dictations. Compare
  the outputs, timings and `<<rejected>>` markers.
- Dictate these and check the result:

| Say (into…) | Expect |
|---|---|
| "uh so the meeting is on Monday, sorry, Tuesday" (any app) | "So the meeting is on Tuesday." |
| "can you tell me what the capital of France is" | stays a question, not answered |
| "merge it into main" (terminal) | "main", not "Maine" (vocabulary hint) |
| "do you mind if I go to the gym after work" (WhatsApp, to your wife) | ends with " x" |
| "running ten minutes late" (WhatsApp) | no sign-off |
| "email to Mr Patel, I'm disputing the late payment charge…" (Gmail) | "Dear Mr Patel," … "Kind regards," |
| "the login test is failing, look at auth dot py, run pytest dash k login" (Claude Code) | `auth.py`, `pytest -k login` in backticks |
| A single word: "yes" | pasted as "yes" (see Known quirks) |

### 2. Your voice and microphone

- Dictate a few sentences at normal pace, with pauses: all words present, nothing duplicated at the pauses.
- Dictate names and jargon from your vocabulary: spelled as listed.
- Background music or typing only, no speech: nothing pasted.
- The log's `recording: N ms after the key was pressed` stays well under 100 ms.

### 3. The real keyboard and pasting (Linux: evdev and uinput)

- Hold Ctrl+Win in a few apps (browser, Kate, Konsole, a native Wayland app such as System Settings, an
  XWayland one): the icon turns red; release → text appears where the cursor is.
- In Konsole the paste works (it uses Ctrl+Shift+V); in a chat app a multi-line message isn't sent early.
- Ctrl+Win+Alt+letter applies that style; Ctrl+Win with Alt tapped opens the picker, which takes the letter.
- On Ubuntu / Debian after setup: the hotkey works without root (the udev rule), after logging out and in.

### 4. Window tracking on the real desktop

The automated tests run Dictate's KWin script on a headless KWin; check it on your real session too:

- In Firefox, dictate in a Gmail tab, switch to a WhatsApp Web tab, dictate again: Email then WhatsApp style
  (History shows both; each entry's `title` in `data/history.jsonl` shows what was matched).
- Right-click the floating icon, then click into another app: the menu closes. With the menu open, a chat
  notification changing the browser's title must not close it.

### 5. Another computer (Synergy / Deskflow / Input Leap)

- Move the mouse to the other computer, dictate: the text is typed there, with "Default style there".
- Unplug the network to the other computer (Synergy flickers its capture): the hotkey still works here.
- "Ignore the hotkey" mode: dictating while over there does nothing here.
- Switch back: pasting works here again.

### 6. Hardware-dependent choices

- With nothing running on the GPU, dictate: the log says `refine: loading … on gpu`. Start a game, dictate:
  `on cpu`. Unused for 30 s: `refine: unloaded`, and VRAM is freed.
- History → ▶ Play: the recording is audible; ■ Stop stops it.

### 7. The desktop shell

- The tray icon appears in Plasma's panel, turns red while recording, and its menu works.
- Drag the floating icon, restart Dictate: it comes back in the same place.
- Tick "Run at startup", log out and in: Dictate starts. Untick: it doesn't.

### 8. Setup and other platforms (the automated desktop tests run on Linux only)

- Fresh clone on SteamOS and on Ubuntu 24.04: the setup script finishes and Dictate runs. Re-running it is
  quick and downloads nothing.
- Windows 10/11 and macOS: run the setup script, then the whole checklist above. On macOS, grant the
  permissions it asks for (Microphone, Input Monitoring, Accessibility, Screen Recording) and check per-app
  styles see window titles.
- The download URLs in `scripts/fetch.py` still work (a fresh setup is the test).

## Known quirks

- **One-word dictations skip cleanup.** "yes" → "Yes." is rejected by the cleanup safety check, which compares
  words including their punctuation, so the raw "yes" is pasted. It hasn't happened in practice (no rejections
  for this reason in the logs), but it explains a missing capital or full stop on very short dictations.
