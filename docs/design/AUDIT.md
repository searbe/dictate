# Dictate's UI before the revamp: an audit

Screenshots of every surface as it was are in [before/](before/). What they show, and what's wrong with it.

## Surfaces

| Surface | What it is | Screenshot |
|---|---|---|
| Floating icon | 52 px round button, always on top: grey idle, red with pulse rings while recording, a spinner while transcribing, a blue (grey when paused) ring in transcribe mode | `icon-states-4x.png` |
| Menu | Right-click on the icon (and the tray icon): 11 items, two submenus | — |
| History | A window of cards, one per dictation, each with Play, Copy, Original and Delete | `history.png` |
| Refine (style picker) | A window after Ctrl+Win with Alt: the cleaned-up text and a button per style | `picker.png` |
| Refinement styles | Sidebar of styles, a form and a monospace prompt editor | `styles.png` |
| Transcripts | List of transcripts, the transcript, its topics; Stop/Pause while recording | `transcripts.png`, `transcripts-saved.png` |
| Voices | A checkbox, an explanation and a list with Forget buttons | `voices.png` |
| Still transcribing | A panel beside the icon | `reminder.png` |
| Rename a voice, confirm delete | Stock GTK message dialogs | — |

## What's wrong

1. **Five separate windows, each its own layout.** History, styles, transcripts and voices open as separate windows
   with their own header-bar arrangements; the app has no home. Getting from a transcript to its voices, or from
   the picker to the styles, opens another window.
2. **Header bars overloaded and inconsistent.** History puts a destructive "Clear history", a "Keep recordings"
   setting and search in the title bar; styles puts Delete on the left and Save on the right; transcripts swap
   their buttons by state. Settings live in title bars and menus rather than one place.
3. **Every row shouts.** Each history card shows 4–5 filled buttons all the time (Play, Copy, Original, Delete
   in red), so a list of ten is fifty buttons. Red is used for every Delete, everywhere, at full strength.
4. **No type scale.** Sizes are ad hoc (8.5, 9, 9.5, 10.5, 11 pt), headings are bold body text, form labels are
   upper-case in one window and sentence case elsewhere; the prompt editor is monospace.
5. **No spacing system.** Margins of 5, 6, 8, 10, 12, 14 and 16 px are mixed; corner radii of 5, 6, 8, 10 and 12.
6. **Colour without roles.** The accent indigo is used for buttons, chips, the speaker's name and selection; topics
   bring eight more colours; red appears as text, fill and border. Nothing says what a colour means.
7. **The floating icon is always 52 px,** idle or not, and says nothing about what it's doing beyond colour: no
   level while listening, no elapsed time while transcribing a call.
8. **Stock dialogs** (rename, confirm) come from the GTK theme and look like another app.
9. **Text-only buttons and Unicode glyphs** (▶, ■, ⏎, ✓) stand in for icons, rendered differently by each font.
10. **Copy is long-winded in places** ("Which additional refinement style would you like to apply?") and the
    picker preselects its text, so it opens highlighted.

## Worth keeping

- The dark, quiet palette and the single indigo accent.
- Cards with soft borders; the key badges (S, W, E, A) for styles.
- Topic colours tying the topic list to the transcript.
- The floating icon as the one always-present control (people learn where it is).
