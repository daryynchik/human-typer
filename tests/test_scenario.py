import itertools

import pytest
from test_engine import finish, setup_engine

from human_typer.engine import State
from human_typer.scenario import EXAMPLE, compile_program, iter_steps


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Это плохой[[слова:1]]первый набросок.", "Это первый набросок."),
        ("один два три  [[слова:2]]новый", "один новый"),
        ("Первое. Второе![[предложения:1]]Третье.", "Первое. Третье."),
        ("Первое. Черновик без точки[[предложения:1]]Готово.", "Первое. Готово."),
        ("Начало.\nЕщё мысль\n[[предложения:1]]Конец.", "Начало.\nКонец."),
        ("Цена 3.14. Всё хорошо.[[предложения:2]]Новая мысль.", "Новая мысль."),
        ("abc[[стереть:2]]de", "ade"),
        ("Старое слово. Конец.[[заменить:Старое=>Новое]] Ещё.", "Новое слово. Конец. Ещё."),
        ("abc abc[[заменить:abc=>X]]!", "abc X!"),
        ("a\nb[[заменить:a\nb=>c\nd]]!", "c\nd!"),
        ("a🙂e\u0301[[стереть:2]]b", "ab"),
        ("👨‍👩‍👧‍👦[[стереть:1]]Готово", "Готово"),
        ("🙂 старое 👨‍👩‍👧‍👦[[заменить:старое=>новое]]!", "🙂 новое 👨‍👩‍👧‍👦!"),
        (r"Текст \[[пауза:2]]", "Текст [[пауза:2]]"),
        ("abc[[стереть:0]][[слова:0]][[предложения:0]]", "abc"),
        ("abc[[заменить:b=>]]", "ac"),
    ],
)
def test_preview_and_real_operation_sequence_match(source, expected):
    program = compile_program(source)
    assert program.final_text == expected
    e, k, c = setup_engine(typo_rate=0)
    e.start(source)
    finish(e, c)
    assert k.buffer == expected
    assert k.cursor == len(expected)
    assert e.position == e.total_steps == program.total_steps
    assert "[[" not in k.buffer or "\\[[" in source


@pytest.mark.parametrize(
    "source",
    [
        "abc[[слова:4]]",
        "abc[[стереть:4]]",
        "abc[[предложения:2]]",
        "[[стереть:1]]",
        "abc[[заменить:missing=>x]]",
        "abc[[заменить:=>x]]",
        "abc[[заменить:bad]]",
        "abc[[пауза:-1]]",
        "abc[[пауза:nan]]",
        "abc[[пауза:inf]]",
        "[[пауза:86401]]",
        "abc[[слова:1.5]]",
        "abc[[неизвестно:1]]",
        "abc[[пауза:2]",
        "[[скорость:0]]",
        "e\u0301[[заменить:e=>a]]",
    ],
)
def test_invalid_scenario_is_rejected_before_access_or_output(source):
    e, k, _ = setup_engine()
    k.fail = True
    with pytest.raises(ValueError, match="Строка"):
        e.start(source)
    assert e.state == State.IDLE
    assert not k.events


def test_error_has_line_and_column():
    with pytest.raises(ValueError, match="Строка 2, столбец 3"):
        compile_program("hello\nxx[[bad]]")


def test_wait_is_exact_and_pause_preserves_remainder():
    e, k, c = setup_engine(typo_rate=0, variation=0, natural_pauses=False, cpm=600)
    e.start("a[[пауза:10]]b")
    c.now = 5
    e.tick()
    c.now = 5.1
    e.tick()
    assert e.deadline == pytest.approx(15.1)
    c.now = 7.1
    e.pause()
    assert e.remaining == pytest.approx(8)
    c.now = 100
    e.resume()
    c.now = 104
    e.tick()
    assert k.buffer == "a"
    c.now = 111.9
    e.tick()
    assert k.buffer == "a"
    c.now = 112
    e.tick()
    assert k.buffer == "ab"


def test_speed_command_is_temporary_and_restart_uses_settings():
    e, _k, c = setup_engine(cpm=60, variation=0, natural_pauses=False, typo_rate=0)
    e.start("[[скорость:600]]ab")
    c.now = 5
    e.tick()
    assert e.script_cpm == 600
    assert e.settings.cpm == 60
    finish(e, c)
    e.start("x")
    assert e.script_cpm is None


def test_plain_mode_types_commands_literally():
    e, k, c = setup_engine(script_mode=False, typo_rate=0)
    source = "[[слова:100]] это текст"
    e.start(source)
    finish(e, c)
    assert k.buffer == source


def test_demo_with_random_typos_finishes_with_predicted_text():
    e, k, c = setup_engine(typo_rate=0.1)
    e.start(EXAMPLE)
    finish(e, c)
    assert k.buffer == compile_program(EXAMPLE).final_text
    assert "Цифровые инструменты" in k.buffer
    assert "Они помогают вдумчиво" in k.buffer


def test_stop_during_revision_cancels_remaining_movement_and_deletion():
    e, k, c = setup_engine(typo_rate=0)
    e.start("old suffix[[заменить:old=>new]]")
    while not any(kind == "left" for kind, _ in k.events):
        c.now += 10
        e.tick()
    e.stop()
    snapshot = (k.buffer, k.cursor, list(k.events))
    c.now += 100
    e.tick()
    assert (k.buffer, k.cursor, k.events) == snapshot


def test_million_characters_are_not_truncated_and_keystrokes_are_lazy():
    source = "я" * 1_000_001
    program = compile_program(source)
    assert program.final_text == source
    assert program.total_steps == len(source)
    assert len(program.actions) == 1
    assert len(list(itertools.islice(iter_steps(program), 3))) == 3


def test_pause_at_end_is_honored_and_zero_only_script_can_complete():
    e, k, c = setup_engine(typo_rate=0)
    e.start("[[пауза:10]]")
    c.now = 5
    e.tick()
    assert e.state == State.RUNNING
    c.now = 14
    e.tick()
    assert e.state == State.RUNNING
    c.now = 15
    e.tick()
    assert e.state == State.COMPLETED
    assert not k.events


def test_deletions_never_reach_preexisting_target_text():
    e, k, c = setup_engine(typo_rate=0)
    k.buffer = "Existing document: "
    e.start("draft[[слова:1]]final")
    finish(e, c)
    assert k.buffer == "Existing document: final"
