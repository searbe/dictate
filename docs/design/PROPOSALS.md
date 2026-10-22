# Redesign: proposals, the choice, and the plan

What's wrong today is in [AUDIT.md](AUDIT.md). The rules everything follows are in [DESIGN.md](DESIGN.md).

## What the best tools do

From the research into Wispr Flow, OpenWhispr, Superwhisper, VoiceInk, Granola, Otter, Krisp and the Mac
utilities people point to (Raycast, Linear, CleanShot X, Apple's HIG):

- **One control that changes shape.** Wispr Flow's bar, OpenWhispr's pill (a 40 px circle that becomes a 98×36
  capsule) and VoiceInk's 184×40 capsule are small when idle and grow only while something's happening.
  Superwhisper's users complain its full window "covers a ton of the screen" and ask to lock its mini mode.
- **A level meter while listening,** not a pulsing colour: 9–15 thin bars, still when it's quiet, which also
  shows the microphone is live. Red only for a dot or a stop button.
- **Processing is quiet:** the bars dim or freeze and a gentle pulse plays; the pasted text is the success
  signal. No spinners.
- **One home window** with a sidebar (Flow's Hub: Home, Meetings, Dictionary, Snippets, Settings; OpenWhispr's
  Control Panel), not a window per feature.
- **Lists that don't shout:** rows grouped by day, actions appear on hover (Flow, Linear, Raycast).
- **Temporary things as HUDs:** small translucent cards (CleanShot's thumbnail, Raycast's toasts) rather than
  dialogs.
- **Restraint:** one accent colour, near-grey neutrals, a tight radius scale, 8-point spacing, two type
  weights, short purposeful motion (≈300 ms morphs on `cubic-bezier(0.2, 0, 0, 1)`).
- **Meetings, à la Granola and Otter:** live text with speakers in muted tints, a quiet rail of topics that
  link back to their moment, and controls in one slim bar. Never a modal.

## Three directions

### A. Capsule and Hub

The floating icon becomes a **capsule** that is a 36 px dot while idle and grows only while it's working:

```
idle            listening                       processing        transcribing a call
 ( ● )      ( ● ▁▃▆█▆▃▁▂▅ 0:04 )            ( ● · · · )        ( ● 12:34 · Release date )
 36 px          ~150×36, live level bars        bars dim, dots    a red dot, elapsed time, topic now
```

- Hovering shows a hint; right-click keeps the short menu; click while transcribing opens the transcript.
- Everything else lives in **one window, "Dictate"**, with a sidebar: **History, Transcripts, Styles, Voices,
  Settings.** The window's title is the page you're on.
- History becomes **rows grouped by day** (Today, Yesterday, Tue 20 Oct) with search at the top; Play, Copy,
  Original and Delete are **icon buttons that appear on hover**.
- Transcripts keep their three panes, with a **status bar** at the top while recording (● Recording · 12:34 ·
  Pause · Stop) and quiet topic cards in the rail.
- **Settings** gathers what's now scattered over menus and title bars: refine text, default style, keep
  recordings, the other computer, run at startup.
- The style picker, the rename and confirm dialogs and the still-transcribing reminder become **HUD cards**:
  dark, translucent where KWin can blur, one accent.

*Footprint:* 36 px idle (from 52), about 150 px wide only while you speak. *Risk:* the capsule grows inside a
fixed transparent window, so clicks in its empty part must pass through (input shape).

### B. Edge dock

Nothing floats while idle. A 4 px **handle** sits on a screen edge (bottom centre by default); dictating slides
out a capsule from it (like a notch), and transcribe mode keeps a slim timer tab there. The tray icon is the way
in; the Hub is as in A.

*Footprint:* smallest. *Against:* the icon people have learned to find and drag disappears; an edge handle is
hard to hit on a multi-monitor desk and fights panels and docks; clicking the icon to see a call's transcript
(which the still-transcribing reminder now teaches) loses its target. Needs per-edge layouts.

### C. Companion

The capsule of A, plus a **drawer** that opens from it during calls: a narrow live view of the conversation's
topics and the last few lines, so a call needs no window at all. Settings, history and styles in the Hub.

*Footprint:* small when dictating, ~380×420 while a call runs with the drawer open. *Against:* a second always-on-
top surface during calls (when screens are shared); duplicates the Transcripts page; most of its value comes
once A exists.

## The choice: A, Capsule and Hub

Against the criteria (modern, sleek, little screen space on a modern desktop):

| | Modern | Sleek | Screen space | Keeps what works | Cost |
|---|---|---|---|---|---|
| A. Capsule and Hub | ✓ the pattern every leading tool has converged on | ✓ one window, one control | 36 px idle; grows only while working | ✓ the icon stays where people put it | Medium |
| B. Edge dock | ✓ | ✓ | Least | ✗ loses the icon; awkward with panels and several screens | High |
| C. Companion | ✓ | ~ a second surface in calls | More during calls | ✓ | High, and needs A first |

A wins: it has B's restraint without hiding the one control, and C's drawer can be added to it later.

## The plan

1. **Design system in code** (`dictate/design.py`): the tokens of DESIGN.md (colours for dark and light, type,
   spacing, radii, motion) generate the app's CSS; one set of components (buttons: primary, quiet, danger,
   icon; chips; key badges; rows; section headers; fields; switches; HUD cards; the sidebar); a small icon set
   drawn in cairo so icons look the same on every desktop theme. Follows the system's light or dark
   preference, live.
2. **The capsule** (`app.py`): a fixed transparent window with the capsule drawn in cairo; idle dot, listening
   with level bars from the recording, processing pulse, transcribing timer and topic; morphs at 280 ms;
   clicks outside the shape pass through.
3. **The Hub** (`hub.py` and `pages/`): one window with the sidebar and five pages, built from the existing
   windows' logic: History (grouped rows, hover actions), Transcripts (status bar, quiet topics), Styles
   (sentence-case form, prompt in the body font), Voices, Settings (new).
4. **HUDs:** the style picker, the rename and confirm dialogs and the still-transcribing reminder rebuilt on one
   HUD card; KWin blur behind them where available.
5. **Menu and tray** keep their items (they're quick to reach), with "Open Dictate" first.
6. **Tests** keep describing what a user sees: window titles become page titles, buttons are found by their
   label or, for icon buttons, their tooltip.
7. **Docs:** screenshots regenerated; README updated.

Since: History was renamed **Dictations**, so it reads as a pair with Transcripts (both are things you made).
