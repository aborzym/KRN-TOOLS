import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from spineworks.app import MainWindow
from spineworks.humdrum import HumdrumDocument
from spineworks.signature_dialog import NAME_SETTING, SignatureDialog


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    widget = MainWindow()
    widget.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    yield widget
    widget.deleteLater()
    app.processEvents()


def test_signature_undo_save_and_close(window, tmp_path, monkeypatch):
    assert not window.signature_button.isEnabled()
    path = tmp_path / "score.krn"
    original = "**kern\n4c\n*-\n"
    path.write_text(original)
    window.load_path(path)
    assert window.signature_button.isEnabled()

    def confirm(dialog):
        dialog.name.setText("Łucja de TEST")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SignatureDialog, "exec", confirm)
    window.apply_signature()
    assert len(window.undo_texts) == 1
    assert "!!!ENC-review: Łucja de TEST" in window.document.to_text()
    assert window.windowTitle().startswith("* ")
    assert path.read_text() == original
    assert window.settings.value(NAME_SETTING) == "Łucja de TEST"
    window.undo()
    assert window.document.to_text() == original
    window.apply_signature()
    assert window.save_file()
    assert "!!!ENC-review: Łucja de TEST" in path.read_text()
    window.close_file()
    assert not window.signature_button.isEnabled()


def test_cancel_preserves_document_settings_and_pending_fields(window, monkeypatch):
    window.document = HumdrumDocument.from_text('**kern\n*I"Old\n4c\n*-\n')
    window._refresh_table()
    field = window.row_inputs["instrument_name_line"][0]
    field.setText("Pending")
    original = window.document.to_text()

    def cancel(dialog):
        dialog.name.setText("Not saved")
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(SignatureDialog, "exec", cancel)
    window.apply_signature()
    assert window.document.to_text() == original
    assert window.undo_texts == []
    assert window.settings.value(NAME_SETTING) is None
    assert field.text() == "Pending"
    assert window.field_edits_dirty

    monkeypatch.setattr(
        SignatureDialog,
        "exec",
        lambda dialog: dialog.name.setText("Jan") or QDialog.DialogCode.Accepted,
    )
    window.apply_signature()
    assert field.text() == "Pending"
    assert window.field_edits_dirty


def test_dialog_shows_actual_selected_signature_and_remembers_name(window):
    window.settings.setValue(NAME_SETTING, "Anna de TEST")
    document = HumdrumDocument.from_text(
        "!!!ENC-review: A\n!!!OTL: Work\n!!!END-review: 2000\n!!!ENC-review: B\n**kern\n4c\n*-\n"
    )
    dialog = SignatureDialog(document, window.settings, window)
    assert dialog.name.text() == "Anna de TEST"
    assert dialog.name.isReadOnly()
    assert dialog.existing.count() == 2
    assert dialog.preview.toPlainText() == "!!!ENC-review: A\n!!!END-review: 2000"
    dialog.existing.setCurrentIndex(1)
    assert dialog.preview.toPlainText() == "!!!ENC-review: B"
    dialog.edit_name()
    assert not dialog.name.isReadOnly()
    dialog.workflow.setCurrentIndex(3)
    assert dialog.existing.count() == 0
