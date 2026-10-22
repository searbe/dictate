# Dictate's design system

Every surface of Dictate follows this. The values live in code in `dictate/design.py` (which generates the app's
CSS from them); use its names, never raw colours or sizes. When something new needs a value that isn't here, add
it here and there first. Why it looks like this: [PROPOSALS.md](PROPOSALS.md).

## Principles

1. **Small until it's needed.** The capsule is a dot while idle and grows only while it works. Windows open when
   asked for and say one thing at a time.
2. **One home.** Everything that isn't the capsule or a moment's HUD is a page of the Dictate window.
3. **Neutral, with colour only for meaning.** Neutral greys carry the interface; each colour has one meaning
   (see Colour). Actions appear when you reach for them (hover), except the one primary action of a view.
4. **One accent.** Indigo is the only brand colour: selection, the primary button, focus, links, live state.
5. **Native to the desktop.** Follows the system's light or dark preference, live; uses the system font when
   Inter isn't installed; no in-app theme switch.
6. **Motion only for changes.** Shape changes morph; nothing loops except a live level meter or a pulse
   while waiting.
7. **Plain words.** Sentence case everywhere, verbs on buttons, the shortest phrasing that's still clear.

## Colour

Tokens, by role. Dark is the default; light mirrors every role.

| Token | Role | Dark | Light |
|---|---|---|---|
| `bg` | Window background | `#111214` | `#f6f6f7` |
| `surface-1` | Sidebar, rails, HUD body | `#17181b` | `#efeff1` |
| `surface-2` | Cards, inputs, rows on hover | `#1d1f23` | `#ffffff` |
| `surface-3` | Controls at rest, selected nav item | `#25272c` | `#e9e9ec` |
| `surface-4` | Controls hovered or pressed | `#2e3137` | `#dfdfe4` |
| `raised` | The chosen part of a segmented control | `#3a3d45` | `#ffffff` |
| `line` | Hairlines and borders | white 7 % | black 8 % |
| `line-strong` | Focused or emphasised borders | white 14 % | black 16 % |
| `text` | Primary text | `#ececef` | `#1b1c1f` |
| `text-2` | Secondary text, icons at rest | `#a4a7b0` | `#5d6068` |
| `text-3` | Hints, timestamps, placeholders | `#6f727b` | `#8b8e96` |
| `accent` | Selection, primary button, focus, live | `#7c8cff` | `#5b6cff` |
| `accent-hover` | Primary button hovered | `#96a3ff` | `#4a5bf0` |
| `accent-weak` | Accent backgrounds (selected chip, focus ring) | accent 16 % | accent 14 % |
| `on-accent` | Text on accent | `#ffffff` | `#ffffff` |
| `record` | Recording now (the dot, the stop) | `#ff5a5f` | `#e5484d` |
| `danger` | Destructive text | `#ff7a7a` | `#d93d42` |
| `danger-weak` | Destructive hover | danger 14 % | danger 10 % |
| `warning` | Needs attention | `#ffb547` | `#b86e00` |
| `warning-weak` | Warning backgrounds | warning 13 % | warning 14 % |
| `hud` | HUD cards (translucent) | `#17181b` at 88 % | `#fafafb` at 90 % |

**Rules.**
- Red means recording, and only that, at full strength. Destructive actions are `danger` *text* on a quiet
  button, filled only on hover; they always ask first.
- Accent appears at most once per view as a filled shape (the primary button or the selection).
- **Topic colours** are the only other hues: eight muted tints (`topic-0` … `topic-7`), used as a 3 px edge, a
  dot, the topic's name, and a 9 % tint behind its paragraphs. Never as button fills.

## Type

The family is **Inter** if installed, else **Noto Sans** (KDE's), else the system sans. Two weights: 400 and 600.
Numbers that change (timers, counts) use tabular figures.

| Token | Size / line | Weight | Use |
|---|---|---|---|
| `headline` | 20 / 26 | 600 | Page titles |
| `title` | 15 / 20 | 600 | Section titles, HUD titles, card titles |
| `body` | 13 / 18 | 400 | Everything by default; transcripts and prompts too |
| `body-strong` | 13 / 18 | 600 | Names, the selected item |
| `small` | 12 / 16 | 400 | Secondary text, descriptions, field labels (600) |
| `caption` | 11 / 14 | 400 | Timestamps, chips, meta lines, group headers (600) |

No upper-case labels; no monospace except for keyboard keys.

## Space, size and shape

- **Spacing:** multiples of 4: `4, 8, 12, 16, 24, 32`. Inside a control 8 or 12; between related items 8;
  between groups 16 or 24; page padding 24.
- **Radii:** `r-xs 4` (key badges) · `r-sm 6` (buttons, inputs, chips, nav items) · `r-md 8` (rows, cards) ·
  `r-lg 12` (HUDs, popovers, panels) · `r-full` (the capsule, dots, avatars).
- **Heights:** controls 28 (small 24); inputs 32; nav items 32; rows at least 40.
- **Elevation:** pages are flat (no shadows, hairlines only). HUDs float: a 1 px `line` border, a 1 px inner top
  highlight (white 6 %) and a soft shadow `0 8 24` black 35 %; KWin blurs what's behind them where it can.

## Motion

| Token | Duration | Curve | Use |
|---|---|---|---|
| `morph` | 280 ms | `cubic-bezier(0.2, 0, 0, 1)` | The capsule changing shape |
| `fade` | 180 ms | ease-out | HUDs appearing, content after a morph (+100 ms delay) |
| `hover` | 120 ms | ease-out | Hover and press colours, revealed actions |
| `pulse` | 1.2 s loop | ease-in-out | Waiting for the model (opacity 50–100 %) |

Only the live level meter and the waiting pulse loop. Things done often don't animate: switching pages,
selecting a row. With the desktop's animations off (`gtk-enable-animations`), everything snaps.

## Icons

16 px on a 16 px grid, 1.5 px strokes with round caps and joins, outline only, drawn by `design.Icon` so they
look the same on every desktop theme. Colour `text-2` at rest, `text` on hover, `accent` when on. One icon per
action, always with a tooltip naming the action ("Copy", "Delete"), which is also how tests find them.

The set: `mic`, `history`, `transcript`, `refinements`, `voices`, `settings`, `search`, `copy`, `play`, `stop`,
`pause`, `trash`, `undo` (the original text), `folder`, `open`, `plus`, `check`, `warning`, `close`.

## The app icon

A charcoal rounded square (corner radius 24 % of its side, inset 6 %; `#33363d` at the top to `#16171a`), lit
along its top edge so it shows on a dark panel, with the microphone in white, filled, at 62 % of its side, and a
`record`-red dot at its top right: the capsule as it looks dictating. (The one place red appears without
meaning "recording now": it's the mark of the app, not a state.) Strokes and the dot are bolder at 24 px and
under. It's the same in light and dark. `design.draw_app_icon` draws it at any size: every window gets it
(`Gtk.Window.set_default_icon_list`), the tray shows it while idle (its other states are the capsule's), and
`dictate/icon.png` (256 px, regenerated by `docs/make_screenshots.py`) is the launchers' and notifications' icon.

## Components

Build every surface from these, in `design.py`; add a component here before using a one-off.

- **Button.** `primary` (accent fill, on-accent text; one per view), `secondary` (surface-3, text), `quiet`
  (transparent, text-2; hover surface-3), `danger` (quiet with danger text; hover danger-weak). 28 high, r-sm,
  12 px sides, body-strong. A **key hint** (`⏎`, `Esc`) can sit inside at caption size in text-3.
- **Icon button.** 28×28, r-sm, quiet; an icon and a tooltip.
- **Chip.** 20 high, r-sm, caption, surface-3 with text-2; `accent` chip uses accent-weak with accent text.
- **Segmented control.** Two to four views of one thing (a rail's Topics and Summary): equal buttons on a
  surface-3 track (r-sm, 2 px in), small 600 text-2; the chosen one on `raised` with a 1 px shadow, in text.
  Switches at once; remembers its choice for the window's life.
- **Step chip.** A chip that can be clicked to open what it stands for (a dictation's Cleanup or refinement: what
  that step changed); hover surface-4; chosen: the accent chip. Only one open per item.
- **Step card.** What a step did to some text, under the item: surface-2, `line` border, r-md, 10/12 padding,
  a caption heading ("What cleanup changed"). Light edits are marked in place: what went struck through in
  `danger`, what came highlighted in the accent at 22 %. A rewrite (under half the words in common) shows Before
  (small, text-2) and After (body) instead. Opens with `fade`.
- **Clickable times.** In a transcript, a paragraph's time (caption size, text-3) plays the call from that
  moment while its recordings are kept; nothing else about it changes, so a transcript stays plain to read.
- **Key badge.** 18×18, r-xs, surface-3, caption 600 in text, the letter upper-case.
- **Row.** A list item: r-md, 8/12 padding, transparent; hover surface-2; actions (icon buttons) at the right,
  hidden until hover (opacity, so they keep their place). Text first, a caption meta line under or over it.
- **Group header.** Caption 600 in text-3, sentence case ("Today"), 16 above, 4 below.
- **Field.** Label (small 600, text-2) above; input 32 high, r-sm, surface-2, `line` border, `accent` border
  and `accent-weak` ring on focus. Help text under it in small text-3; errors in danger.
- **Setting row.** Title (body) and description (small text-3) on the left, the control (switch or dropdown)
  on the right; a hairline between rows.
- **Sidebar.** 200 wide, surface-1, the app's name at the top (title), nav items 32 high with an icon and a
  label; selected: surface-3 and text; hover surface-2.
- **Page header.** Headline at left, the page's actions at right (one primary at most), 24 padding; a status
  line under the title when something's live.
- **Status pill.** Caption 600 on surface-3, r-full, with a 6 px dot: record red when recording, text-3 when
  paused; a tabular timer.
- **HUD card.** A window of its own for a moment's question or notice (refinement picker, rename, confirm,
  reminder): r-lg, `hud` fill, border and top highlight, 16 padding, a title, short body, buttons at the bottom
  right (the safe choice left of the primary). Opens with `fade`, near what it's about (the capsule, the pointer
  or the screen's centre). Escape cancels; Enter takes the primary.
- **Warning strip.** warning-weak background, warning text and icon, r-sm, inside a page or HUD.
- **Scrollbar.** Thin and quiet: a 3 px rounded line in `line-strong`, no trough or arrows; 6 px in `text-3`
  while hovered or dragged. Overlaid on the content where the desktop allows.
- **Empty state.** A 32 px icon in text-3, one sentence in text-2, a hint of what to do in small text-3, centred.
- **The capsule.** 36 high, r-full, `surface-1` at 92 % with the HUD border and shadow:
  - idle: a 36 px dot with the mic icon (text-2; text on hover);
  - listening: grows to the right to fit a record dot, 11 level bars (3 wide, 2 apart, 4–20 high, white
    85 %, the middle ones taller) and a tabular timer;
  - processing: bars at 35 % and a three-dot pulse;
  - transcribing a call: a `record` dot (text-3 when paused), the elapsed time and, when known, the topic now
    in text-2, at most 220 wide; clicking it opens the transcript.

## Words

- Sentence case for everything: titles, buttons, labels, menu items.
- Buttons are verbs ("Copy", "Delete", "Stop"); a "…" means it opens something more.
- Say what happens, briefly: "Closing the window doesn't stop it." Not "Please note that…".
- Times: "Today", "Yesterday", then "Tue 20 Oct"; clock times 24-hour; durations "under a minute", "12 min",
  "1 h 05 min"; live timers "12:34".
- Keyboard keys as written on the key: Ctrl, Win, Alt, Esc, Enter.

## Building it (GTK 3)

- **Tokens, not values.** `design.tok("accent")`, `design.rgba("text-2")`, the CSS classes in `design.css()`
  (`.title`, `.small`, `.caption`, `.chip`, `.row-item`, `btn primary`…). A new colour or size goes into
  `SCHEMES`/`TYPE` and this file first.
- **Components, not widgets.** `design.button`, `icon_button`, `field`, `setting_row`, `group_header`,
  `empty_state`, `warning_strip`, `status_pill`, `Hud`; pages are built with `hub.page_header`. Hand-built
  widgets get the matching class.
- **Light and dark.** Everything takes its colours from the scheme at draw time; things drawn in cairo (the
  capsule, the tray icon, text-view tags) redraw from `design.on_scheme` when it changes.
- **Translucent windows** (the capsule, HUDs) use greyscale text antialiasing (`design.grayscale`): sub-pixel
  colour fringes show through translucency. Their shadow needs transparent room inside the window.
- **The Dictate window's header bar** holds only the window buttons; the sidebar's colour runs up through it, so
  the window reads as one surface. The page names itself in its headline; the window's title follows the page.
- **Resizing.** A wider window shows more. Lists (Dictations) and the transcript fill the width they're given;
  side panes (the transcript list, the topics rail) are split panes the user drags to the width they want
  (a hairline divider with 2 px to grab either side, painted the colour of the pane beside it; brighter on
  hover; widths remembered in the settings), and keep it as the window grows. Forms read better as a
  column: Settings (640 px) and Voices (560 px) centre in a wide window (`design.Clamp`). Narrower, everything
  shrinks to what's still usable: long titles and status lines end in "…", text wraps, and below 1120 px the
  sidebar shows only its icons. A pane beside a draggable divider keeps its narrowest small and steady: no
  rows of buttons or changing text side by side that can't wrap or shorten (icon buttons, wrapping rows, short
  status), or the divider stops wherever that narrowest is at the moment. Panes that shouldn't grow say
  `hexpand=False` (a scrolled list inside would otherwise make them). Changes made in response to a resize (the sidebar) are applied after GTK's layout, from
  an idle callback.
- **Hover-revealed actions** fade with `opacity`, so they keep their place and stay clickable by keyboard and by
  tests; a playing recording keeps its row's actions shown. In GTK 3 only the list row itself is hovered (not
  the boxes in it), so hover rules start from `row:hover`.
- **Screenshots** of every surface, light and dark, come from `docs/make_screenshots.py` (`--light`); check a
  change in both.
