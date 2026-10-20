"""Compile editing notation before touching the target; expand keystrokes lazily."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import regex

GRAPHEME = regex.compile(r"\X")
MARKER = regex.compile(r"\\\[\[|\[\[")
BOUNDARY = regex.compile(r"""[.!?…]+[»”"’')]*(?=\s|$)|\n+""")
ALIASES = {
    "пауза": "wait",
    "pause": "wait",
    "wait": "wait",
    "стереть": "erase",
    "delete": "erase",
    "слова": "words",
    "words": "words",
    "предложения": "sentences",
    "sentences": "sentences",
    "заменить": "replace",
    "replace": "replace",
    "скорость": "speed",
    "speed": "speed",
}

EXAMPLE = (
    "Мне кажется, эта тема очень важна.[[пауза:2]]"
    "[[предложения:1]]Технологии меняют то, как мы учимся. "
    "Они помогают быстро и легко[[пауза:1]][[слова:3]]"
    "вдумчиво разбирать сложные вопросы.\n"
    "Но готовый ответ не заменяет собственного размышления."
    "[[пауза:3]][[заменить:Технологии меняют=>Цифровые инструменты меняют]]"
    "\nПоэтому важен не только результат, но и путь к нему."
)

HELP = """Команды сценария (сами команды не печатаются)

[[пауза:2.5]] — подождать 2,5 секунды.
[[стереть:12]] — постепенно удалить 12 символов слева.
[[слова:2]] — удалить два последних слова.
[[предложения:1]] — удалить последнее предложение или незаконченный набросок.
[[заменить:старый текст=>новый текст]] — найти последнее вхождение уже
написанного фрагмента, вернуться к нему, переписать и продолжить с конца.
[[скорость:180]] — изменить скорость на 180 символов в минуту до конца запуска.

Пример:
Это плохой[[слова:1]]первый набросок.[[пауза:2]]
[[заменить:первый набросок=>продуманный текст]]

Результат: Это продуманный текст.

Для буквальных [[ напишите \\[[ или выберите режим «Обычный текст».
Пробелы и переносы вне команд печатаются буквально. Перенос внутри команды
«заменить» допускается. Внутри команды нельзя использовать ]] или => в старом
фрагменте. Ошибка в любой команде отменяет весь запуск до первого нажатия.

Команды удаляют только текст этого сценария. Слова разделяются пробелами;
предложения — . ! ? … перед пробелом/концом или переносом строки.
Сокращения вроде «т. д.» могут считаться несколькими предложениями — для точной
правки лучше «заменить». Не двигайте курсор в целевом поле во время сценария.
"""


@dataclass(frozen=True)
class Action:
    kind: str
    text: str = ""
    number: float = 0


@dataclass(frozen=True)
class Program:
    actions: tuple[Action, ...]
    final_text: str
    total_steps: int
    command_count: int


def graphemes(text: str) -> Iterator[str]:
    return (match.group() for match in GRAPHEME.finditer(text))


def grapheme_count(text: str) -> int:
    return sum(1 for _ in GRAPHEME.finditer(text))


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


def sentence_starts(text: str) -> list[int]:
    starts = []
    previous = 0
    for match in BOUNDARY.finditer(text):
        chunk = text[previous : match.end()]
        if chunk.strip():
            starts.append(previous + len(chunk) - len(chunk.lstrip()))
        previous = match.end()
    if text[previous:].strip():
        tail = text[previous:]
        starts.append(previous + len(tail) - len(tail.lstrip()))
    return starts


def compile_program(source: str, scripted: bool = True) -> Program:
    source = normalize_text(source)
    if not scripted:
        return Program((Action("type", source),), source, grapheme_count(source), 0)
    actions: list[Action] = []
    buffer = ""
    literal: list[str] = []
    steps = 0
    commands = 0

    def flush() -> None:
        nonlocal buffer, steps
        if literal:
            text = "".join(literal)
            actions.append(Action("type", text))
            buffer += text
            steps += grapheme_count(text)
            literal.clear()

    def erase(count: int) -> None:
        nonlocal buffer, steps
        clusters = list(GRAPHEME.finditer(buffer))
        if count > len(clusters):
            raise ValueError("Нельзя удалить больше символов, чем уже написал сценарий.")
        if count:
            buffer = buffer[: clusters[-count].start()]
            actions.append(Action("erase", number=count))
            steps += count

    position = 0
    while match := MARKER.search(source, position):
        literal.append(source[position : match.start()])
        if match.group().startswith("\\"):
            literal.append("[[")
            position = match.end()
            continue
        flush()
        close = source.find("]]", match.end())
        try:
            if close < 0:
                raise ValueError("Команда не закрыта: нужны ]].")
            body = source[match.end() : close]
            name, separator, argument = body.partition(":")
            kind = ALIASES.get(name.strip().lower())
            if not separator or kind is None:
                raise ValueError("Неизвестная команда. Откройте «Команды», чтобы увидеть формат.")
            if kind in ("erase", "words", "sentences", "speed"):
                if not regex.fullmatch(r"[0-9]+", argument.strip()):
                    raise ValueError("Нужно целое неотрицательное число.")
                number = int(argument.strip())
                if kind == "speed":
                    if not 20 <= number <= 1200:
                        raise ValueError("Скорость должна быть от 20 до 1200.")
                    actions.append(Action("speed", number=number))
                    steps += 1
                elif kind == "erase":
                    erase(number)
                else:
                    starts = (
                        [m.start() for m in regex.finditer(r"\S+", buffer)]
                        if kind == "words"
                        else sentence_starts(buffer)
                    )
                    if number > len(starts):
                        raise ValueError("В набранном тексте недостаточно слов или предложений.")
                    if number:
                        erase(grapheme_count(buffer[starts[-number] :]))
            elif kind == "wait":
                if not regex.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", argument.strip()):
                    raise ValueError("Пауза задаётся числом секунд, например 2.5.")
                seconds = float(argument.strip().replace(",", "."))
                if not 0 <= seconds <= 86400:
                    raise ValueError("Пауза должна быть от 0 до 86400 секунд.")
                actions.append(Action("wait", number=seconds))
                steps += 1
            elif kind == "replace":
                old, separator, new = argument.partition("=>")
                if not separator or not old:
                    raise ValueError("Формат замены: [[заменить:старое=>новое]].")
                index = buffer.rfind(old)
                if index < 0:
                    raise ValueError(f"Фрагмент для замены ещё не написан: {old[:60]!r}.")
                prefix, suffix = buffer[:index], buffer[index + len(old) :]
                left, deleted = grapheme_count(suffix), grapheme_count(old)
                if grapheme_count(prefix) + deleted + left != grapheme_count(buffer):
                    raise ValueError("Замена не должна разделять составной Unicode-символ.")
                if left:
                    actions.append(Action("left", number=left))
                actions.append(Action("erase", number=deleted))
                if new:
                    actions.append(Action("type", new))
                if left:
                    actions.append(Action("right", number=left))
                steps += 2 * left + deleted + grapheme_count(new)
                buffer = prefix + new + suffix
            commands += 1
        except ValueError as exc:
            line = source.count("\n", 0, match.start()) + 1
            column = match.start() - source.rfind("\n", 0, match.start())
            raise ValueError(f"Строка {line}, столбец {column}: {exc}") from exc
        position = close + 2
    literal.append(source[position:])
    flush()
    return Program(tuple(actions), buffer, steps, commands)


def iter_steps(program: Program) -> Iterator[Action]:
    for action in program.actions:
        if action.kind == "type":
            for cluster in graphemes(action.text):
                yield Action("newline" if cluster == "\n" else "write", cluster)
        elif action.kind in ("erase", "left", "right"):
            for _ in range(int(action.number)):
                yield Action(action.kind)
        else:
            yield action
