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


def test_scenario_menu_inserts_notation_and_changes_source():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(FakeKeyboard(), demo=True)
    window.commands_button.menu().actions()[0].trigger()
    assert window.editor.toPlainText() == "[[пауза:2]]"
    assert not window.clipboard_source.isChecked()
    assert window.mode.currentIndex() == 1
    window._start()
    assert not window.commands_button.isEnabled()
    assert not window.mode.isEnabled()
    assert not window.preview_button.isEnabled()
    window.close()
    app.processEvents()


def test_large_editor_document_and_demo_are_not_truncated():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(FakeKeyboard(), demo=True)
    assert window.editor.maximumBlockCount() == 0
    source = ("Длинная строка.\n" * 10000) + "Конец"
    window._set_text(source)
    assert window.editor.toPlainText() == source
    assert str(len(source))[:1] in window.count.text()
    window._set_text("")
    window._load_example()
    assert "[[заменить:" in window.editor.toPlainText()
    assert window.mode.currentIndex() == 1
    assert not window.clipboard_source.isChecked()
    window.close()
    app.processEvents()
