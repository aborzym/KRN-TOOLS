from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from spineworks.filters import run_addic
from spineworks.humdrum import HumdrumDocument, HumdrumError


class MainWindow(QMainWindow):
    ROW_NAMES = {
        "exclusive_line": "Typ spine’u",
        "part_line": "Part",
        "staff_line": "Staff",
        "instrument_name_line": "Nazwa pełna",
        "instrument_abbr_line": "Nazwa skrócona",
        "instrument_class_line": "Klasa instrumentu",
        "instrument_group_line": "Grupa instrumentu",
    }
    EDITABLE_ROWS = {
        "instrument_name_line": '*I"',
        "instrument_abbr_line": "*I'",
        "instrument_code_line": "*",
        "instrument_group_line": "*IG",
    }

    def __init__(self) -> None:
        super().__init__()
        self.document: HumdrumDocument | None = None
        self.current_path: Path | None = None
        self.undo_texts: list[str] = []
        self.row_inputs: dict[str, dict[int, QLineEdit]] = {}
        self.enabled_edit_rows: set[str] = set()
        self.editable_row_indexes: dict[int, str] = {}
        self.show_group_row = False
        self.setWindowTitle("SPINEWORKS")
        self.resize(1200, 650)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_theme()
        QTimer.singleShot(0, self._load_test_file)

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
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setSectionsClickable(True)
        self.table.verticalHeader().sectionClicked.connect(self.toggle_row_editing)
        layout.addWidget(self.table, 1)

        self.propagate_button = QPushButton("Uzupełnij przypisania spine’ów")
        self.propagate_button.setObjectName("primaryButton")
        self.propagate_button.setEnabled(False)
        self.propagate_button.clicked.connect(self.propagate_assignments)
        layout.addWidget(self.propagate_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.instrument_button = QPushButton("Zastosuj dane instrumentów")
        self.instrument_button.setObjectName("primaryButton")
        self.instrument_button.setEnabled(False)
        self.instrument_button.clicked.connect(self.apply_instrument_codes)
        layout.addWidget(self.instrument_button, alignment=Qt.AlignmentFlag.AlignLeft)

        filter_buttons = QHBoxLayout()
        filter_buttons.setSpacing(8)

        self.addic_button = QPushButton("addic")
        self.addic_button.setObjectName("primaryButton")
        self.addic_button.setEnabled(False)
        self.addic_button.clicked.connect(self.apply_addic)
        filter_buttons.addWidget(self.addic_button)

        self.ig_button = QPushButton("IG")
        self.ig_button.setObjectName("primaryButton")
        self.ig_button.setEnabled(False)
        self.ig_button.clicked.connect(self.toggle_instrument_group_row)
        filter_buttons.addWidget(self.ig_button)
        filter_buttons.addStretch(1)
        layout.addLayout(filter_buttons)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Gotowe")

    def _load_test_file(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        test_path = project_root / "data.krn"
        if test_path.is_file():
            self.load_path(test_path)

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
        self.enabled_edit_rows.clear()
        self.undo_action.setEnabled(False)
        self.propagate_button.setEnabled(True)
        self.instrument_button.setEnabled(True)
        self.addic_button.setEnabled(True)
        self.ig_button.setEnabled(True)
        self.show_group_row = document.header.instrument_group_line is not None
        self._sync_ig_button()
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
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self.undo_action.setEnabled(bool(self.undo_texts))
        self._refresh_table()
        self.statusBar().showMessage("Cofnięto ostatnią zmianę")

    def apply_instrument_codes(self) -> None:
        if self.document is None:
            return
        before = self.document.to_text()
        try:
            changed = False
            if "instrument_name_line" in self.enabled_edit_rows:
                changed |= self.document.set_instrument_names(
                    self._row_values("instrument_name_line")
                )
            if "instrument_abbr_line" in self.enabled_edit_rows:
                changed |= self.document.set_instrument_abbreviations(
                    self._row_values("instrument_abbr_line")
                )
            if "instrument_code_line" in self.enabled_edit_rows:
                codes = [f"*{value}" if value else "*" for value in self._row_values("instrument_code_line")]
                changed |= self.document.set_instrument_codes(codes)
            if "instrument_group_line" in self.enabled_edit_rows:
                changed |= self.document.set_instrument_groups(
                    self._row_values("instrument_group_line")
                )
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można zastosować danych", str(error))
            return
        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage("Zastosowano dane instrumentów")
        else:
            self.statusBar().showMessage("Dane instrumentów nie wymagają zmian")

    def _row_values(self, kind: str) -> list[str]:
        fields = self.row_inputs.get(kind, {})
        return [
            fields[column].text() if column in fields else ""
            for column in range(self.document.spine_count)
        ]

    def apply_addic(self) -> None:
        if self.document is None:
            return
        self.apply_instrument_codes()
        missing = [
            str(column + 1)
            for column, (spine_type, code) in enumerate(
                zip(self.document.spine_types, self.document.instrument_codes(), strict=True)
            )
            if spine_type == "**kern" and code == "*"
        ]
        if missing:
            box = QMessageBox(self)
            box.setWindowTitle("Brak kodów instrumentów")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(
                "Brak kodów instrumentów w spine’ach: " + ", ".join(missing) + "."
            )
            box.setInformativeText("Czy mimo to uruchomić filtr addic?")
            proceed = box.addButton("Kontynuuj", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Wróć do edycji", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not proceed:
                return
        before = self.document.to_text()
        try:
            self.document = run_addic(self.document)
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można uruchomić addic", str(error))
            return
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self._refresh_table()
        self.statusBar().showMessage("Filtr addic utworzył klasy instrumentów")

    def toggle_row_editing(self, row: int) -> None:
        kind = self.editable_row_indexes.get(row)
        if kind is None:
            return
        if kind in self.enabled_edit_rows:
            self.enabled_edit_rows.remove(kind)
        else:
            self.enabled_edit_rows.add(kind)
        self._refresh_table()
        self.table.clearSelection()
        if kind in self.enabled_edit_rows:
            first_field = next(iter(self.row_inputs[kind].values()))
            first_field.setFocus()
            first_field.selectAll()

    def toggle_instrument_group_row(self) -> None:
        if self.show_group_row:
            if self.document.header.instrument_group_line is not None:
                before = self.document.to_text()
                self.document.remove_instrument_groups()
                self.undo_texts.append(before)
                self.undo_action.setEnabled(True)
            self.show_group_row = False
            self.enabled_edit_rows.discard("instrument_group_line")
            self._sync_ig_button()
            self._refresh_table()
            self.statusBar().showMessage("Usunięto wiersz grupy instrumentów")
            return
        self.show_group_row = True
        self.enabled_edit_rows.add("instrument_group_line")
        self._sync_ig_button()
        self._refresh_table()
        first_field = next(iter(self.row_inputs["instrument_group_line"].values()))
        first_field.setFocus()
        first_field.selectAll()

    def _sync_ig_button(self) -> None:
        self.ig_button.setText("Usuń IG" if self.show_group_row else "IG")

    def _refresh_table(self) -> None:
        if self.document is None:
            return
        rows: list[tuple[str, int, str | None, str | None]] = []
        for attribute, label in self.ROW_NAMES.items():
            line_number = getattr(self.document.header, attribute)
            if line_number is not None:
                prefix = self.EDITABLE_ROWS.get(attribute)
                rows.append((label, line_number, attribute if prefix else None, prefix))

        if self.show_group_row and self.document.header.instrument_group_line is None:
            rows.append(("Grupa instrumentu", -2, "instrument_group_line", "*IG"))

        if self.document.header.instrument_code_line is None:
            rows.append(("Kod instrumentu", -1, "instrument_code_line", "*"))
        else:
            rows.append(
                (
                    "Kod instrumentu",
                    self.document.header.instrument_code_line,
                    "instrument_code_line",
                    "*",
                )
            )
        def row_order(row):
            label, line_number, _, _ = row
            if label == "Grupa instrumentu" and line_number == -2:
                class_line = self.document.header.instrument_class_line
                return (class_line + 0.5) if class_line is not None else float("inf") - 1
            return line_number if line_number >= 0 else float("inf")

        rows.sort(key=row_order)

        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(self.document.spine_count)
        for column, spine_type in enumerate(self.document.spine_types):
            header_item = QTableWidgetItem(str(column + 1))
            header_item.setToolTip(spine_type)
            header_item.setForeground(QColor("#eef7f1"))
            if spine_type == "**kern":
                font = header_item.font()
                font.setBold(True)
                header_item.setFont(font)
                header_item.setBackground(QColor("#294234"))
            self.table.setHorizontalHeaderItem(column, header_item)
        self.editable_row_indexes.clear()
        labels = []
        for row, (label, _, kind, _) in enumerate(rows):
            if kind:
                self.editable_row_indexes[row] = kind
                labels.append(f"{'☑' if kind in self.enabled_edit_rows else '☐'} {label}")
            else:
                labels.append(label)
        for row, label in enumerate(labels):
            header_item = QTableWidgetItem(label)
            self.table.setVerticalHeaderItem(row, header_item)
        self.row_inputs.clear()
        for row, (label, line_number, kind, fixed_prefix) in enumerate(rows):
            if label == "Klasa instrumentu":
                values = self.document.instrument_classes()
            elif label == "Grupa instrumentu":
                values = self.document.instrument_groups()
            elif line_number == -1:
                values = self.document.instrument_codes()
            else:
                values = self.document.fields(line_number)
            for column, value in enumerate(values):
                if kind and self.document.spine_types[column] == "**kern":
                    editor = QWidget()
                    editor.setObjectName(
                        "instrumentEditorActive"
                        if kind in self.enabled_edit_rows
                        else "instrumentEditorKernInactive"
                    )
                    editor_layout = QHBoxLayout(editor)
                    editor_layout.setContentsMargins(7, 2, 5, 2)
                    editor_layout.setSpacing(1)
                    prefix = QLabel(fixed_prefix)
                    prefix.setObjectName("fixedPrefix")
                    field = QLineEdit("" if value == "*" else value.removeprefix(fixed_prefix))
                    field.setFrame(False)
                    field.installEventFilter(self)
                    field.setEnabled(kind in self.enabled_edit_rows)
                    editor_layout.addWidget(prefix)
                    editor_layout.addWidget(field, 1)
                    self.row_inputs.setdefault(kind, {})[column] = field
                    self.table.setCellWidget(row, column, editor)
                    continue
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if self.document.spine_types[column] == "**kern":
                    item.setBackground(QColor("#18271e"))
                self.table.setItem(row, column, item)
        for fields in self.row_inputs.values():
            editable_fields = list(fields.values())
            for current, following in zip(editable_fields, editable_fields[1:], strict=False):
                QWidget.setTabOrder(current, following)
        self.table.resizeRowsToContents()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        fields = next(
            (list(row.values()) for row in self.row_inputs.values() if watched in row.values()),
            [],
        )
        if (
            watched in fields
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
        ):
            current = fields.index(watched)
            step = -1 if event.key() == Qt.Key.Key_Backtab else 1
            target = fields[(current + step) % len(fields)]
            target.setFocus()
            target.selectAll()
            return True
        if watched in fields and event.type() == QEvent.Type.MouseButtonPress:
            QTimer.singleShot(0, watched.selectAll)
        return super().eventFilter(watched, event)

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
            QWidget#instrumentEditorActive { background: #183d29; }
            QWidget#instrumentEditorKernInactive { background: #18271e; }
            QLabel#fixedPrefix { background: transparent; color: #63d297; font-weight: 700; }
            QLineEdit {
                background: transparent; color: #d8f8e4; border: 0;
                selection-background-color: #177245; padding: 3px 1px;
            }
            QLineEdit:disabled { color: #d8f8e4; }
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
