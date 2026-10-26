"""A wireless headset that's off while its dongle's still plugged in doesn't count as a connected microphone, where
its dongle can say so (dictate/headsets.py): asked here of a stand-in dongle, through a stand-in /sys and /dev."""
import os
import socket
import threading

import pytest

from dictate import headsets

ON, OFF, POWERING_DOWN = "64 00 5a b1 01", "64 00 00 33 00", "64 80 5b b1 01"  # (the real dongle's answers)


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A /sys with ALSA card 2 on a USB device (a Corsair dongle unless said otherwise), its HID interface hidraw0;
    and /dev/hidraw0: a socket whose other end answers as answer() says (None: not at all)."""
    sys_, dev = tmp_path / "sys", tmp_path / "dev"
    usb = sys_ / "devices/usb3/3-2/3-2.1"
    (usb / "3-2.1:1.0").mkdir(parents=True)
    (usb / "3-2.1:1.3/0003:1B1C:0A4F.0001/hidraw/hidraw0").mkdir(parents=True)
    (sys_ / "class/sound").mkdir(parents=True)
    (sys_ / "class/hidraw").mkdir(parents=True)
    (sys_ / "class/sound/card2").mkdir()
    (sys_ / "class/sound/card2/device").symlink_to(usb / "3-2.1:1.0")
    (sys_ / "class/hidraw/hidraw0").symlink_to(usb / "3-2.1:1.3/0003:1B1C:0A4F.0001/hidraw/hidraw0")
    dev.mkdir()
    monkeypatch.setattr(headsets, "SYS", sys_)
    monkeypatch.setattr(headsets, "DEV", dev)
    state = {"answers": [ON], "ids": ("1b1c", "0a4f"), "asked": []}

    def ids(vendor, product):
        (usb / "idVendor").write_text(vendor + "\n")
        (usb / "idProduct").write_text(product + "\n")
    ids(*state["ids"])
    ours, dongle = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)  # (a report per read, as hidraw)
    real_open = os.open
    monkeypatch.setattr(headsets.os, "open", lambda path, flags: os.dup(ours.fileno()) if str(path) == str(
        dev / "hidraw0") else real_open(path, flags))

    def answer():
        while True:
            try:
                asked = dongle.recv(64)
            except OSError:
                return
            if not asked:
                return
            state["asked"].append(asked.hex(" "))
            for reply in state["answers"]:
                if reply:
                    dongle.send(bytes.fromhex(reply))
    threading.Thread(target=answer, daemon=True).start()
    state["ids_"] = ids
    yield state
    ours.close()
    dongle.close()


def test_a_headset_that_is_off_is_off(machine):
    machine["answers"] = [OFF]

    assert headsets.off(2) is True
    assert machine["asked"] == ["c9 64"]


def test_a_headset_that_is_on_is_not(machine):
    machine["answers"] = [ON]
    assert headsets.off(2) is False
    machine["answers"] = [POWERING_DOWN]  # (still connected, for the 2 s it takes)
    assert headsets.off(2) is False


def test_other_reports_from_the_dongle_are_not_its_answer(machine):
    machine["answers"] = ["01 02 03", OFF]

    assert headsets.off(2) is True


def test_a_dongle_that_does_not_answer_counts_as_on(machine):
    machine["answers"] = [None]

    assert headsets.off(2) is False  # (never skip a microphone without being told plainly)


def test_a_device_we_do_not_know_how_to_ask_is_not_asked(machine):
    machine["ids_"]("046d", "0893")  # (a webcam)

    assert headsets.off(2) is False
    assert machine["asked"] == []


def test_a_card_that_is_not_there_is_not_off(machine):
    assert headsets.off(7) is False
