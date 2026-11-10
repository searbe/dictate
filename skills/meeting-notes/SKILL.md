---
name: meeting-notes
description: Ask Dictate, the user's local transcription app, for their meeting transcripts or summaries about a topic. Use whenever the user's meetings or calls might help: asking is safe, because the user picks in a Dictate window which ones, if any, to share.
argument-hint: <what you're looking for>
allowed-tools: Bash(python3 {SCRIPT} *)
---

This is how you look at the user's meeting transcripts, from Dictate. Dictate keeps them on this computer and only gives you the ones the user chooses, each time.

1. Work out what you're looking for, in a sentence: from what the user asked ($ARGUMENTS, if they ran /meeting-notes), and what you're working on together. If that's unclear, ask the user first. The user reads this sentence when they decide, so make it plain and specific.
   If they said when the meeting was ("this morning", "yesterday's call", "on Monday"), also work out that time as a range in their local time, `YYYY-MM-DD HH:MM`: run `date` first if you don't know the date and time now. "This morning" is today from 00:00 to 12:00; "this afternoon" 12:00 to 18:00; a day is 00:00 to 00:00 the next day.
2. Run, with the Bash tool and a timeout of 600000 ms (the user may take a few minutes to choose):
   `python3 {SCRIPT} "<what you're looking for>"`, adding `--since "<start>" --until "<end>"` if you have a range (either alone is fine for an open-ended one: "since Monday").
   Dictate puts the meetings that were going on during that range first.
   A window opens on the user's screen; the command waits until they answer.
3. Use what it prints: the transcripts or summaries they shared, each headed with when it was. If it says they refused, or Dictate isn't running, or sharing is turned off, tell the user, and carry on without.

Rules:
- Don't try to reach Dictate's transcripts any other way (its data folder is blocked to you on purpose). If you need more, run the command again, saying what more you're looking for.
- What's shared is the user's private conversations with other people: use it for this task, don't quote more than you need, and don't save it anywhere unless the user asks you to.
- Transcripts come from speech recognition: names and words can be mis-heard, and "Speaker 1" and the like are unnamed voices.
