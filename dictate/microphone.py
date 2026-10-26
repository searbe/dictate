"""The microphone Dictate records: decided here, and only here. The first one connected in the order set on the
Settings page (those seen for the first time join its end, the system's default one first, so until you change
the order it's the default one); a wireless headset that's switched off doesn't count as connected (headsets.py).

What's connected is checked every POLL seconds, off the GTK thread. When the one to record changes (a headset
switched on or off, one plugged in or out, the order changed), every recording of the microphone that's running
(a dictation, a call: they follow it while they run) is moved to it by PipeWire, as it's recorded: nothing's
restarted, nothing's lost, and the recording carries on in the same file. Dictations start with it, calls too,
and the Settings page shows it."""
import logging
import threading

from gi.repository import GLib

from . import osio

log = logging.getLogger(__name__)

POLL = 2  # seconds between checks of what's connected


class Microphone:
    """current: the name of the microphone to record (osio.microphones'), or None: the system's default (none in
    the order is connected); connected: {name: description}. listen(fn): fn() on the GTK thread when either
    changes (returns a function that stops it)."""

    def __init__(self, settings):
        self.settings, self.current, self.connected = settings, None, {}
        self.listeners, self.following, self.checking = [], [], False
        self.update(osio.microphones())
        GLib.timeout_add(int(POLL * 1000), self.poll)

    def listen(self, fn):
        self.listeners.append(fn)
        return lambda: fn in self.listeners and self.listeners.remove(fn)

    def order(self):
        return self.settings["microphones"]

    def set_order(self, order):
        """The order set on the Settings page: [[name, description]], preferred first."""
        self.settings.update(microphones=order)
        self.update(list(self.connected.items()))

    def refresh(self):
        """Check what's connected now, on this thread (slow-ish: about 20 ms)."""
        self.update(osio.microphones())

    def poll(self):
        if not self.checking:
            self.checking = True

            def check():
                found = osio.microphones()
                GLib.idle_add(lambda: (setattr(self, "checking", False), self.update(found)) and False)
            threading.Thread(target=check, daemon=True).start()
        return True

    def update(self, found):
        """found: [(name, description)] connected now (osio.microphones)."""
        connected, order = dict(found), self.order()
        new = [[name, label] for name, label in connected.items() if name not in {n for n, _ in order}]
        if new:
            self.settings.update(microphones=order + new)
        current = next((name for name, _ in self.order() if name in connected), None)
        changed = current != self.current
        if changed:
            log.info("recording %s", connected.get(current, "the system's default"))
            self.current = current
            if current and self.following:
                recordings = list(self.following)
                threading.Thread(target=lambda: [rec.move(current) for rec in recordings], daemon=True).start()
        if changed or connected != self.connected:
            self.connected = connected
            for fn in list(self.listeners):
                fn()

    def follow(self, rec):
        """rec (an osio.Recorder of the microphone, started) is moved to the microphone whenever it changes, until
        unfollow(rec)."""
        self.following.append(rec)

    def unfollow(self, rec):
        if rec in self.following:
            self.following.remove(rec)
