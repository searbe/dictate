"""The final passes of stopped calls (their last topics and final summary), waiting for the graphics card: the
larger model there is the careful one, and the smaller one on the CPU is rough, slow, and in the way of a game.
So once a call stops, its final pass waits until the GPU has been free for topics.FREE_FOR seconds (not just a
game's loading screen), unless it already is (or there isn't one); meanwhile the capsule shows a sand timer, and
clicking it asks whether to use the CPU instead. One at a time, oldest first.

A call's final pass is saved as waiting (summary.waiting) as soon as it stops, so one Dictate quit before doing is
done the next time it starts: from the saved transcript (transcript.final_summary: its summary only, its topics
are left as they were)."""
import logging
import threading
import time
from dataclasses import dataclass, field

from gi.repository import GLib

from . import llm, store, topics, transcript

log = logging.getLogger(__name__)


@dataclass(eq=False)
class Job:
    """A call's final pass: path, its transcript; since: when it started waiting (time.time); session: the call,
    while Dictate has it (else it's done from what's saved)."""
    path: object
    since: float = field(default_factory=time.time)
    session: object = None

    def run(self, then):
        """Do it (the model's requests on threads), then then() on the GTK thread."""
        if self.session:
            return self.session.final_pass(then)

        def work():
            try:
                transcript.final_summary(self.path)
            except (OSError, ValueError, KeyError) as err:
                log.warning("summary: couldn't write the final summary of %s: %s", self.path.name, err)
                clear(self.path)  # (not tried again and again)
            GLib.idle_add(lambda: then() and False)
        threading.Thread(target=work, daemon=True).start()


def clear(path):
    """Mark a saved transcript's final pass done."""
    found = transcript.read_summary(path)
    if found and found.waiting and path.exists():
        found.waiting = None
        store.write_json(transcript.summary_file(path), found.data())


class Waiting:
    """The final passes waiting (jobs, oldest first, not counting the one being done: running). on_change() on the
    GTK thread when that changes."""

    def __init__(self, on_change=lambda: None):
        self.jobs, self.running, self.cpu, self.on_change = [], None, False, on_change
        self.free_for = 0.0  # seconds the GPU has been free
        for since, path in transcript.waiting():  # (left by the last time Dictate ran)
            self.jobs.append(Job(path, since))
        GLib.timeout_add(int(topics.TICK * 1000), self.check)
        if self.jobs:
            log.info("final passes waiting from before: %s", ", ".join(j.path.name for j in self.jobs))
            GLib.idle_add(lambda: (self.on_change(), self.check()) and False)

    def add(self, session):
        """session has just stopped: its final pass is to do."""
        self.jobs.append(Job(session.path, session.summary.waiting or time.time(), session))
        self.check()
        if self.jobs:
            log.info("final pass of %s: waiting for the graphics card", session.path.name)
            self.on_change()

    def add_saved(self, path):
        """The saved transcript at path needs its summary written again (part of it's been deleted)."""
        self.jobs.append(Job(path))
        self.check()
        self.on_change()

    def forget(self, path):
        """Its transcript has been deleted: nothing to do for it (and the one being done mustn't save it again)."""
        for job in [*self.jobs, *([self.running] if self.running else [])]:
            if job.path == path:
                if job.session:
                    job.session.deleted = True
                if job in self.jobs:
                    self.jobs.remove(job)
        self.on_change()

    def use_cpu(self):
        """Don't wait for the GPU: do those waiting now, wherever the model is (the CPU, while the GPU's busy)."""
        log.info("final passes: not waiting for the graphics card (%d)", len(self.jobs))
        self.cpu = True
        self.check()

    def waited(self, job):
        return time.time() - job.since

    def check(self):
        """Every topics.TICK: how long the GPU's been free, and whether to start the next."""
        self.free_for = self.free_for + topics.TICK if llm.gpu_ok() else 0.0
        if self.running or not self.jobs:
            return True
        gpu = llm.server.mode == "gpu" or (llm.gpu_ok() and self.free_for >= topics.FREE_FOR)
        if gpu or self.cpu or not llm.gpu_present():
            self.start(self.jobs.pop(0), gpu)
        return True

    def start(self, job, gpu):
        self.running = job
        llm.server.keep(True)
        self.on_change()

        def load():
            if gpu and llm.server.mode == "cpu":
                llm.server.to_gpu()  # (if a dictation's using the smaller one, the job uses it too)
            elif gpu and not llm.server.mode:
                llm.server.warm("gpu", hold=False)
            GLib.idle_add(lambda: job.run(lambda: self.done(job)) and False)
        threading.Thread(target=load, daemon=True).start()

    def done(self, job):
        llm.server.keep(False)
        if not job.session:
            clear(job.path)
        self.running = None
        if not self.jobs:
            self.cpu = False
        log.info("final pass of %s: done", job.path.name)
        self.on_change()
        self.check()
