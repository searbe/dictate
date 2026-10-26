# Testing Dictate

There are two kinds of testing:

- **Automated** (`tests/`), for everything that gives the same result from the same input.
- **Manual** (the checklist below), for what varies or needs real hardware: the model's wording, your voice and
  microphone, real keyboards, real apps, other computers, other operating systems.

## Running the automated tests

```sh
.venv/bin/pip install --group dev   # once: installs pytest and ruff
python scripts/test.py              # everything (about 3 min); add pytest options, e.g. -k dictations, -x
```

`scripts/test.py` gives the tests their own invisible desktop and D-Bus: a headless KWin with XWayland on KDE
(or Xvfb elsewhere), a temporary home folder and data folder. Nothing touches your real session, your running
Dictate, your dictations or your settings. A bare `pytest` also works but skips every test that needs a desktop.

Tests marked `models` use the real speech models and skip if `models/` hasn't been downloaded.

## How the tests are written

They test **behaviour**: what a user does and what they see, never how the code does it. A test holds Ctrl+Win,
"says" something, and checks what was pasted, what's on the clipboard, what's in Dictations. If the
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

Tests find things the way a user does: windows by title (the Dictate window's is the page shown), buttons by
their label or, for icon buttons, the tooltip that names them, fields by the label above them, switches by their
setting's title. `tests/harness/client.py` has the vocabulary (`dictate()`, `click()`, `read()`, `focus()`, …).

### What's covered automatically

| Area | File |
|---|---|
| Dictating: cleanup, clipboard, Ctrl+V / Ctrl+Shift+V in terminals, the Dictations list, nothing heard, refine off, recordings kept or not, the hotkey itself, another key with it being another app's shortcut | `test_dictation.py` |
| Choosing a refinement: by window title or app, title changes without refocusing, default refinement, Alt+letter (one that's no refinement's being another app's shortcut), the picker (letter, Enter, Escape, click) | `test_choosing_a_refinement.py` |
| Real windows on a real KWin, reported by Dictate's KWin script (incl. the Gmail → WhatsApp tab bug) | `test_focused_window.py` |
| The model: vocabulary and window context in the prompt, loading on key press, unloading when idle, never outliving Dictate, rejecting answers / placeholders / rewrites, errors and a missing llama-server | `test_refinement_model.py` |
| Dictations: grouped by day, labels, search, copy, play, delete, clear (with confirmation), the keep-dictation-recordings setting | `test_dictations_page.py` |
| Refinements: add, edit, validate, delete, rename, vocabulary, cleanup prompt and reset, asking to save unsaved changes | `test_refinements_page.py` |
| Another computer (Synergy's log): typed not pasted, its own default refinement, ignoring the hotkey, switching back | `test_other_computer.py` |
| Quit (menu and signal) with the reason logged, the microphone never left recording (quitting mid-dictation, or crashing mid-recording), run at startup, single instance, switching to `.venv` | `test_running_dictate.py` |
| Tray icon over the StatusNotifierItem protocol: registers, same menu, turns red while recording, its tooltip saying how long it has been transcribing (paused or not) and the topic now | `test_tray.py` |
| Keyboards coming and going (Linux): Ctrl+Win still works after one is unplugged, one plugged in later (or dropping out and coming back) works, unplugged mid-dictation counts as let go, Dictate's own virtual keyboard not watched | `test_keyboards.py` |
| Microphone: the system's default one used until the order on the Settings page is changed, moving one up records with it, the next one used while the preferred one is unplugged (and it again once it's back), transcribe mode too, forgetting one that isn't connected | `test_microphones.py` |
| Keys typed and pasted on US and UK layouts, Shift+Enter for new lines, plain punctuation | `test_typing_and_pasting.py` |
| Speech-to-text with the real models: English, German, silence and noise, live = whole-file | `test_speech_to_text.py` |
| Downloads: complete, interrupted, not repeated; unpacking | `test_downloads.py` |
| Dictate's files: saved whole or not at all (a failed save leaves the old file), missing or damaged ones read as defaults, recordings deleted when their time is up but never one being recorded | `test_files.py` |
| Transcribe mode: what's being said shown before the pause and replaced by the whole stretch (not saved; not while muted or paused), a stretch cut between voices loses no words (real models), the Ctrl+Win, Win gesture (and not mistaking a dictation for it), speakers and microphone labelled, paragraphs, stop / Stop / menu, closing the window carries on, pause, dictating meanwhile, echoes (the same words at once, and with the real models a made-up room's echo), playback from Dictations, recordings kept or not, a transcript where nothing was heard not kept, transcript recordings kept for their own setting, the real model on speakers audio | `test_transcribe_mode.py` |
| Transcripts: listed newest first with when and how long, the recording at the top and kept up to date while reading others, reading one, copy, delete (with confirmation) with its recordings, playing the call back (only while its recordings are kept; not while it's recorded), none yet, clicking the capsule while recording | `test_transcripts_window.py` |
| Playing back: a transcript's paragraph (its button shown while it's hovered) playing only to the next paragraph, highlighted with its Stop, the whole call from Play with the highlight following it, another paragraph taking over, Stop while it's still being prepared (nothing plays), only the last of several requests played, the window closed or another transcript shown stopping it, a dictation's playback stopping a transcript's, the copy mixed to play from deleted with the transcript or its recordings | `test_playing_back.py` |
| Waiting for the graphics card: a stopped call's final summary waiting while it's busy (a sand timer on the capsule, the tray's tooltip, saved as waiting), done on it once it's free, not waiting when it's free, the pop-up from the sand timer with Use the CPU and Keep waiting, the transcript's summary saying so (with Use the CPU), done after Dictate quits and starts again (also quitting mid-call), a transcript deleted while it waits staying deleted, slices waiting too | `test_waiting_for_gpu.py` |
| Sharing with Claude Code: off until turned on (refused without asking), the window saying what it's for and that it's sent to Anthropic, those that mention it first, nothing ticked, only what's ticked shared (summary unless the whole transcript is chosen), refusing, closing and Escape share nothing, one request at a time, Dictate not running, the socket yours only, Settings installing the skill and the read block and turning the block off and on (nothing else in Claude Code's settings changed, and left alone if they aren't JSON) | `test_sharing_with_claude.py` |
| Echoes: the speakers heard again by the microphone (in made-up rooms, quieter or later) told from you speaking, alone or over them | `test_echo.py` |
| Topics: listed beside the transcript with who brought each up and who else spoke on it, the current one marked, carried on when the conversation goes back to one, a new paragraph where the topic changes, small talk left out, saved at the top of the transcript (including what was said last, when it's stopped), the transcript carrying on when the model fails, a warning while the less reliable model is used (graphics card busy, or none) and once saved, switching to the better one once the graphics card is free but not mid-dictation, topics that turn out to be one subject merged (only if the model says so again about each pair, and not by the less reliable model) | `test_topics.py` |
| Still transcribing: closing the window while recording says it carries on and every way to stop it (once a day), Stop now, Keep going, a desktop notification when the capsule isn't on screen, after a while with nothing heard, paused and saying so (beside the capsule, or in the middle of the screen), nothing recorded or transcribed while paused, the icons flashing at a sound meanwhile (and the alert brought to the front by clicking the capsule, or by Ctrl+Win, which doesn't dictate but says why), the alert closed only by Resume (paused again only after another while) or Stop now, and closed any other way, stopped | `test_still_transcribing.py` |
| Live summary: the Summary tab beside Topics, kept up to date with only what's new sent each time, the final pass when it's stopped saved at the top of the transcript, a long conversation summarised a slice at a time and the slices merged (the earliest condensed first when they don't fit together), an answer cut off by the model not taken, a saved transcript's summary, its prompt changed and reset in Refinements | `test_summary.py` |
| Grouping voices into people on a call's worth of made-up voiceprints: one voice each, short parts never someone new, numbers kept when one is named | `test_voice_grouping.py` |
| Voices: told apart, named live or after the call, merged by naming two the same, remembered only when turned on (live and after the call), listed and forgotten, all forgotten when turned off, "Them" without the voice model | `test_voices.py` |
| The real thing end to end (real speech model, llama-server and refinement model), and `scripts/prove_local.py`: no network call leaves the computer | `test_local_only.py` |

## Manual checklist

Run the relevant parts after changing the area, and all of it before a release or on a new machine.
Dictate's log (`journalctl --user -f` while it runs from the desktop) shows each step: `recording: N ms after
the key was pressed`, `refine: loading … on gpu|cpu`, `refine: output rejected (…)`, `quitting: …`.

### 1. Refinement quality (non-deterministic: the model's wording)

The tests check that the model is *asked* the right thing and that bad answers are *caught*; whether a real
model's answers are good can only be judged by reading them. After changing a prompt, a refinement or the model:

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
- With two microphones connected, move the one that isn't the system's default to the top in Settings: the log says
  `microphone: <its name>` at the next dictation, and the recording is from it (play it back from Dictations).
  Unplug it: the next dictation records the next one in the list.

### 3. The real keyboard and pasting (Linux: evdev and uinput)

- Hold Ctrl+Win in a few apps (browser, Kate, Konsole, a native Wayland app such as System Settings, an
  XWayland one): the capsule grows and its level meter follows your voice; release → three dots, then the text
  appears where the cursor is.
- In Konsole the paste works (it uses Ctrl+Shift+V); in a chat app a multi-line message isn't sent early.
- Ctrl+Win+Alt+letter applies that refinement; Ctrl+Win with Alt tapped opens the picker, which takes the letter.
- On Ubuntu / Debian after setup: the hotkey works without root (the udev rule), after logging out and in.

### 4. Window tracking on the real desktop

The automated tests run Dictate's KWin script on a headless KWin; check it on your real session too:

- In Firefox, dictate in a Gmail tab, switch to a WhatsApp Web tab, dictate again: Email then WhatsApp refinement
  (Dictations shows both; each entry's `title` in `data/dictations.jsonl` shows what was matched).
- Right-click the capsule, then click into another app: the menu closes. With the menu open, a chat
  notification changing the browser's title must not close it.

### 5. Another computer (Synergy / Deskflow / Input Leap)

- Move the mouse to the other computer, dictate: the text is typed there, with "Default refinement there".
- Unplug the network to the other computer (Synergy flickers its capture): the hotkey still works here.
- "Ignore the hotkey" mode: dictating while over there does nothing here.
- Switch back: pasting works here again.

### 6. Hardware-dependent choices

- With nothing running on the GPU, dictate: the log says `refine: loading … on gpu`. Start a game, dictate:
  `on cpu`. Unused for 30 s: `refine: unloaded`, and VRAM is freed.
- Dictations → Play (hover an entry): the recording is audible; Stop stops it.
- Transcripts → Play on a call with its recordings kept: both sides are audible, mixed. Clicking a paragraph's
  time plays from there.

### 7. Transcribe mode (real speakers, microphone and calls)

- Play a video with speech, start transcribe mode (Ctrl+Win, lift Win, Win again): its words appear under
  "Speaker 1" a moment after each pause, accurately. Speak: under "Me". The Dictate window doesn't take focus.
- On a call on headphones, and again on the speakers: the other person isn't also written as "Me", and what you
  say (on its own, and over them) still is. While it runs, "Dictate: microphone without the speakers" is listed
  among the microphones (PipeWire's echo canceller); it's gone once you stop.
- Dictate into another app meanwhile: pasted as usual, not in the transcript.
- An hour-long session: the transcript keeps up, CPU use stays reasonable, the file in `data/transcripts/` is
  complete after Stop.
- Switch the output device (e.g. headphones on) mid-session: still transcribed (the default output's monitor).
- A call or podcast with 2–4 people (a long one too, 15 min or more): as many "Speaker N" as there are people, each
  mostly keeping theirs, including in quick back-and-forth; note where it slips (talking over each other, one-word
  answers). Sentences aren't broken up at short pauses. The greyed-out preview keeps up within about a second
  of someone speaking, and grows from the start of what they're saying (it doesn't jump to its last few words),
  until it's replaced by the whole stretch transcribed. Interjections ("yeah", "no") and a quick reply in the
  middle of someone's turn go to the person who said them. With the call on speakers (no headphones), nothing
  the speakers said turns up as yours, and what you say over them does.
- After changing `stt.py`, `voices.py`, `echo.py` or `transcript.py`, replay a recorded call (one whose
  recordings are still kept) with `python scripts/replay_call.py "data/transcripts/<stem>"` and read who was
  given what, and whether anything the speakers said turned up as "Me".
- After changing `voices.py`, run `python scripts/bench_voices.py LibriSpeech/dev-clean` (download it from
  openslr.org/12) and compare with the last run: speaking time labelled right 98.6% / 94.3% (with pauses, full
  quality / phone), 89.8% / 81.5% (quick replies); the right number of people in 83% / 75% and 75% / 67% of
  conversations. With `--by-word` (as transcripts do, once two voices are known; slower, as it transcribes too):
  97.5% / 93.8%, 89.3% / 80.3%; 83% / 79% and 75% / 62%. These are a little lower because the benchmark's
  conversations are spliced from audiobook readings, with no interjections; word-by-word is what attributes a
  "yeah" or a quick answer in the middle of someone's turn on a real call.
- With Remember voices on: name someone, and in a later call with them they're named from their first stretch.
- Close the Dictate window while transcribing: the reminder appears beside the capsule, on its screen
  (try the capsule near the right edge: it goes on the left); Stop now stops it. With it off screen, a desktop
  notification says it instead, and its Stop now button works.
- The live summary, on a real call: it appears within a minute, changes about every half a minute, and keeps
  every subject as it grows; Agreed and Action points hold only what was said; the final pass after Stop reads
  well and is marked final.
- Topics, on a real call: the first is listed within half a minute, and the list reads as what was discussed,
  in order, with the one being talked about marked "Now" within about half a minute of the subject changing
  (which topic, and who brought it up, can slip on a short reply or a quick change of subject). The
  transcript's colours match. After changing `topics.py`'s prompt, use
  `python scripts/bench_topics.py` on a few saved transcripts and read the results.

### 8. The desktop shell

- The tray icon appears in Plasma's panel, turns red while recording, and its menu works.
- Drag the capsule, restart Dictate: it comes back in the same place. Near the right half of a screen it grows
  to the left. Only the capsule takes clicks: just beside it, the window underneath gets them. A click (no drag)
  while transcribing opens Transcripts on the recording; a drag doesn't.
- The look ([design/DESIGN.md](design/DESIGN.md)): switch Plasma between light and dark (System Settings →
  Colours): Dictate follows at once. The refinement picker and reminders blur what's behind them (KWin's blur on).
  With animations off (System Settings → Animation speed → Instant), the capsule changes size without morphing.
- Tick "Run at startup", log out and in: Dictate starts. Untick: it doesn't.

### 9. Setup and other platforms (the automated desktop tests run on Linux only)

- Fresh clone on SteamOS and on Ubuntu 24.04: the setup script finishes and Dictate runs. Re-running it is
  quick and downloads nothing.
- Windows 10/11 and macOS: run the setup script, then the whole checklist above. On macOS, grant the
  permissions it asks for (Microphone, Input Monitoring, Accessibility, Screen Recording) and check per-app
  refinements see window titles.
- The download URLs in `scripts/fetch.py` still work (a fresh setup is the test).

## Known quirks

- **One-word dictations skip cleanup.** "yes" → "Yes." is rejected by the cleanup safety check, which compares
  words including their punctuation, so the raw "yes" is pasted. It hasn't happened in practice (no rejections
  for this reason in the logs), but it explains a missing capital or full stop on very short dictations.
