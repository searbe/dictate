"""The keys Dictate presses to paste, or to type text on another computer, on Linux (a uinput virtual keyboard).
The virtual keyboard is replaced by one that records key presses; the expected keys come from the standard
US and UK layouts, written out independently here."""
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux types through uinput")
evdev = pytest.importorskip("evdev")
e = evdev.ecodes

US_SHIFTED = dict(zip("1234567890-=[];',./`\\", '!@#$%^&*()_+{}:"<>?~|'))
NAMES = {"-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE", ";": "SEMICOLON", "'": "APOSTROPHE",
         ",": "COMMA", ".": "DOT", "/": "SLASH", "`": "GRAVE", "\\": "BACKSLASH", " ": "SPACE"}
UK_CHANGES = {(e.KEY_2, True): '"', (e.KEY_APOSTROPHE, True): "@", (e.KEY_3, True): "£",
              (e.KEY_BACKSLASH, False): "#", (e.KEY_BACKSLASH, True): "~", (e.KEY_102ND, False): "\\",
              (e.KEY_102ND, True): "|", (e.KEY_GRAVE, True): "¬"}


def layout(uk):
    """(key code, shift) -> character, for a US or UK keyboard."""
    keys = {}
    for c in "abcdefghijklmnopqrstuvwxyz0123456789" + "".join(NAMES):
        code = getattr(e, "KEY_" + NAMES.get(c, c.upper()))
        keys[code, False] = c
        keys[code, True] = c.upper() if c.isalpha() else US_SHIFTED.get(c, c)
    if uk:
        keys.update(UK_CHANGES)
    return keys


class Keyboard:
    """Stands in for evdev.UInput: remembers every key event."""

    def __init__(self, *_, **__):
        self.events = []

    def write(self, kind, code, value):
        if kind == e.EV_KEY:
            self.events.append((code, value))

    def syn(self):
        pass

    def typed(self, uk=False):
        """What these key presses produce on a US or UK keyboard (Shift+Enter shows as "⇧⏎")."""
        keys, shift, out = layout(uk), False, ""
        for code, down in self.events:
            if code == e.KEY_LEFTSHIFT:
                shift = bool(down)
            elif down and code == e.KEY_ENTER:
                out += "⇧⏎" if shift else "⏎"
            elif down:
                out += keys[code, shift]
        return out


@pytest.fixture
def paster(monkeypatch, tmp_path):
    """Dictate's paster, on a computer whose KDE keyboard layout is set by layout("gb"); default US."""
    from dictate import osio
    monkeypatch.setattr(osio.evdev, "UInput", Keyboard)
    monkeypatch.setattr(osio.time, "sleep", lambda s: None)
    monkeypatch.setenv("HOME", str(tmp_path))

    def make(kde_layout=None):
        if kde_layout:
            (tmp_path / ".config").mkdir(exist_ok=True)
            (tmp_path / ".config/kxkbrc").write_text(f"[Layout]\nLayoutList={kde_layout},us\nUse=true\n")
        return osio.Paster()
    return make


def test_text_is_typed_exactly_on_a_us_keyboard(paster):
    p = paster()
    p.type_text('Hi Sam, it\'s 5:30 @ "Joe\'s" (cost: $12.50) - ok? #1 ~/x|y\\z')
    assert p.kbd.typed() == 'Hi Sam, it\'s 5:30 @ "Joe\'s" (cost: $12.50) - ok? #1 ~/x|y\\z'


def test_text_is_typed_exactly_on_a_uk_keyboard(paster):
    p = paster("gb")
    p.type_text('Email me@example.com "now", it\'s £5 #2 ~ back\\slash | pipe')
    assert p.kbd.typed(uk=True) == 'Email me@example.com "now", it\'s £5 #2 ~ back\\slash | pipe'


def test_new_lines_are_shift_enter_so_chat_apps_dont_send_early(paster):
    p = paster()
    p.type_text("line one\nline two")
    assert p.kbd.typed() == "line one⇧⏎line two"


def test_typographic_punctuation_and_accents_are_typed_as_plain_characters(paster):
    p = paster()
    p.type_text("“Quote” — it’s a café… ok")
    assert p.kbd.typed() == '"Quote" - it\'s a cafe... ok'


def test_characters_the_keyboard_cannot_type_are_skipped(paster):
    p = paster()
    p.type_text("see you 🍺 soon €")
    assert p.kbd.typed() == "see you  soon "


def test_every_key_pressed_is_released(paster):
    p = paster("gb")
    p.type_text("Mixed CASE @ £ text\nend")
    held = set()
    for code, down in p.kbd.events:
        (held.add if down else held.discard)(code)
    assert held == set()


def test_paste_presses_ctrl_v(paster):
    p = paster()
    p.paste(terminal=False)
    assert p.kbd.events == [(e.KEY_LEFTCTRL, 1), (e.KEY_V, 1), (e.KEY_V, 0), (e.KEY_LEFTCTRL, 0)]


def test_paste_into_a_terminal_presses_ctrl_shift_v(paster):
    p = paster()
    p.paste(terminal=True)
    assert p.kbd.events == [(e.KEY_LEFTCTRL, 1), (e.KEY_LEFTSHIFT, 1), (e.KEY_V, 1), (e.KEY_V, 0),
                            (e.KEY_LEFTSHIFT, 0), (e.KEY_LEFTCTRL, 0)]
