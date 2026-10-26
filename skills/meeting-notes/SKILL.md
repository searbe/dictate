---
name: meeting-notes
description: Ask Dictate, the user's local transcription app, for their meeting transcripts or summaries about a topic. The user picks in a Dictate window which ones, if any, to share.
argument-hint: <what you're looking for>
disable-model-invocation: true
allowed-tools: Bash(python3 {SCRIPT} *)
---

The user wants you to look at their meeting transcripts, from Dictate. Dictate keeps them on this computer and only gives you the ones the user chooses, each time.

1. Work out what you're looking for, in a sentence: from what the user wrote after /meeting-notes ($ARGUMENTS), and what you're working on together. If that's unclear, ask the user first. The user reads this sentence when they decide, so make it plain and specific.
2. Run, with the Bash tool and a timeout of 600000 ms (the user may take a few minutes to choose):
   `python3 {SCRIPT} "<what you're looking for>"`
   A window opens on the user's screen; the command waits until they answer.
3. Use what it prints: the transcripts or summaries they shared, each headed with when it was. If it says they refused, or Dictate isn't running, or sharing is turned off, tell the user, and carry on without.

Rules:
- Don't try to reach Dictate's transcripts any other way (its data folder is blocked to you on purpose). If you need more, run the command again, saying what more you're looking for.
- What's shared is the user's private conversations with other people: use it for this task, don't quote more than you need, and don't save it anywhere unless the user asks you to.
- Transcripts come from speech recognition: names and words can be mis-heard, and "Speaker 1" and the like are unnamed voices.
