"""Native Unicode input on macOS and Windows. Never pastes clipboard content."""

from __future__ import annotations

import ctypes
import sys
from typing import ClassVar


class MacKeyboard:
    HOTKEYS: ClassVar = {"start": 97, "pause": 100, "stop": 101}  # F6, F8, F9

    def __init__(self) -> None:
        import AppKit
        import Quartz

        self.q = Quartz
        self.workspace = AppKit.NSWorkspace.sharedWorkspace()
        self.source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStatePrivate)

    def check_access(self) -> None:
        if not self.q.CGPreflightPostEventAccess():
            self.q.CGRequestPostEventAccess()
            raise PermissionError(
                "Разрешите Human Typer в Настройки системы → Конфиденциальность "
                "и безопасность → Универсальный доступ. Затем перезапустите приложение."
            )

    def foreground(self) -> int:
        app = self.workspace.frontmostApplication()
        return int(app.processIdentifier()) if app else 0

    def modifiers_down(self) -> bool:
        q = self.q
        flags = q.CGEventSourceFlagsState(q.kCGEventSourceStateHIDSystemState)
        return bool(
            flags
            & (
                q.kCGEventFlagMaskShift
                | q.kCGEventFlagMaskControl
                | q.kCGEventFlagMaskAlternate
                | q.kCGEventFlagMaskCommand
            )
        )

    def hotkeys(self) -> set[str]:
        return {
            name
            for name, code in self.HOTKEYS.items()
            if self.q.CGEventSourceKeyState(self.q.kCGEventSourceStateHIDSystemState, code)
        }

    def _key(self, code: int, text: str = "", shift: bool = False) -> None:
        q = self.q
        # CoreGraphics counts UTF-16 code units, not Python code points (emoji = 2).
        units = len(text.encode("utf-16-le")) // 2
        for down in (True, False):
            event = q.CGEventCreateKeyboardEvent(self.source, code, down)
            if event is None:
                raise RuntimeError("Не удалось создать событие клавиатуры")
            q.CGEventSetFlags(event, q.kCGEventFlagMaskShift if shift else 0)
            if text:
                q.CGEventKeyboardSetUnicodeString(event, units, text)
            q.CGEventPost(q.kCGHIDEventTap, event)

    def write(self, text: str) -> None:
        self._key(0, text)

    def backspace(self) -> None:
        self._key(51)

    def newline(self, soft: bool) -> None:
        self._key(36, shift=soft)

    def move(self, direction: str) -> None:
        self._key({"left": 123, "right": 124}[direction])


class WindowsKeyboard:
    HOTKEYS: ClassVar = {"start": 0x75, "pause": 0x77, "stop": 0x78}

    def __init__(self) -> None:
        from ctypes import wintypes as w

        pointer = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", w.WORD),
                ("wScan", w.WORD),
                ("dwFlags", w.DWORD),
                ("time", w.DWORD),
                ("dwExtraInfo", pointer),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", w.LONG),
                ("dy", w.LONG),
                ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD),
                ("time", w.DWORD),
                ("dwExtraInfo", pointer),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("data",)
            _fields_ = [("type", w.DWORD), ("data", INPUTUNION)]

        self.INPUT = INPUT
        self.KEYBDINPUT = KEYBDINPUT
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = (w.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self.user32.SendInput.restype = w.UINT
        self.user32.GetForegroundWindow.restype = w.HWND
        self.user32.GetWindowThreadProcessId.argtypes = (w.HWND, ctypes.POINTER(w.DWORD))
        self.user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user32.GetAsyncKeyState.restype = w.SHORT
        self.w = w

    def check_access(self) -> None:
        pass  # SendInput reports blocked input, including elevated target applications.

    def foreground(self) -> int:
        pid = self.w.DWORD()
        self.user32.GetWindowThreadProcessId(self.user32.GetForegroundWindow(), ctypes.byref(pid))
        return int(pid.value)

    def modifiers_down(self) -> bool:
        return any(
            self.user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)
        )

    def hotkeys(self) -> set[str]:
        return {
            name for name, vk in self.HOTKEYS.items() if self.user32.GetAsyncKeyState(vk) & 0x8000
        }

    def _input(self, vk: int = 0, scan: int = 0, flags: int = 0):
        event = self.INPUT()
        event.type = 1
        event.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        return event

    def _send(self, events: list) -> None:
        array = (self.INPUT * len(events))(*events)
        sent = self.user32.SendInput(len(events), array, ctypes.sizeof(self.INPUT))
        if sent != len(events):
            # Release modifiers if a partially accepted Shift+Enter left Shift pressed.
            self.user32.SendInput(
                1, (self.INPUT * 1)(self._input(0x10, flags=2)), ctypes.sizeof(self.INPUT)
            )
            raise PermissionError(
                "Windows заблокировала ввод. Проверьте, что целевое приложение "
                "не запущено с повышенными правами."
            )

    def write(self, text: str) -> None:
        encoded = text.encode("utf-16-le")
        events = []
        for i in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[i : i + 2], "little")
            events.extend((self._input(scan=unit, flags=4), self._input(scan=unit, flags=6)))
        self._send(events)

    def backspace(self) -> None:
        self._send([self._input(8), self._input(8, flags=2)])

    def newline(self, soft: bool) -> None:
        events = [self._input(0x0D), self._input(0x0D, flags=2)]
        if soft:
            events = [self._input(0x10), *events, self._input(0x10, flags=2)]
        self._send(events)

    def move(self, direction: str) -> None:
        vk = {"left": 0x25, "right": 0x27}[direction]
        self._send([self._input(vk, flags=1), self._input(vk, flags=3)])


def create_keyboard():
    if sys.platform == "darwin":
        return MacKeyboard()
    if sys.platform == "win32":
        return WindowsKeyboard()
    raise RuntimeError("Human Typer поддерживает macOS и Windows.")
