<img src="dictate/icon.png" width="72" align="right" alt="">

# Dictate

**Talk instead of typing, in any app, and get text that reads like you wrote it.** Hold Ctrl+Win, say what you
mean, let go: a second later it's pasted, the ums gone, your corrections applied, and formatted for where it's
going. Leave it running on a call and it writes the call down as it happens, who said what, with a live list of
topics and a summary that's ready when the call ends.

Everything runs on your own computer. Nothing you say leaves it, and you can [check that for
yourself](docs/TECHNICAL.md#checking-that-its-local-only).

![The capsule: idle, dictating, working, transcribing a call](docs/capsule-states.png)

## Say it the way you'd say it

You don't speak in finished sentences, and you don't need to. Dictate's cleanup takes out the filler, the
repeated words and the false starts, keeps the corrections you make as you go, and fixes the words speech
recognition gets wrong. It keeps your wording: it tidies, it doesn't rewrite.

Every dictation is kept, so you can see exactly what was done to it. Click **Cleanup**:

![What cleanup changed: "so I think we should like move the the stand up to ten thirty because uh half the team is in the other time zone sorry Tuesday's stand up not every day"](docs/cleanup-step.png)

That's real output from the local model: "sorry, Tuesday's stand-up, not every day" became "the Tuesday
stand-up", where it belongs.

## Right for where it's going

A message to a colleague, an email, a prompt for an AI agent: each reads differently. **Refinements** reshape
cleaned-up text for its destination, and they run on their own: the Slack refinement in Slack, the email one in
your mail client, matched by app name or window title. Here's the same dictation after Slack's:

![What the Slack refinement changed: "ten thirty" became "10:30"](docs/refinement-step.png)

Want a different one this time? Hold **Alt** while you speak and pick one when you let go, or press **Alt+S**,
**Alt+E**… for one directly. Write your own in plain words. Teach it the names and terms you use, spelled your
way, in **Vocabulary**.

| Pick a refinement (tap Alt while dictating) | Your refinements |
|---|---|
| ![The refinement picker](docs/picker.png) | ![Refinements](docs/refinements.png) |

## Your calls, written down as they happen

Hold Ctrl+Win, lift Win and press it again, and Dictate starts transcribing everything your computer plays and everything you say into
your microphone: a Meet or Zoom call, a webinar, a podcast. It's built for the moment you're on a call and need
to keep up.

- **Who said what.** Each voice is told apart, word by word, so even a quick "yeah" in the middle of someone
  else's sentence goes to the right person. Click a name to rename them.
- **Live topics.** Every 20 seconds or so the topics are brought up to date: each in its own colour, with who
  raised it, what was said, and the one being talked about now. The transcript is tinted to match, so you can see
  where the conversation went at a glance. Click a topic to jump to it.
- **A live summary.** Overview, what was discussed and who thought what, what was agreed, action points and open
  questions, kept up to date as the call goes on, and given a careful final pass when you stop. Change the prompt
  to suit your meetings.
- **No headphones needed.** Your microphone hears the call through your speakers too; Dictate recognises that
  echo and leaves it out, so the other side isn't written down twice as you.
- **Play it back.** Click any paragraph's time to hear that moment again.

| Topics, as the call goes on | The live summary |
|---|---|
| ![Transcripts with live topics](docs/transcripts.png) | ![Transcripts with the live summary](docs/summary.png) |

Transcripts are plain Markdown files, with the summary and topics at the top. Take them anywhere.

## Knows who's on the call

Name someone once and, if you turn it on, Dictate remembers their voice and names them in your next call
automatically. It's off unless you switch it on, the voiceprints stay on this computer, and turning it off
forgets every one. (A voiceprint can identify someone: ask people first.)

![Voices](docs/voices.png)

## Stays out of your way

Dictate lives in a small capsule on your desktop: just a dot until you use it. While you speak it shows a live
level meter, so you know it hears you; while it works, three quiet dots; while it's transcribing a call, the time
and the topic being discussed, and one click opens the transcript. Close the window mid-call, or go quiet for
ten minutes, and a reminder appears beside the capsule, so you don't leave it running by accident.

Everything else is in one window: your **Dictations** (each with its recording, to play back), **Transcripts**,
**Refinements**, **Voices** and **Settings**. Dark or light, following your desktop.

| Every dictation, and what was done to it | Settings |
|---|---|
| ![Dictations](docs/dictations.png) | ![Settings](docs/settings.png) |

## Private, and you can prove it

Speech recognition, cleanup, refinements, topics, summaries, voices: all of it runs locally, on your graphics
card if it's free and your processor if not. There's no account, no subscription and no cloud. The models are
downloaded once, during setup, and after that Dictate never touches the network.

Don't take our word for it: `python scripts/prove_local.py` runs Dictate in a sandbox with no network, records
every network call of every process, and only says `LOCAL ONLY` if all of them stayed on your computer.

## Fast

The text is transcribed while you speak, so it's ready about a tenth of a second after you let go. Cleanup takes
about a second on a graphics card (1–2 seconds on a recent processor). The model loads while you're talking, and
lets go of the graphics card after half a minute unused, so it doesn't sit on your GPU while you game.

## Get started

On Linux (SteamOS / KDE Plasma, or Ubuntu 24.04+):

```sh
git clone https://github.com/searbe/dictate.git
cd dictate
./setup.sh
python dictate.py
```

Setup downloads the models (about 10 GB) into this folder, and everything stays in it: delete the folder and
Dictate is gone. Tick **Run at startup** in its menu to have it there every time you log in. Windows and macOS
setups are included but untested; see [the technical details](docs/TECHNICAL.md) for those, and for the
recommended hardware.

## At a glance

| | |
|---|---|
| **Ctrl+Win** (hold) | Dictate; let go to paste |
| **+ Alt** (tap, while holding) | Pick a refinement when you let go (Enter pastes as is, Esc only copies) |
| **+ Alt+letter** | Use that refinement |
| **+ any other key** | It's another app's shortcut (e.g. Ctrl+Win+→): nothing is pasted |
| **Ctrl+Win, then Win again** | Start or stop transcribing a call: hold Ctrl+Win, lift Win, press it again (or **Stop**, or the menu) |
| **Right-click the capsule** | The menu: refine text on or off, the default refinement, your dictations, transcripts and settings |

You can dictate as usual while a call is being transcribed; your dictations stay out of the transcript. On Linux,
terminals get Ctrl+Shift+V. While your keyboard controls another computer through Synergy or similar, the text is
typed there instead.

## More

- [The technical details](docs/TECHNICAL.md): how it works, hardware, setup on each platform, the code, your data.
- [Testing](docs/TESTING.md) and [the design system](docs/design/DESIGN.md), for changing it.

MIT licensed: see [LICENSE](LICENSE). The models it downloads have their own licenses, listed in
[the technical details](docs/TECHNICAL.md#licenses).
