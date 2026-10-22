"""A live summary of a conversation while it's transcribed: what it's about, what was discussed (and who thought
what), what was agreed, the action points and what's still open; a little more than an executive summary, so
everyone leaves with the same understanding.

Every EVERY seconds (once enough has been said since) the refinement model gets the summary so far, the topics so
far (topics.py) and what was said since, and writes the whole summary again, updated: so it changes as the
conversation does, without the model having to read all of it each time: quick, and a little rough (it hasn't
heard where things went). When it's stopped there's a final pass, careful: from the whole transcript if it fits
the model's context, else from the summary, the topics and the end of it.
The prompt is the user's to change (Refinements → Live summary; kept in data/summary.txt)."""
import re
from xml.sax.saxutils import escape
from . import DATA, refine, topics

PROMPT_FILE = DATA / "summary.txt"
EVERY = 30  # seconds between updates, so it keeps up (3-7 s each on the larger model), and a final pass at the end
WORDS = 30  # said since the last update, for another to be worth it
WHOLE = 3500  # words: a transcript this long or shorter is read whole for the final pass (within the model's context)
LAST = 400  # words: otherwise the end of it, with the summary and the topics
PROMPT = """You keep a running summary of a meeting or call while it happens, so that everyone in it leaves with the same understanding of what was discussed and what was agreed. It's read by people who were there: a little more than an executive summary, much less than minutes.

The transcript is from speech recognition: it has mis-heard words, cut-off sentences and lines given to the wrong speaker; make sense of it, but don't invent anything that wasn't said. Use people's names as the transcript gives them ("Me" is the person keeping the summary).

Write it in Markdown, in these sections, leaving out any with nothing in them yet:
## Overview
Two to four sentences: what the conversation is about, and where it has got to.
## Discussed
A bullet per subject: what was said about it, and who thought what where views differed.
## Agreed
A bullet per decision made.
## Action points
A bullet per thing someone is to do: "**Who:** what (and by when, if that was said)".
## Open questions
A bullet per thing still undecided or unanswered.

Be faithful above all: put under Agreed only what people said they agreed or decided, and under Action points only what someone said they (or someone else) would do; anything less certain belongs under Discussed or Open questions. Don't guess at facts the transcript doesn't give.
When updating, keep every subject from the summary so far (correcting it where what was said since changes it), even if nobody mentioned it again; add what's new.
Be specific and brief: plain sentences, no filler, nothing about the summary itself."""


def prompt():
    return PROMPT_FILE.read_text() if PROMPT_FILE.exists() else PROMPT


def save_prompt(text):
    """Keep the user's prompt (or, if it's the default again, go back to following the default)."""
    if text.strip() == PROMPT.strip():
        PROMPT_FILE.unlink(missing_ok=True)
    else:
        PROMPT_FILE.write_text(text.strip() + "\n")


class Summary:
    """text: the summary so far (Markdown), "" until there is one; read: the keys of the lines it has read (lines
    as topics.py has them: (key, who, text)); final: whether it's the final pass's."""

    def __init__(self, text="", final=False):
        self.text, self.read, self.final = text, set(), final

    def new(self, lines):
        return [l for l in lines if l[0] not in self.read]

    def due(self, lines, since, slow=False):
        """Whether to update: lines are all the lines so far; since: seconds since the last update; slow: on the
        smaller model, on the CPU (topics.SLOWER times as long between)."""
        return since >= EVERY * (topics.SLOWER if slow else 1) and sum(len(t.split()) for _, _, t in self.new(lines)) >= WORDS

    def ask(self, lines, found):
        """The model's updated summary, from what was said since the last (slow: not on the GTK thread)."""
        new = "".join(f"{who}: {text}\n" for _, who, text in self.new(lines))
        return refine.write(prompt(), f"The summary so far:\n{self.text or '(none yet)'}\n\nThe topics so far:\n"
                                      f"{topic_list(found)}\n\nWhat was said since the summary was written:\n"
                                      f"<transcript>\n{new}</transcript>\n\nReply with the whole summary, updated.")

    def ask_final(self, lines, found):
        """The final summary, once the conversation has ended (slow)."""
        words = sum(len(t.split()) for _, _, t in lines)
        if words <= WHOLE:
            said = "".join(f"{who}: {text}\n" for _, who, text in lines)
            return refine.write(prompt(), f"The conversation has ended. Here is all of it:\n<transcript>\n{said}"
                                          f"</transcript>\n\nWrite the final summary.")
        tail, count = [], 0
        for _, who, text in reversed(lines):
            tail.insert(0, f"{who}: {text}\n")
            count += len(text.split())
            if count >= LAST:
                break
        return refine.write(prompt(), f"The conversation has ended. The summary so far:\n{self.text or '(none yet)'}"
                                      f"\n\nAll its topics:\n{topic_list(found)}\n\nHow it ended:\n<transcript>\n"
                                      f"{''.join(tail)}</transcript>\n\nWrite the final summary: the summary so far, "
                                      f"corrected and completed.")

    def take(self, reply, lines, final=False):
        """Take the model's summary of lines. Returns whether it was one."""
        text = clean(reply)
        if not text:
            print("summary: the model's answer isn't a summary:", reply[:100], flush=True)
            return False
        self.text, self.final = text, final
        self.read.update(l[0] for l in lines)
        return True

    def data(self):
        return {"text": self.text, "final": self.final}


def topic_list(found):
    return "\n".join(f"- {t['title']}: {' '.join(t['points'])}" for t in found.topics) or "(none yet)"


def clean(reply):
    """The summary in a reply: the Markdown, without anything around it (a fence, a preamble before its first
    heading)."""
    text = re.sub(r"^```\w*\n|\n```$", "", reply.strip())
    first = text.find("## ")
    return (text[first:] if first > 0 else text).strip() if "## " in text else ""


def markup_lines(text):
    """The summary's Markdown as [(kind, Pango markup)]: kind "heading", "bullet" or "text"."""
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        bold = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(s))
        if line.startswith("#"):
            out.append(("heading", bold(line.lstrip("#").strip())))
        elif re.match(r"\s*[-*•]\s+", line):
            out.append(("bullet", bold(re.sub(r"^\s*[-*•]\s+", "", line))))
        else:
            out.append(("text", bold(line)))
    return out


def markdown(text):
    """The summary as part of the transcript's Markdown (its headings a level down, under "## Summary")."""
    if not text:
        return ""
    return "\n## Summary\n\n" + re.sub(r"^## ", "### ", text, flags=re.M) + "\n"
