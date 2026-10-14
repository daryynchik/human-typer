import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from test_engine import FakeKeyboard

from human_typer.app import STYLE, MainWindow
from human_typer.engine import State


def test_ui_source_edit_pause_stop_and_live_settings():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window = MainWindow(FakeKeyboard(), demo=True)
    window._set_text("Привет")
    assert window.clipboard_source.isChecked()
    window.editor.insertPlainText("!")
    assert not window.clipboard_source.isChecked()
    window._start()
    assert window.engine.state == State.COUNTDOWN
    assert window.editor.isReadOnly()
    window.speed.setValue(500)
    assert window.engine.settings.cpm == 500
    window._pause_resume()
    assert window.engine.state == State.PAUSED
    window._pause_resume()
    assert window.engine.state == State.COUNTDOWN
    window.stop_button.click()
    window._render()
    assert window.engine.state == State.STOPPED
    assert not window.editor.isReadOnly()
    window.close()


def test_f9_wins_over_other_hotkeys_and_holding_does_not_restart():
    app = QApplication.instance() or QApplication([])
    keyboard = FakeKeyboard()
    window = MainWindow(keyboard, demo=True)
    window._set_text("abc")
    window.clipboard_source.setChecked(False)
    window._start()
    keyboard.hotkeys = lambda: {"start", "pause", "stop"}
    window._tick()
    assert window.engine.state == State.STOPPED
    window._tick()
    assert window.engine.state == State.STOPPED
    window.close()
    app.processEvents()
