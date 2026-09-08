from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from spineworks.humdrum import HumdrumDocument, HumdrumError


class MainWindow(QMainWindow):
    ROW_NAMES = {
        "exclusive_line": "Typ spine’u",
        "part_line": "Part",
        "staff_line": "Staff",
        "instrument_name_line": "Nazwa pełna",
        "instrument_abbr_line": "Nazwa skrócona",
    }

    def __init__(self) -> None:
        super().__init__()
        self.document: HumdrumDocument | None = None
        self.current_path: Path | None = None
        self.undo_texts: list[str] = []
        self.setWindowTitle("SPINEWORKS")
        self.resize(1200, 650)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        toolbar = QToolBar("Plik", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("Otwórz", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_file)
        toolbar.addAction(open_action)

        self.undo_action = QAction("Cofnij", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self.undo)
        toolbar.addAction(self.undo_action)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)

        self.file_label = QLabel("Upuść tutaj plik .krn albo wybierz „Otwórz”.")
        self.file_label.setObjectName("fileLabel")
        layout.addWidget(self.file_label)

        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.propagate_button = QPushButton("Uzupełnij przypisania spine’ów")
        self.propagate_button.setObjectName("primaryButton")
        self.propagate_button.setEnabled(False)
        self.propagate_button.clicked.connect(self.propagate_assignments)
        layout.addWidget(self.propagate_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Gotowe")

    def open_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Otwórz plik Humdrum", "", "Pliki Humdrum (*.krn);;Wszystkie pliki (*)"
        )
        if filename:
            self.load_path(Path(filename))

    def load_path(self, path: Path) -> None:
        try:
            document = HumdrumDocument.from_path(path)
        except (OSError, UnicodeError, HumdrumError) as error:
            QMessageBox.critical(self, "Nie można otworzyć pliku", str(error))
            return

        self.document = document
        self.current_path = path
        self.undo_texts.clear()
        self.undo_action.setEnabled(False)
        self.propagate_button.setEnabled(True)
        self.file_label.setText(str(path))
        self._refresh_table()
        self.statusBar().showMessage(f"Wczytano {document.spine_count} spine’ów")

    def propagate_assignments(self) -> None:
        if self.document is None:
            return
        before = self.document.to_text()
        try:
            changed = self.document.propagate_kern_assignments()
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można uzupełnić przypisań", str(error))
            return
        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage("Uzupełniono przypisania part i staff")
        else:
            self.statusBar().showMessage("Przypisania part i staff są już kompletne")

    def undo(self) -> None:
        if not self.undo_texts:
            return
        self.document = HumdrumDocument.from_text(self.undo_texts.pop())
        self.undo_action.setEnabled(bool(self.undo_texts))
        self._refresh_table()
        self.statusBar().showMessage("Cofnięto ostatnią zmianę")

    def _refresh_table(self) -> None:
        if self.document is None:
            return
        rows: list[tuple[str, int]] = []
        for attribute, label in self.ROW_NAMES.items():
            line_number = getattr(self.document.header, attribute)
            if line_number is not None:
                rows.append((label, line_number))

        self.table.setRowCount(len(rows))
        self.table.setColumnCount(self.document.spine_count)
        self.table.setHorizontalHeaderLabels(
            [f"{number + 1}\n{kind}" for number, kind in enumerate(self.document.spine_types)]
        )
        self.table.setVerticalHeaderLabels([label for label, _ in rows])
        for row, (_, line_number) in enumerate(rows):
            for column, value in enumerate(self.document.fields(line_number)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeRowsToContents()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(".krn"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.load_path(Path(event.mimeData().urls()[0].toLocalFile()))
        event.acceptProposedAction()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #101713; color: #e7f4eb; }
            QToolBar { background: #152019; border: 0; padding: 7px; spacing: 8px; }
            QToolButton { padding: 7px 12px; border-radius: 6px; }
            QToolButton:hover { background: #24372a; }
            QLabel#fileLabel { color: #b7cabe; font-size: 14px; padding: 4px; }
            QTableWidget {
                background: #121c16; alternate-background-color: #17231b;
                gridline-color: #304536; border: 1px solid #304536;
                selection-background-color: #177245;
            }
            QHeaderView::section {
                background: #1c2a20; color: #d9eee0; padding: 8px;
                border: 0; border-right: 1px solid #304536;
                border-bottom: 1px solid #304536;
            }
            QPushButton#primaryButton {
                background: #168653; color: white; padding: 10px 18px;
                border: 1px solid #35a36d; border-radius: 7px; font-weight: 600;
            }
            QPushButton#primaryButton:hover { background: #1b9a61; }
            QPushButton#primaryButton:disabled { background: #26342b; color: #718078; }
            QStatusBar { background: #111a14; color: #9fb2a5; }
            """
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

