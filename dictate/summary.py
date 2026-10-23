"""A live summary of a conversation while it's transcribed: what it's about, what was discussed (and who thought
what), what was agreed, the action points and what's still open; a little more than an executive summary, so
everyone leaves with the same understanding.

Every EVERY seconds (once enough has been said since) the refinement model gets the summary so far, the topics so
far (topics.py) and what was said since, and writes the whole summary again, updated: so it changes as the
conversation does, without the model having to read all of it each time: quick, and a little rough (it hasn't
heard where things went). When it's stopped there's a final pass, careful: from the whole transcript if it fits
the model's context, else from the summary, the topics and the end of it.
The prompt is the user's to change (Refinements → Live summary; kept in data/summary.txt)."""
import logging
import re
from xml.sax.saxutils import escape

from . import DATA, llm, prompts, store, topics

log = logging.getLogger(__name__)

PROMPT_FILE = DATA / "summary.txt"
EVERY = 30  # seconds between updates, so it keeps up (3-7 s each on the larger model), and a final pass at the end
WORDS = 30  # said since the last update, for another to be worth it
WHOLE = 3500  # words: a transcript this long or shorter is read whole for the final pass (within the model's context)
LAST = 400  # words: otherwise the end of it, with the summary and the topics
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
    as topics.py has them: (key, who, text)); final: whether it's the final pass's."""

    def __init__(self, text="", final=False):
        self.text, self.read, self.final = text, set(), final

    def new(self, lines):
        return [line for line in lines if line[0] not in self.read]

    def due(self, lines, since, slow=False):
        """Whether to update: lines are all the lines so far; since: seconds since the last update; slow: on the
        smaller model, on the CPU (topics.SLOWER times as long between)."""
        return (since >= EVERY * (topics.SLOWER if slow else 1)
                and sum(len(t.split()) for _, _, t in self.new(lines)) >= WORDS)

    def ask(self, lines, found):
        """The model's updated summary, from what was said since the last (slow: not on the GTK thread)."""
        new = "".join(f"{who}: {text}\n" for _, who, text in self.new(lines))
        return llm.write(prompt(), f"The summary so far:\n{self.text or '(none yet)'}\n\nThe topics so far:\n"
                                      f"{topic_list(found)}\n\nWhat was said since the summary was written:\n"
                                      f"<transcript>\n{new}</transcript>\n\nReply with the whole summary, updated.")

    def ask_final(self, lines, found):
        """The final summary, once the conversation has ended (slow)."""
        words = sum(len(t.split()) for _, _, t in lines)
        if words <= WHOLE:
            said = "".join(f"{who}: {text}\n" for _, who, text in lines)
            return llm.write(prompt(), f"The conversation has ended. Here is all of it:\n<transcript>\n{said}"
                                          f"</transcript>\n\nWrite the final summary.")
        tail, count = [], 0
        for _, who, text in reversed(lines):
            tail.insert(0, f"{who}: {text}\n")
            count += len(text.split())
            if count >= LAST:
                break
        return llm.write(prompt(), f"The conversation has ended. The summary so far:\n{self.text or '(none yet)'}"
                                      f"\n\nAll its topics:\n{topic_list(found)}\n\nHow it ended:\n<transcript>\n"
                                      f"{''.join(tail)}</transcript>\n\nWrite the final summary: the summary so far, "
                                      f"corrected and completed.")

    def take(self, reply, lines, final=False):
        """Take the model's summary of lines. Returns whether it was one."""
        text = clean(reply)
        if not text:
            log.warning("the model's answer isn't a summary: %s", reply[:100])
            return False
        self.text, self.final = text, final
        self.read.update(line[0] for line in lines)
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
