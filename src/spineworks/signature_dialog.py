"""Local workflow signature selection and remembered author spelling."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spineworks.humdrum import HumdrumDocument
from spineworks.signatures import WORKFLOWS, existing_signatures

NAME_SETTING = "signatures/name"


class SignatureDialog(QDialog):
    def __init__(self, document: HumdrumDocument, settings: QSettings, parent=None):
        super().__init__(parent)
        self.document = document
        self.settings = settings
        self.setWindowTitle("Dodaj podpis")
        self.resize(560, 400)
        layout = QVBoxLayout(self)
        self.name = QLineEdit(str(settings.value(NAME_SETTING, "")))
        self.name.setReadOnly(bool(self.name.text().strip()))
        notice = QLabel(
            "Wpisz imię i nazwisko dokładnie tak, jak mają pojawiać się w podpisach plików. "
            "Zachowamy podaną pisownię i wielkość liter."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        row.addWidget(self.name)
        change = QPushButton("Zmień użytkownika…")
        change.clicked.connect(self.edit_name)
        row.addWidget(change)
        layout.addLayout(row)
        self.workflow = QComboBox()
        for key, spec in WORKFLOWS.items():
            self.workflow.addItem(spec.label, key)
        layout.addWidget(self.workflow)
        self.existing_panel = QWidget()
        existing_layout = QVBoxLayout(self.existing_panel)
        existing_layout.addWidget(QLabel("Wybierz istniejący podpis (numery linii w dokumencie):"))
        self.existing = QComboBox()
        existing_layout.addWidget(self.existing)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        existing_layout.addWidget(self.preview)
        self.action = QComboBox()
        self.action.addItem("Dodaj swój pod spodem", "add")
        self.action.addItem("Zamień", "replace")
        existing_layout.addWidget(self.action)
        layout.addWidget(self.existing_panel)
        layout.addWidget(QLabel("Data zostanie pobrana z komputera w chwili zatwierdzenia."))
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Zatwierdź")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.workflow.currentIndexChanged.connect(self.update_existing)
        self.existing.currentIndexChanged.connect(self.update_preview)
        self.name.textChanged.connect(self.validate_name)
        self.update_existing()
        self.validate_name()

    def edit_name(self):
        self.name.setReadOnly(False)
        self.name.setFocus()

    def validate_name(self):
        name = self.name.text()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(name.strip()) and not any(c in name for c in "\r\n\t")
        )

    def update_existing(self):
        self.existing.clear()
        for signature in existing_signatures(self.document, self.workflow.currentData()):
            label = ", ".join(str(i + 1) for i in signature.positions)
            if len(signature.positions) == 1:
                label += " (podpis niekompletny)"
            self.existing.addItem(label, signature)
        self.existing_panel.setVisible(self.existing.count() > 0)
        self.action.setCurrentIndex(0)
        self.update_preview()

    def update_preview(self):
        selected = self.existing.currentData()
        self.preview.setPlainText(selected.text(self.document) if selected else "")
