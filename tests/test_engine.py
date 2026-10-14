import random

import pytest

from human_typer.engine import Settings, State, TypingEngine, normalize_text


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeKeyboard:
    def __init__(self):
        self.pid = 22
        self.modified = False
        self.buffer = ""
        self.events = []
        self.fail = False

    def check_access(self):
        if self.fail:
            raise PermissionError("access denied")

    def foreground(self):
        return self.pid

    def modifiers_down(self):
        return self.modified

    def hotkeys(self):
        return set()

    def write(self, text):
        if self.fail:
            raise OSError("input blocked")
        self.events.append(("write", text))
        self.buffer += text

    def backspace(self):
        self.events.append(("backspace", ""))
        self.buffer = self.buffer[:-1]

    def newline(self, soft):
        self.events.append(("newline", soft))
        self.buffer += "\n"


def setup_engine(**settings):
    clock = FakeClock()
    keyboard = FakeKeyboard()
    engine = TypingEngine(keyboard, Settings(**settings), clock, random.Random(3), own_pid=11)
    return engine, keyboard, clock


def finish(engine, clock):
    for _ in range(10000):
        clock.now += 10
        engine.tick()
        if engine.state == State.COMPLETED:
            return
        assert engine.state in (State.COUNTDOWN, State.RUNNING)
    pytest.fail("typing never completed")


def test_unicode_and_normalization_preserve_final_text():
    e, k, c = setup_engine(typo_rate=0.1)
    text = "Привет, әлем! Hello 🙂 e\u0301\r\nline\tend"
    e.start(text)
    finish(e, c)
    assert k.buffer == normalize_text(text)
    assert e.position == len(e.text)
    assert ("newline", True) in k.events


def test_typos_are_deleted_and_corrected():
    e, k, c = setup_engine(typo_rate=0.1)
    text = "abcdef Привет " * 40
    e.start(text)
    finish(e, c)
    assert k.buffer == text
    assert sum(kind == "backspace" for kind, _ in k.events) > 10


def test_countdown_and_slow_frames_never_burst():
    e, k, c = setup_engine(countdown=4)
    e.start("abc")
    c.now = 3.9
    e.tick()
    assert k.events == []
    c.now = 100
    e.tick()
    assert k.buffer == "a"
    e.tick()
    assert k.buffer == "a"


def test_pause_and_stop_prevent_pending_keystrokes():
    e, k, c = setup_engine()
    e.start("hello")
    c.now = 5
    e.tick()
    e.pause()
    before = k.buffer
    c.now += 100
    e.tick()
    assert k.buffer == before
    e.resume()
    c.now += 3
    e.tick()
    assert k.buffer == before
    c.now += 2
    e.tick()
    e.stop()
    before = k.buffer
    c.now += 100
    e.tick()
    assert k.buffer == before
    assert e.state == State.STOPPED


def test_changed_target_and_own_window_pause():
    e, k, c = setup_engine()
    e.start("hello")
    c.now = 5
    e.tick()
    k.pid = 33
    c.now += 2
    e.tick()
    assert e.state == State.PAUSED
    assert k.buffer == "h"
    e.resume()
    k.pid = 11
    c.now += 5
    e.tick()
    assert e.state == State.PAUSED
    assert k.buffer == "h"


def test_held_modifier_pauses_without_input():
    e, k, c = setup_engine()
    e.start("abc")
    k.modified = True
    c.now = 5
    e.tick()
    assert e.state == State.PAUSED
    assert not k.events


def test_delete_before_and_no_typos():
    e, k, c = setup_engine(delete_before=3, typo_rate=0)
    k.buffer = "old"
    e.start("new")
    finish(e, c)
    assert k.buffer == "new"
    assert k.events[:3] == [("backspace", "")] * 3


def test_restarting_does_not_resume_old_run_or_repeat_deletion():
    e, k, c = setup_engine(delete_before=1, typo_rate=0)
    k.buffer = "x"
    e.start("a")
    e.start("ignored")
    assert e.text == "a"
    c.now = 5
    e.tick()
    e.pause()
    e.resume()
    finish(e, c)
    assert k.buffer == "a"
    assert k.events.count(("backspace", "")) == 1
    e.start("b")
    finish(e, c)
    assert k.buffer == "b"


def test_backend_failure_stops_run():
    e, k, c = setup_engine()
    e.start("abc")
    k.fail = True
    c.now = 5
    e.tick()
    assert e.state == State.ERROR
    assert not k.events


def test_permission_error_never_arms_countdown():
    e, k, _ = setup_engine()
    k.fail = True
    with pytest.raises(PermissionError):
        e.start("abc")
    assert e.state == State.IDLE


@pytest.mark.parametrize("text", ["", "abc\0", "\x1b", "\x7f", "\ud800"])
def test_invalid_source_is_rejected(text):
    e, k, _ = setup_engine()
    with pytest.raises(ValueError):
        e.start(text)
    assert not k.events


def test_live_speed_changes_affect_next_delay():
    e, k, c = setup_engine(cpm=60, variation=0, natural_pauses=False, typo_rate=0)
    e.start("abc")
    c.now = 5
    e.tick()
    assert e.deadline == 6
    e.settings.cpm = 600
    c.now = 6
    e.tick()
    assert e.deadline == pytest.approx(6.1)
    assert k.buffer == "ab"


def test_enter_mode_can_be_selected():
    e, k, c = setup_engine(soft_newlines=False)
    e.start("a\nb")
    finish(e, c)
    assert ("newline", False) in k.events
