"""A live summary of a conversation while it's transcribed: what it's about, what was discussed (and who thought
what), what was agreed, the action points and what's still open; a little more than an executive summary, so
everyone leaves with the same understanding.

Every EVERY seconds (once enough has been said since) the refinement model gets the summary so far, the topics'
titles so far (topics.py) and what was said since, and writes the whole summary again, updated: so it changes as
the conversation does, without the model having to read all of it each time: quick, and a little rough (it hasn't
heard where things went).

Meanwhile, every SLICE words, that slice of the conversation is summarised on its own, from all of it. When it's
stopped there's a final pass, careful: from the whole transcript if it's short enough, else from the slices'
summaries, merged (the rest summarised as a slice first). So the final summary has read everything that was said,
once, however long the call: a rolling summary alone, rewritten a hundred times, drops and blurs things, and the
whole of a long call (or every topic's points, which is what overflowed before) doesn't fit the model's context.
If the slices' summaries don't fit either, the earliest are condensed into one first, as often as it takes.
Nothing is sent that doesn't leave room for the answer (llm.fits), and an answer that was cut off isn't taken
(llm.Cut): the summary stays as it was.
The prompt is the user's to change (Refinements → Live summary; kept in data/summary.txt); slices and the merge
use it too, with what they're for said in the request."""
import logging
import re
from xml.sax.saxutils import escape

from . import DATA, llm, prompts, store, topics

log = logging.getLogger(__name__)

PROMPT_FILE = DATA / "summary.txt"
EVERY = 30  # seconds between updates, so it keeps up (3-7 s each on the larger model), and a final pass at the end
WORDS = 30  # said since the last update, for another to be worth it
WHOLE = 3500  # words: a transcript this long or shorter is read whole for the final pass (within the model's context)
SLICE = 1500  # words: a slice of the conversation summarised on its own (about 2,000 tokens to read)
SLICE_WORDS = 300  # a slice's summary at most, in words (asked for: 9B wrote 330-440 words of 1,500), and in
PART = 1000  # tokens (so it stops)
ANSWER = 2000  # tokens: the whole summary at most (asked for in at most WORDS_MOST words: models write over)
WORDS_MOST = 1000
PROMPT = prompts.load("summary")


def prompt():
    return store.read_text(PROMPT_FILE) or PROMPT


def save_prompt(text):
    """Keep the user's prompt (or, if it's the default again, go back to following the default)."""
    if text.strip() == PROMPT.strip():
        PROMPT_FILE.unlink(missing_ok=True)
    else:
        store.write_text(PROMPT_FILE, text.strip() + "\n")


class Summary:
    """text: the summary so far (Markdown), "" until there is one; read: the keys of the lines it has read (lines
    as topics.py has them: (key, who, text), in order); final: whether it's the final pass's; slices: the slices
    summarised so far, in order: {"until": the key of its last line, "text": its summary}."""

    def __init__(self, text="", final=False, slices=()):
        self.text, self.read, self.final = text, set(), final
        self.slices = [dict(sl) for sl in slices]

    def new(self, lines):
        return [line for line in lines if line[0] not in self.read]

    def due(self, lines, since, slow=False):
        """Whether to update: lines are all the lines so far; since: seconds since the last update; slow: on the
        smaller model, on the CPU (topics.SLOWER times as long between)."""
        return (since >= EVERY * (topics.SLOWER if slow else 1)
                and sum(len(t.split()) for _, _, t in self.new(lines)) >= WORDS)

    def ask(self, lines, found):
        """The model's updated summary, from what was said since the last (slow: not on the GTK thread). If it
        doesn't all fit, without the topics, then with only the latest of what was said (the slices have it all)."""
        new, listed = self.new(lines), titles(found)
        while True:
            said = "".join(f"{who}: {text}\n" for _, who, text in new)
            user = (f"The summary so far:\n{self.text or '(none yet)'}\n\n"
                    + (f"The topics so far:\n{listed}\n\n" if listed else "")
                    + f"What was said since the summary was written:\n<transcript>\n{said}</transcript>\n\n"
                      "Reply with the whole summary, updated.")
            if llm.fits(prompt(), user, ANSWER) or (not listed and len(new) == 1):
                return llm.write(prompt(), user, ANSWER)
            if listed:
                listed = ""
            else:
                new = new[len(new) // 2:]

    def slice_due(self, lines):
        """The lines of the next slice to summarise, once SLICE words have been said that aren't in one; or None."""
        part = self.part(self.unsliced(lines))
        return part if sum(len(t.split()) for _, _, t in part) >= SLICE else None

    def unsliced(self, lines, slices=None):
        slices = self.slices if slices is None else slices
        return [line for line in lines if not slices or line[0] > slices[-1]["until"]]

    @staticmethod
    def part(lines):
        """The first SLICE words' worth of lines (all of them, if there are fewer)."""
        out, words = [], 0
        for line in lines:
            out.append(line)
            words += len(line[2].split())
            if words >= SLICE:
                break
        return out

    def ask_slice(self, part, slices=None):
        """The summary of one slice, part (its lines), on its own (slow); the slice before it gives it context."""
        slices = self.slices if slices is None else slices
        said = "".join(f"{who}: {text}\n" for _, who, text in part)
        before = (f"What the conversation was about before this part, in brief:\n{slices[-1]['text']}\n\n"
                  if slices else "")
        text = clean(llm.write(prompt(), f"{before}This is part {len(slices) + 1} of a longer conversation:\n"
                                         f"<transcript>\n{said}</transcript>\n\nSummarise just this part, in at "
                                         f"most {SLICE_WORDS} words.", PART))
        if not text:
            raise ValueError("the model's answer isn't a summary of the part")
        return text

    def take_slice(self, part, text):
        self.slices.append({"until": part[-1][0], "text": text})

    def ask_final(self, lines, found):
        """The final summary, once the conversation has ended (slow), and the slices it was made from:
        (reply, slices)."""
        said = "".join(f"{who}: {text}\n" for _, who, text in lines)
        whole = f"The conversation has ended. Here is all of it:\n<transcript>\n{said}</transcript>\n\n" \
                "Write the final summary."
        if sum(len(t.split()) for _, _, t in lines) <= WHOLE and llm.fits(prompt(), whole, ANSWER):
            return llm.write(prompt(), whole, ANSWER), self.slices
        slices = list(self.slices)
        while rest := self.unsliced(lines, slices):  # what's been said since the last slice: a slice too
            part = self.part(rest)
            slices.append({"until": part[-1][0], "text": self.ask_slice(part, slices)})
        while True:
            parts = "\n\n".join(f"Part {n}:\n{sl['text']}" for n, sl in enumerate(slices, 1))
            merge = (f"The conversation has ended. Here are summaries of its parts, in order:\n\n{parts}\n\n"
                     "Write the final summary of the whole conversation from them: one bullet per subject, "
                     "combining what the parts say about it, and keeping everything they say, in at most "
                     f"{WORDS_MOST} words.")
            if llm.fits(prompt(), merge, ANSWER) or len(slices) < 2:
                return llm.write(prompt(), merge, ANSWER), slices
            half = max(2, len(slices) // 2)  # the earliest, condensed into one
            first = "\n\n".join(f"Part {n}:\n{sl['text']}" for n, sl in enumerate(slices[:half], 1))
            text = clean(llm.write(prompt(), f"Here are summaries of consecutive parts of a conversation, in "
                                             f"order:\n\n{first}\n\nCombine them into one summary of these "
                                             f"parts, in at most {SLICE_WORDS * 2} words.", PART * 2))
            if not text:
                raise ValueError("the model's answer isn't a summary of the parts")
            slices = [{"until": slices[half - 1]["until"], "text": text}, *slices[half:]]

    def take(self, reply, lines, final=False, slices=None):
        """Take the model's summary of lines (and, final, the slices it was made from). Returns whether it was
        one."""
        text = clean(reply)
        if not text:
            log.warning("the model's answer isn't a summary: %s", reply[:100])
            return False
        self.text, self.final = text, final
        self.read.update(line[0] for line in lines)
        if slices is not None:
            self.slices = slices
        return True

    def data(self):
        return {"text": self.text, "final": self.final, "slices": self.slices}


def titles(found):
    return "\n".join(f"- {t['title']}" for t in found.topics)


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
