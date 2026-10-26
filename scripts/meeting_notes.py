"""Ask the running Dictate for transcripts about something (the /meeting-notes skill runs this). Dictate asks you
which, if any, to share; this prints what you chose, as Markdown, or why there's nothing.

Usage: python3 scripts/meeting_notes.py "<what it's looking for>"
Only the standard library: it runs with any Python 3, outside Dictate's .venv. See dictate/sharing.py."""
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAIT = 540 + 30  # seconds: Dictate's wait for you to choose (sharing.WAIT), and a little more


def address():
    """As sharing.address: the socket of the Dictate with this data folder."""
    data = Path(os.environ.get("DICTATE_DATA") or ROOT / "data").resolve()
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dictate-{os.getuid()}"
    return Path(runtime) / f"dictate-{hashlib.sha1(str(data).encode()).hexdigest()[:10]}.sock"


def ask(topic):
    """Dictate's answer: {"shared": [...]} or {"refused": "..."}."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(WAIT)
        try:
            sock.connect(str(address()))
        except OSError:
            return {"refused": "Dictate isn't running, so there's no one to ask."}
        sock.sendall((json.dumps({"topic": topic, "from": os.getcwd()}) + "\n").encode())
        try:
            line = sock.makefile().readline()
        except TimeoutError:
            return {"refused": "No answer from Dictate in time."}
    return json.loads(line) if line else {"refused": "Dictate closed the connection without answering."}


def main():
    topic = " ".join(sys.argv[1:]).strip()
    if not topic:
        sys.exit('Usage: meeting_notes.py "<what you\'re looking for>"')
    answer = ask(topic)
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
