#!/usr/bin/env python3
"""Stands in for llama-server: same command line, same HTTP API, but answers by rules instead of a model.

Rules (JSON list in $FAKE_LLAMA_RULES, re-read on every request) are tried in order; the first whose
"prompt", "text" and "user" substrings are all found in the system prompt, the transcript (or the whole user
message, if it has no transcript) and the whole user message decides the answer:
  {"reply": "..."}             answer with this text
  {"op": "upper"}              answer with the transcript in capitals
  {"op": "error"}              answer HTTP 500
  {"op": "cut", "reply": "..."} answer with this text, cut off at max_tokens (finish_reason "length")
A token is a word here (/tokenize too); a prompt that leaves no room for max_tokens in the context (-c) is an HTTP
500, as llama-server's is.
No rule matches → the transcript comes back unchanged (a model with nothing to fix).
Each request is appended to $FAKE_LLAMA_LOG as {"system", "text", "args"}; startup is logged as {"started"}."""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ARGS = sys.argv[1:]
LOG = os.environ["FAKE_LLAMA_LOG"]


def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def answer(system, text, user=""):
    rules_file = Path(os.environ["FAKE_LLAMA_RULES"])
    rules = json.loads(rules_file.read_text()) if rules_file.exists() else []
    for rule in rules:
        if rule.get("prompt", "") in system and rule.get("text", "") in text and rule.get("user", "") in user:
            if rule.get("op") == "upper":
                return text.upper()
            if rule.get("op") == "error":
                return None
            if rule.get("op") == "cut":
                return ("cut", rule["reply"])
            return rule["reply"]
    return text


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply(200, {"status": "ok"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/tokenize":
            return self.reply(200, {"tokens": list(range(len(body["content"].split())))})
        system = next(m["content"] for m in body["messages"] if m["role"] == "system")
        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        tagged = re.search(r"<transcript>\n(.*)\n</transcript>", user, re.S)
        text = tagged.group(1) if tagged else user  # (e.g. topics' merging: no transcript)
        log({"system": system, "text": text, "user": user, "args": ARGS})
        context = int(ARGS[ARGS.index("-c") + 1]) if "-c" in ARGS else None
        if context and len(system.split()) + len(user.split()) + body["max_tokens"] > context:
            return self.reply(500, {"error": "the request exceeds the available context size"})
        out = answer(system, text, user)
        if out is None:
            return self.reply(500, {"error": "fake failure"})
        if isinstance(out, tuple):
            return self.reply(200, {"choices": [{"message": {"content": out[1]}, "finish_reason": "length"}]})
        self.reply(200, {"choices": [{"message": {"content": out}, "finish_reason": "stop"}]})


log({"started": os.getpid(), "args": ARGS})
HTTPServer(("127.0.0.1", int(ARGS[ARGS.index("--port") + 1])), Handler).serve_forever()
