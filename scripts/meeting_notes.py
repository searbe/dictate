"""Ask the running Dictate for transcripts about something (the /meeting-notes skill runs this). Dictate asks you
which, if any, to share; this prints what you chose, as Markdown, or why there's nothing.

Usage: python3 scripts/meeting_notes.py "<what it's looking for>" [--since "YYYY-MM-DD HH:MM"] [--until "..."]
--since and --until (your local time) say when the calls it's looking for were: those during that time come first.
Only the standard library: it runs with any Python 3, outside Dictate's .venv. See dictate/sharing.py."""
import argparse
import hashlib
import json
import os
import socket
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAIT = 540 + 30  # seconds: Dictate's wait for you to choose (sharing.WAIT), and a little more


def address():
    """As sharing.address: the socket of the Dictate with this data folder."""
    data = Path(os.environ.get("DICTATE_DATA") or ROOT / "data").resolve()
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dictate-{os.getuid()}"
    return Path(runtime) / f"dictate-{hashlib.sha1(str(data).encode()).hexdigest()[:10]}.sock"


def ask(topic, since=None, until=None):
    """Dictate's answer: {"shared": [...]} or {"refused": "..."}. since, until: datetimes, or None."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(WAIT)
        try:
            sock.connect(str(address()))
        except OSError:
            return {"refused": "Dictate isn't running, so there's no one to ask."}
        request = {"topic": topic, "from": os.getcwd(), "since": since and since.isoformat(timespec="minutes"),
                   "until": until and until.isoformat(timespec="minutes")}
        sock.sendall((json.dumps({k: v for k, v in request.items() if v}) + "\n").encode())
        try:
            line = sock.makefile().readline()
        except TimeoutError:
            return {"refused": "No answer from Dictate in time."}
    return json.loads(line) if line else {"refused": "Dictate closed the connection without answering."}


def moment(text):
    """A local time, as YYYY-MM-DD HH:MM (or YYYY-MM-DD: its start)."""
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a time like 2026-11-10 09:00") from None


def main():
    parser = argparse.ArgumentParser(description="Ask Dictate for transcripts about something.")
    parser.add_argument("topic", nargs="+", help="what you're looking for")
    parser.add_argument("--since", type=moment, help="calls during or after this local time (YYYY-MM-DD HH:MM)")
    parser.add_argument("--until", type=moment, help="calls during or before this local time (YYYY-MM-DD HH:MM)")
    args = parser.parse_args()
    topic = " ".join(args.topic).strip()
    if not topic:
        parser.error("say what you're looking for")
    if args.since and args.until and args.since >= args.until:
        parser.error("--since must be before --until")
    answer = ask(topic, args.since, args.until)
    if "refused" in answer:
        print(f"Nothing shared: {answer['refused']}")
        return
    shared = answer["shared"]
    print(f"The user shared {len(shared)} transcript{'s' if len(shared) != 1 else ''} from Dictate.\n")
    for it in shared:
        what = "Its summary" if it["kind"] == "summary" else "The whole transcript"
        print(f"# {it['title']}\n\n({what}.)\n\n{it['text'].strip()}\n")


if __name__ == "__main__":
    main()
