"""Timer-driven typing; no threads, clipboard writes, or blocking sleeps."""

from __future__ import annotations

import os
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Keyboard(Protocol):
    def check_access(self) -> None: ...
    def foreground(self) -> int: ...
    def modifiers_down(self) -> bool: ...
    def write(self, text: str) -> None: ...
    def backspace(self) -> None: ...
    def newline(self, soft: bool) -> None: ...


class State(StrEnum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class Settings:
    cpm: int = 240
    variation: float = 0.35
    natural_pauses: bool = True
    typo_rate: float = 0.02
    delete_before: int = 0
    countdown: float = 4.0
    soft_newlines: bool = True

    def validate(self) -> None:
        if not 20 <= self.cpm <= 1200:
            raise ValueError("Скорость должна быть от 20 до 1200 символов в минуту.")
        if not 0 <= self.variation <= 0.8 or not 0 <= self.typo_rate <= 0.1:
            raise ValueError("Некорректные настройки ритма или исправлений.")
        if not 0 <= self.delete_before <= 10000 or not 1 <= self.countdown <= 15:
            raise ValueError("Некорректное число удалений или время отсчёта.")


@dataclass(frozen=True)
class Operation:
    kind: str
    text: str = ""
    completes: bool = False


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    if not text:
        raise ValueError("Буфер обмена пуст. Скопируйте текст или введите его в окно.")
    if any((ord(c) < 32 and c != "\n") or ord(c) == 127 for c in text):
        raise ValueError("В тексте есть управляющие символы. Удалите их перед запуском.")
    try:
        text.encode("utf-16-le")
    except UnicodeEncodeError as exc:
        raise ValueError("В тексте есть некорректный Unicode-символ.") from exc
    return text


class TypingEngine:
    def __init__(
        self,
        keyboard: Keyboard,
        settings: Settings | None = None,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        own_pid: int | None = None,
    ) -> None:
        self.keyboard = keyboard
        self.settings = settings or Settings()
        self.clock = clock
        self.rng = rng or random.Random()
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.state = State.IDLE
        self.text = ""
        self.position = 0
        self.target = 0
        self.message = "Готов к работе"
        self.deadline = 0.0
        self.remaining = 0.0
        self.deletions_left = 0
        self.pending: deque[Operation] = deque()

    @property
    def active(self) -> bool:
        return self.state in (State.COUNTDOWN, State.RUNNING, State.PAUSED)

    @property
    def seconds_left(self) -> float:
        return max(0.0, self.deadline - self.clock())

    def start(self, text: str) -> None:
        if self.active:
            return
        self.settings.validate()
        normalized = normalize_text(text)
        self.keyboard.check_access()
        self.text = normalized
        self.position = 0
        self.deletions_left = self.settings.delete_before
        self.pending.clear()
        self.remaining = 0
        self.target = 0
        self.state = State.COUNTDOWN
        self.deadline = self.clock() + self.settings.countdown
        self.message = "Выберите поле для ввода"

    def pause(self, reason: str = "Пауза") -> None:
        if self.state not in (State.COUNTDOWN, State.RUNNING):
            return
        self.remaining = self.seconds_left if self.state == State.RUNNING else 0.0
        self.state = State.PAUSED
        self.message = reason

    def resume(self) -> None:
        if self.state != State.PAUSED:
            return
        self.keyboard.check_access()
        self.state = State.COUNTDOWN
        self.deadline = self.clock() + self.settings.countdown
        self.message = "Выберите поле для продолжения"

    def stop(self) -> None:
        if self.active:
            self.state = State.STOPPED
            self.message = "Остановлено"
            self.pending.clear()

    def _delay(self, char: str = "") -> float:
        s = self.settings
        delay = 60.0 / s.cpm * self.rng.uniform(1 - s.variation, 1 + s.variation)
        if s.natural_pauses:
            if char in ".!?;:\n" and char:
                delay += self.rng.uniform(0.35, 1.0)
            elif char == " " and self.rng.random() < 0.12:
                delay += self.rng.uniform(0.15, 0.6)
            elif self.rng.random() < 0.015:
                delay += self.rng.uniform(0.5, 1.4)
        return max(0.01, delay)

    def _plan_character(self) -> None:
        char = self.text[self.position]
        # Typos are single letters, so a single Backspace always undoes the typo.
        alphabet = ""
        if char.lower() in "abcdefghijklmnopqrstuvwxyz":
            alphabet = "abcdefghijklmnopqrstuvwxyz"
        elif char.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя":
            alphabet = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
        if alphabet and self.rng.random() < self.settings.typo_rate:
            wrong = self.rng.choice(alphabet.replace(char.lower(), ""))
            if char.isupper():
                wrong = wrong.upper()
            self.pending.extend((Operation("write", wrong), Operation("backspace")))
        self.pending.append(Operation("newline" if char == "\n" else "write", char, True))

    def tick(self) -> None:
        """At most one keystroke per tick; delayed UI frames never produce a burst."""
        if self.state not in (State.COUNTDOWN, State.RUNNING):
            return
        try:
            now = self.clock()
            if self.state == State.COUNTDOWN:
                if now < self.deadline:
                    return
                target = self.keyboard.foreground()
                if not target or target == self.own_pid:
                    self.pause("Выберите другое приложение и нажмите F8")
                    return
                if self.keyboard.modifiers_down():
                    self.pause("Отпустите Ctrl / Alt / Shift / Cmd и нажмите F8")
                    return
                self.target = target
                self.state = State.RUNNING
                self.message = "Печатаю"
                self.deadline = now + self.remaining
                self.remaining = 0
            if self.keyboard.foreground() != self.target:
                self.pause("Окно сменилось · F8 для продолжения")
                return
            if self.keyboard.modifiers_down():
                self.pause("Нажата клавиша-модификатор · F8 для продолжения")
                return
            if now < self.deadline:
                return
            if self.deletions_left:
                self.keyboard.backspace()
                self.deletions_left -= 1
                self.message = "Удаляю перед вводом"
                self.deadline = now + self._delay()
                return
            if not self.pending:
                if self.position == len(self.text):
                    self.state = State.COMPLETED
                    self.message = "Готово! Текст напечатан"
                    return
                self._plan_character()
            op = self.pending[0]
            if op.kind == "backspace":
                self.keyboard.backspace()
            elif op.kind == "newline":
                self.keyboard.newline(self.settings.soft_newlines)
            else:
                self.keyboard.write(op.text)
            self.pending.popleft()
            if op.completes:
                self.position += 1
            self.message = "Исправляю букву" if not op.completes else "Печатаю"
            self.deadline = now + self._delay(op.text if op.completes else "")
        except Exception as exc:
            self.state = State.ERROR
            self.message = f"Ввод остановлен: {exc}"
