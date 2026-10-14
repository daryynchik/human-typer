from __future__ import annotations

import math
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .engine import Settings, State, TypingEngine
from .keyboard import create_keyboard

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
        self.setWindowTitle("Human Typer")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(440)
        self.resize(470, 680)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Human Typer")
        title.setObjectName("brand")
        subtitle = QLabel("Ваш текст. Живой ритм.")
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
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Скопируйте текст и нажмите «Старт».\nИли напишите текст прямо здесь."
        )
        self.editor.setMinimumHeight(135)
        self.editor.textChanged.connect(self._text_edited)
        layout.addWidget(self.editor, 1)
        self.count = QLabel("Текст хранится только в памяти")
        self.count.setObjectName("muted")
        layout.addWidget(self.count)

        card = QFrame()
        card.setObjectName("card")
        options = QVBoxLayout(card)
        options.setContentsMargins(14, 12, 14, 12)
        options.setSpacing(10)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Скорость"))
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
        self.delete.setRange(0, 10000)
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
        self.count.setText(f"{len(self.editor.toPlainText())} символов · только в памяти")

    def _set_text(self, text: str) -> None:
        self.programmatic_text = True
        self.editor.setPlainText(text)
        self.programmatic_text = False

    def _load_clipboard(self) -> None:
        if not self.engine.active:
            self._set_text(QApplication.clipboard().text())

    def _settings_changed(self, *_args) -> None:
        s = self.engine.settings
        s.cpm = self.speed.value()
        s.variation = self.variation.value() / 100
        s.typo_rate = self.typos.value() / 100
        s.natural_pauses = self.pauses.isChecked()
        s.delete_before = self.delete.value()
        s.countdown = self.countdown.value()
        s.soft_newlines = self.newlines.currentIndex() == 0
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
        if e.state == State.COUNTDOWN:
            text = f"Старт через {math.ceil(e.seconds_left)} сек · {e.message}"
        elif e.text:
            text = f"{e.message} · {e.position} / {len(e.text)}"
        else:
            text = e.message
        self.status.setText(text)
        self.progress.setValue(round(1000 * e.position / len(e.text)) if e.text else 0)

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
