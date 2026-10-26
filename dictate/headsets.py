"""Wireless headsets whose USB dongle stays plugged in while the headset is off: the dongle's microphone is still
listed (by ALSA, so by PipeWire), and records silence. For those we know how to ask, the dongle says whether the
headset is on, and a microphone whose headset is off doesn't count as connected (osio.microphones): the next one
in the order is recorded instead.

Only "off" is skipped, and only when the dongle says so plainly; if it can't be asked (no permission, no answer
in time) the microphone counts as connected, as before. A muted headset is still on, and still recorded (silence):
it's never swapped for another microphone that would hear you.

Known (Linux, through /dev/hidraw: logind lets the seat's user read it):
- Corsair HS70 Pro Wireless (1b1c:0a4f). Asked with the report C9 64, the dongle answers 64 b1 battery b3 state:
  state 1 while the headset's on, 0 while it's off (the battery 0 then). Tried 2026-10-26: turning it on and off,
  and muting and unmuting (mute doesn't change the answer at all; b1 is 0x80 for the 2 s it takes to power down).
"""
import logging
import os
import select
import time
from pathlib import Path

log = logging.getLogger(__name__)

ANSWER_WITHIN = 0.3  # seconds (it answers in about 3 ms)
SYS, DEV = Path("/sys"), Path("/dev")  # (the tests' stand-ins are elsewhere)


def _corsair_on(fd):
    """The Corsair dongle's answer: whether the headset's on, or None if it didn't answer."""
    os.write(fd, bytes([0xC9, 0x64]))
    deadline = time.monotonic() + ANSWER_WITHIN
    while (left := deadline - time.monotonic()) > 0:
        if not select.select([fd], [], [], left)[0]:
            break
        reply = os.read(fd, 64)
        if reply[:1] == b"\x64" and len(reply) >= 5:  # (other reports may come too: not ours)
            return reply[4] == 1
    return None


ASK = {(0x1b1c, 0x0a4f): _corsair_on}  # (USB vendor, product): how to ask its dongle whether the headset's on


def usb_device(card):
    """The sysfs folder of the USB device ALSA's sound card number card is on, or None."""
    try:
        interface = (SYS / "class/sound" / f"card{int(card)}" / "device").resolve(strict=True)
    except (OSError, ValueError):
        return None
    return interface.parent if (interface.parent / "idVendor").exists() else None


def hidraw(device):
    """(/dev/hidrawN, vendor, product) of the HID interface of the USB device folder device, or None."""
    for node in sorted((SYS / "class/hidraw").glob("hidraw*")):
        try:
            path = node.resolve(strict=True)
        except OSError:
            continue
        if device in path.parents:
            return DEV / node.name, int((device / "idVendor").read_text(), 16), \
                int((device / "idProduct").read_text(), 16)
    return None


def off(card):
    """Whether the headset whose dongle is ALSA sound card card is off, as far as its dongle says: True only when
    it says so; False if it's on, or isn't a headset we know how to ask, or can't be asked."""
    device = usb_device(card)
    found = device and hidraw(device)
    if not found or (found[1], found[2]) not in ASK:
        return False
    try:
        fd = os.open(found[0], os.O_RDWR | os.O_NONBLOCK)
    except OSError as err:
        log.info("headset: can't ask %s whether it's on: %s", found[0], err)
        return False
    try:
        on = ASK[found[1], found[2]](fd)
    except OSError as err:
        log.info("headset: couldn't ask %s whether it's on: %s", found[0], err)
        on = None
    finally:
        os.close(fd)
    return on is False
