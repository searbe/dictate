#!/bin/sh
# Linux: SteamOS / KDE (the main platform), or Ubuntu 24.04+ / Debian. Installs everything into this folder
# only: .venv (Python deps), bin/ (llama.cpp) and models/. Safe to re-run (e.g. after a SteamOS update
# changes the system Python). On Ubuntu/Debian it first installs the system pieces SteamOS already ships.
set -e
cd "$(dirname "$0")"

ubuntu_prereqs() {
    # GTK, evdev and tray bindings, venv, PipeWire's pw-record/pw-play, and Vulkan for llama.cpp
    missing=""
    for p in python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-evdev \
             gir1.2-dbusmenu-glib-0.4 gir1.2-dbusmenu-gtk3-0.4 pipewire-bin libvulkan1 libgomp1; do
        dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
    done
    if [ -n "$missing" ]; then
        echo "Installing system packages (needs sudo):$missing"
        sudo apt-get update -q && sudo apt-get install -y $missing
    fi
    # The hotkey reads the keyboards and pasting uses a virtual keyboard (/dev/uinput). SteamOS allows both
    # for the logged-in user through Steam's udev rules; Ubuntu doesn't, so add an equivalent rule.
    if ! python3 -c 'import os, sys, evdev
keyboards = [p for p in evdev.list_devices() if evdev.ecodes.KEY_A in evdev.InputDevice(p).capabilities().get(1, [])]
sys.exit(0 if keyboards and os.access("/dev/uinput", os.W_OK) else 1)' 2>/dev/null; then
        echo "Giving your login session access to keyboards and /dev/uinput (needs sudo)"
        sudo mkdir -p /etc/udev/rules.d
        sudo tee /etc/udev/rules.d/70-dictate.rules >/dev/null <<'EOR'
# Dictate: let the logged-in user read keyboards (global hotkey) and use /dev/uinput (pasting)
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_KEYBOARD}=="1", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOR
        sudo modprobe uinput || true
        sudo udevadm control --reload-rules
        sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
        echo "If the hotkey doesn't work straight away, log out and back in."
    fi
}

ID="" ID_LIKE=""
[ -r /etc/os-release ] && . /etc/os-release
case " $ID $ID_LIKE " in
    *" ubuntu "* | *" debian "*) ubuntu_prereqs ;;
esac

# --system-site-packages: reuse the system's GTK (gi) and evdev bindings, read-only
.venv/bin/python -c "" 2>/dev/null || { rm -rf .venv; python3 -m venv --system-site-packages .venv; }
.venv/bin/pip install -q --no-cache-dir --disable-pip-version-check --upgrade --upgrade-strategy eager -e .
.venv/bin/python scripts/fetch.py

cat > dictate.desktop <<EOD
[Desktop Entry]
Type=Application
Name=Dictate
Exec="$PWD/.venv/bin/python" "$PWD/dictate.py"
Icon=$PWD/dictate/icon.png
StartupWMClass=dictate
EOD
echo "Done. Run: python dictate.py"
