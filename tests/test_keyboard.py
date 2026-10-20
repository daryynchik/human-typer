import ctypes
import sys

import pytest

from human_typer.keyboard import MacKeyboard, WindowsKeyboard


class QuartzFake:
    kCGEventFlagMaskShift = 1
    kCGHIDEventTap = 0

    def __init__(self):
        self.events = []

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return {"code": code, "down": down}

    def CGEventSetFlags(self, event, flags):
        event["flags"] = flags

    def CGEventKeyboardSetUnicodeString(self, event, units, text):
        event["unicode"] = (units, text)

    def CGEventPost(self, tap, event):
        self.events.append(event)


def test_mac_emoji_uses_two_utf16_units_and_balanced_events():
    keyboard = MacKeyboard.__new__(MacKeyboard)
    keyboard.q = QuartzFake()
    keyboard.source = None
    keyboard.write("🙂")
    assert [e["down"] for e in keyboard.q.events] == [True, False]
    assert all(e["unicode"] == (2, "🙂") for e in keyboard.q.events)
    keyboard.newline(True)
    assert all(e["flags"] == 1 for e in keyboard.q.events[-2:])
    keyboard.move("left")
    keyboard.move("right")
    assert [e["code"] for e in keyboard.q.events[-4:]] == [123, 123, 124, 124]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native ABI")
def test_windows_input_layout_and_unicode_surrogates():
    keyboard = WindowsKeyboard()
    assert ctypes.sizeof(keyboard.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    events = []

    class User32Fake:
        def SendInput(self, count, array, size):
            events.extend(
                (array[i].ki.wVk, array[i].ki.wScan, array[i].ki.dwFlags) for i in range(count)
            )
            return count

    keyboard.user32 = User32Fake()
    keyboard.write("🙂")
    assert events == [(0, 0xD83D, 4), (0, 0xD83D, 6), (0, 0xDE42, 4), (0, 0xDE42, 6)]
    keyboard.newline(True)
    assert events[-4:] == [(0x10, 0, 0), (0x0D, 0, 0), (0x0D, 0, 2), (0x10, 0, 2)]
    keyboard.move("left")
    keyboard.move("right")
    assert events[-4:] == [(0x25, 0, 1), (0x25, 0, 3), (0x27, 0, 1), (0x27, 0, 3)]
