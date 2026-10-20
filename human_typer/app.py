from __future__ import annotations

import math
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .engine import Settings, State, TypingEngine
from .keyboard import create_keyboard
from .scenario import EXAMPLE, HELP, compile_program

STYLE = """
QWidget { background: #101724; color: #e8edf5; font-size: 13px; }
QLabel#brand { font-size: 25px; font-weight: 700; }
QLabel#muted { color: #8e9db4; font-size: 12px; }
QLabel#value { color: #8fb9ff; font-size: 15px; font-weight: 600; }
QLabel#badge { color: #93c5fd; background: #1a2d48; padding: 7px 10px; border-radius: 9px; }
QFrame#card { background: #182234; border: 1px solid #26344a; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; }
QPlainTextEdit { background: #141e2f; border: 1px solid #2c3c55; border-radius: 10px;
                padding: 10px; selection-background-color: #3461a5; }
QPushButton { background: #223149; border: 1px solid #32425c; border-radius: 8px;
              padding: 9px 12px; font-weight: 600; }
QPushButton:hover { background: #2d4160; }
QPushButton:pressed { background: #19263c; }
QPushButton#primary { background: #80b5ff; color: #0c203e; border: none; }
QPushButton#primary:hover { background: #a1c8ff; }
QPushButton#stop { color: #ffb5b5; }
QPushButton:disabled { color: #60718a; background: #1b2638; border-color: #26344a; }
QSpinBox, QDoubleSpinBox, QComboBox { background: #1d2a40; border: 1px solid #35455e;
                                    border-radius: 6px; padding: 6px; }
QSlider::groove:horizontal { height: 5px; background: #30405a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #80b5ff; border-radius: 2px; }
QSlider::handle:horizontal { background: #b1d1ff; width: 15px; margin: -5px 0;
                            border-radius: 7px; }
QProgressBar { border: none; background: #26344a; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #80b5ff; border-radius: 3px; }
QCheckBox { spacing: 7px; }
QToolTip { background: #223149; color: #e8edf5; border: 1px solid #456080; padding: 6px; }
"""


def app_icon() -> QIcon:
    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#80b5ff"))
    painter.drawRoundedRect(4, 4, 120, 120, 28, 28)
    painter.setPen(QColor("#102039"))
    font = painter.font()
    font.setPixelSize(58)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "Ht")
    painter.end()
    return QIcon(pix)


class MainWindow(QWidget):
    def __init__(self, keyboard=None, demo: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(f"Human Typer {__version__}")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(510, 640)
        self.resize(580, 800)
        self.store = QSettings("HumanTyper", "HumanTyper")
        self.engine = TypingEngine(keyboard or create_keyboard())
        self.previous_hotkeys: set[str] = set()
        self.programmatic_text = False
        self.reported_error = ""
        self.demo = demo
        self._build_ui()
        if not demo:
            self._restore()
        self.speed.setValue(self.engine.settings.cpm)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        if not demo:
            self.timer.start(20)
        self._render()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Human Typer")
        title.setObjectName("brand")
        subtitle = QLabel("От черновика к готовому тексту · 2.0")
        subtitle.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()
        badge = QLabel("Ht")
        badge.setObjectName("badge")
        header.addWidget(badge)
        layout.addLayout(header)

        source_row = QHBoxLayout()
        self.clipboard_source = QCheckBox("Последний текст из буфера")
        self.clipboard_source.setChecked(True)
        self.clipboard_source.setToolTip("При каждом старте читает текущий буфер обмена.")
        source_row.addWidget(self.clipboard_source)
        source_row.addStretch()
        self.load_button = QPushButton("Из буфера")
        self.load_button.clicked.connect(self._load_clipboard)
        source_row.addWidget(self.load_button)
        layout.addLayout(source_row)
        mode_row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Обычный текст", "Сценарий с правками"])
        self.mode.setCurrentIndex(1)
        self.mode.setToolTip("В сценарии команды [[…]] управляют правками и паузами.")
        self.mode.currentIndexChanged.connect(self._settings_changed)
        mode_row.addWidget(self.mode, 1)
        self.commands_button = QPushButton("Команды")
        commands_menu = QMenu(self.commands_button)
        for label, notation in (
            ("Пауза на 2 секунды", "[[пауза:2]]"),
            ("Удалить 1 слово", "[[слова:1]]"),
            ("Удалить 1 предложение", "[[предложения:1]]"),
            ("Удалить 5 символов", "[[стереть:5]]"),
            ("Заменить написанный фрагмент", "[[заменить:старое=>новое]]"),
            ("Сменить скорость", "[[скорость:180]]"),
        ):
            commands_menu.addAction(
                label, lambda _checked=False, text=notation: self._insert_command(text)
            )
        commands_menu.addSeparator()
        commands_menu.addAction("Справка по сценариям", self._show_help)
        self.commands_button.setMenu(commands_menu)
        mode_row.addWidget(self.commands_button)
        self.example_button = QPushButton("Пример")
        self.example_button.clicked.connect(self._load_example)
        mode_row.addWidget(self.example_button)
        layout.addLayout(mode_row)
        self.editor = QPlainTextEdit()
        self.editor.setMaximumBlockCount(0)
        self.editor.setPlaceholderText(
            "Пишите черновик и добавляйте команды:\n"
            "Это плохой[[слова:1]]первый вариант.\n"
            "[[пауза:2]][[заменить:первый=>продуманный]]\n\n"
            "Кнопка «Пример» покажет готовый сценарий."
        )
        self.editor.setMinimumHeight(135)
        self.editor.textChanged.connect(self._text_edited)
        layout.addWidget(self.editor, 1)
        info_row = QHBoxLayout()
        self.count = QLabel("Без лимита длины · только в памяти")
        self.count.setObjectName("muted")
        self.count.setWordWrap(True)
        info_row.addWidget(self.count, 1)
        self.file_button = QPushButton("Файл…")
        self.file_button.clicked.connect(self._load_file)
        self.preview_button = QPushButton("Итог и план")
        self.preview_button.clicked.connect(self._preview)
        info_row.addWidget(self.file_button)
        info_row.addWidget(self.preview_button)
        layout.addLayout(info_row)

        card = QFrame()
        card.setObjectName("card")
        options = QVBoxLayout(card)
        options.setContentsMargins(14, 12, 14, 12)
        options.setSpacing(10)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Скорость печати · это не лимит текста"))
        speed_row.addStretch()
        self.speed_value = QLabel()
        self.speed_value.setObjectName("value")
        speed_row.addWidget(self.speed_value)
        options.addLayout(speed_row)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(20, 1200)
        self.speed.valueChanged.connect(self._settings_changed)
        options.addWidget(self.speed)
        row = QHBoxLayout()
        self.pauses = QCheckBox("Естественные паузы")
        self.pauses.setChecked(True)
        self.pauses.toggled.connect(self._settings_changed)
        row.addWidget(self.pauses)
        row.addStretch()
        self.topmost = QCheckBox("Поверх окон")
        self.topmost.toggled.connect(self._toggle_topmost)
        row.addWidget(self.topmost)
        options.addLayout(row)
        self.more = QPushButton("Настроить ритм и удаления ▾")
        self.more.setCheckable(True)
        options.addWidget(self.more)
        self.advanced = QWidget()
        advanced = QVBoxLayout(self.advanced)
        advanced.setContentsMargins(0, 2, 0, 0)

        self.variation = QSpinBox()
        self.variation.setRange(0, 80)
        self.variation.setSuffix(" %")
        self.variation.setValue(35)
        self.typos = QDoubleSpinBox()
        self.typos.setRange(0, 10)
        self.typos.setSingleStep(0.5)
        self.typos.setSuffix(" %")
        self.typos.setValue(2)
        self.delete = QSpinBox()
        self.delete.setRange(0, 2147483647)
        self.delete.setToolTip("Столько нажатий Backspace будет отправлено перед вводом.")
        self.countdown = QSpinBox()
        self.countdown.setRange(1, 15)
        self.countdown.setSuffix(" сек")
        self.countdown.setValue(4)
        self.newlines = QComboBox()
        self.newlines.addItems(["Shift + Enter", "Enter"])
        self.newlines.setToolTip("Enter в мессенджерах может отправить сообщение.")
        for label, widget in (
            ("Разброс скорости", self.variation),
            ("Ошибки с исправлением", self.typos),
            ("Backspace перед вводом", self.delete),
            ("Отсчёт до старта", self.countdown),
            ("Переносы строк", self.newlines),
        ):
            line = QHBoxLayout()
            line.addWidget(QLabel(label))
            line.addStretch()
            line.addWidget(widget)
            advanced.addLayout(line)
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._settings_changed)
            else:
                widget.valueChanged.connect(self._settings_changed)
        self.advanced.hide()
        self.more.toggled.connect(self.advanced.setVisible)
        self.more.toggled.connect(
            lambda on: self.more.setText(
                "Настроить ритм и удаления ▴" if on else "Настроить ритм и удаления ▾"
            )
        )
        options.addWidget(self.advanced)
        layout.addWidget(card)

        self.status = QLabel("Готов к работе")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)
        controls = QHBoxLayout()
        self.start_button = QPushButton("▶  Старт")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        self.pause_button = QPushButton("Пауза")
        self.pause_button.clicked.connect(self._pause_resume)
        self.stop_button = QPushButton("■  Стоп")
        self.stop_button.setObjectName("stop")
        self.stop_button.clicked.connect(self.engine.stop)
        controls.addWidget(self.start_button, 2)
        controls.addWidget(self.pause_button, 1)
        controls.addWidget(self.stop_button, 1)
        layout.addLayout(controls)
        keys = QLabel("F6  буфер → ввод     F8  пауза / продолжить     F9  стоп")
        keys.setAlignment(Qt.AlignmentFlag.AlignCenter)
        keys.setObjectName("muted")
        layout.addWidget(keys)
        hint = QLabel("После старта выберите поле ввода. На Mac может понадобиться Fn.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)

    def _text_edited(self) -> None:
        if not self.programmatic_text:
            self.clipboard_source.setChecked(False)
        self.count.setText(f"{len(self.editor.toPlainText()):,} символов · без лимита длины")

    def _set_text(self, text: str) -> None:
        self.programmatic_text = True
        self.editor.setPlainText(text)
        self.programmatic_text = False

    def _load_clipboard(self) -> None:
        if not self.engine.active:
            self._set_text(QApplication.clipboard().text())

    def _insert_command(self, text: str) -> None:
        self.mode.setCurrentIndex(1)
        self.editor.insertPlainText(text)
        self.editor.setFocus()

    def _load_example(self) -> None:
        if self.editor.toPlainText():
            answer = QMessageBox.question(
                self, "Загрузить пример", "Заменить текст в окне готовым примером?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.mode.setCurrentIndex(1)
        self.clipboard_source.setChecked(False)
        self._set_text(EXAMPLE)

    def _load_file(self) -> None:
        from pathlib import Path

        name, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть сценарий или текст",
            "",
            "Текст UTF-8 (*.txt *.md *.htype);;Все файлы (*)",
        )
        if name:
            try:
                text = Path(name).read_text(encoding="utf-8-sig")
                self.clipboard_source.setChecked(False)
                self._set_text(text)
            except (OSError, UnicodeError) as exc:
                QMessageBox.warning(self, "Не удалось открыть файл", str(exc))

    def _show_help(self) -> None:
        self._text_dialog("Команды сценария", [("Справка", HELP)])

    def _text_dialog(self, title: str, pages: list[tuple[str, str]], summary: str = "") -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(680, 560)
        layout = QVBoxLayout(dialog)
        if summary:
            label = QLabel(summary)
            label.setWordWrap(True)
            layout.addWidget(label)
        tabs = QTabWidget()
        for name, text in pages:
            editor = QPlainTextEdit()
            editor.setMaximumBlockCount(0)
            editor.setReadOnly(True)
            editor.setPlainText(text)
            tabs.addTab(editor, name)
        layout.addWidget(tabs)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _preview(self) -> None:
        try:
            if self.clipboard_source.isChecked():
                self._load_clipboard()
            program = compile_program(self.editor.toPlainText(), self.mode.currentIndex() == 1)
            names = {
                "type": "Напечатать",
                "erase": "Удалить символов",
                "left": "Влево",
                "right": "Вправо",
                "wait": "Пауза, сек",
                "speed": "Скорость, симв/мин",
            }
            lines = []
            for i, action in enumerate(program.actions, 1):
                detail = repr(action.text[:120]) if action.kind == "type" else f"{action.number:g}"
                if action.kind == "type" and len(action.text) > 120:
                    detail += f" … ({len(action.text):,} символов)"
                lines.append(f"{i}. {names[action.kind]}: {detail}")
            self._text_dialog(
                "Итог и план сценария",
                [("Итоговый текст", program.final_text), ("Порядок действий", "\n".join(lines))],
                f"Команд: {program.command_count} · действий: {program.total_steps:,} · "
                f"в итоге: {len(program.final_text):,} символов. "
                "Итог рассчитан для точного ввода без автокоррекции целевого редактора.",
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка сценария", str(exc))

    def _settings_changed(self, *_args) -> None:
        s = self.engine.settings
        if s.cpm != self.speed.value():
            self.engine.script_cpm = None
        s.cpm = self.speed.value()
        s.variation = self.variation.value() / 100
        s.typo_rate = self.typos.value() / 100
        s.natural_pauses = self.pauses.isChecked()
        s.delete_before = self.delete.value()
        s.countdown = self.countdown.value()
        s.soft_newlines = self.newlines.currentIndex() == 0
        s.script_mode = self.mode.currentIndex() == 1
        self.speed_value.setText(f"{s.cpm} симв/мин")

    def _restore(self) -> None:
        s = Settings()
        for key in ("cpm", "variation", "typo_rate", "delete_before", "countdown"):
            value = self.store.value(key, getattr(s, key))
            try:
                setattr(s, key, type(getattr(s, key))(value))
            except (TypeError, ValueError):
                pass
        try:
            s.validate()
        except ValueError:
            s = Settings()
        self.variation.setValue(round(s.variation * 100))
        self.typos.setValue(s.typo_rate * 100)
        self.delete.setValue(s.delete_before)
        self.countdown.setValue(int(s.countdown))
        self.speed.setValue(s.cpm)
        self.pauses.setChecked(self.store.value("natural_pauses", True, type=bool))
        self.newlines.setCurrentIndex(
            0 if self.store.value("soft_newlines", True, type=bool) else 1
        )
        self.topmost.setChecked(self.store.value("topmost", False, type=bool))
        self.mode.setCurrentIndex(1 if self.store.value("script_mode", True, type=bool) else 0)

    def _toggle_topmost(self, on: bool) -> None:
        self.engine.pause("Пауза · изменены настройки окна")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def _start(self, _checked: bool = False, force_clipboard: bool = False) -> None:
        if self.engine.active:
            return
        try:
            self._settings_changed()
            if force_clipboard or self.clipboard_source.isChecked():
                self._load_clipboard()
            self.engine.start(self.editor.toPlainText())
        except Exception as exc:
            QMessageBox.warning(self, "Human Typer", str(exc))
        self._render()

    def _pause_resume(self) -> None:
        try:
            if self.engine.state == State.PAUSED:
                self.engine.resume()
            else:
                self.engine.pause()
        except Exception as exc:
            QMessageBox.warning(self, "Human Typer", str(exc))
        self._render()

    def _tick(self) -> None:
        try:
            current = self.engine.keyboard.hotkeys()
            pressed = current - self.previous_hotkeys
            self.previous_hotkeys = current
            # Stop takes priority over pause/start if several keys are held.
            if "stop" in pressed:
                self.engine.stop()
            elif "pause" in pressed:
                self._pause_resume()
            elif "start" in pressed:
                self._start(force_clipboard=True)
            self.engine.tick()
        except Exception as exc:
            self.engine.stop()
            self.engine.state = State.ERROR
            self.engine.message = str(exc)
        self._render()

    def _render(self) -> None:
        e = self.engine
        active = e.active
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.stop_button.setEnabled(active)
        self.pause_button.setText("Продолжить" if e.state == State.PAUSED else "Пауза")
        self.editor.setReadOnly(active)
        self.load_button.setEnabled(not active)
        self.clipboard_source.setEnabled(not active)
        self.delete.setEnabled(not active)
        self.newlines.setEnabled(not active)
        self.mode.setEnabled(not active)
        self.commands_button.setEnabled(not active)
        self.example_button.setEnabled(not active)
        self.file_button.setEnabled(not active)
        self.preview_button.setEnabled(not active)
        if e.state == State.COUNTDOWN:
            text = f"Старт через {math.ceil(e.seconds_left)} сек · {e.message}"
        elif e.text:
            text = f"{e.message} · {e.position:,} / {e.total_steps:,} действий"
        else:
            text = e.message
        self.status.setText(text)
        self.progress.setValue(round(1000 * e.position / e.total_steps) if e.total_steps else 0)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.engine.stop()
        if not self.demo:
            for key, value in vars(self.engine.settings).items():
                self.store.setValue(key, value)
            self.store.setValue("topmost", self.topmost.isChecked())
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Human Typer")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(None, "Human Typer", str(exc))
        raise SystemExit(1) from exc
    window.show()
    sys.exit(app.exec())
