from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from spineworks import __version__
from spineworks.filters import insert_spine, remove_spine, run_addic, run_barnum
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
        self.saved_text: str | None = None
        self.field_edits_dirty = False
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

        self.save_action = QAction("Zapisz", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.save_file)
        toolbar.addAction(self.save_action)

        self.save_as_action = QAction("Zapisz jako…", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.setEnabled(False)
        self.save_as_action.triggered.connect(self.save_as_file)
        toolbar.addAction(self.save_as_action)

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

        self.propagate_button = QPushButton("Uzupełnij i popraw przypisania spine’ów")
        self.propagate_button.setObjectName("primaryButton")
        self.propagate_button.setEnabled(False)
        self.propagate_button.clicked.connect(self.propagate_assignments)
        layout.addWidget(self.propagate_button, alignment=Qt.AlignmentFlag.AlignLeft)

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

        self.barnum_button = QPushButton("barnum")
        self.barnum_button.setObjectName("primaryButton")
        self.barnum_button.setEnabled(False)
        self.barnum_button.clicked.connect(self.apply_barnum)
        filter_buttons.addWidget(self.barnum_button)

        self.empty_spine_button = QPushButton("Dodaj pusty spine")
        self.empty_spine_button.setObjectName("primaryButton")
        self.empty_spine_button.setEnabled(False)
        self.empty_spine_button.clicked.connect(self.add_empty_spine)
        filter_buttons.addWidget(self.empty_spine_button)

        self.kern_spine_button = QPushButton("Dodaj spine **kern")
        self.kern_spine_button.setObjectName("primaryButton")
        self.kern_spine_button.setEnabled(False)
        self.kern_spine_button.clicked.connect(self.add_kern_spine)
        filter_buttons.addWidget(self.kern_spine_button)

        self.remove_spine_button = QPushButton("Usuń spine")
        self.remove_spine_button.setObjectName("dangerButton")
        self.remove_spine_button.setEnabled(False)
        self.remove_spine_button.clicked.connect(self.remove_selected_spine)
        filter_buttons.addWidget(self.remove_spine_button)
        filter_buttons.addStretch(1)
        layout.addLayout(filter_buttons)

        self.setCentralWidget(central)
        version_label = QLabel(f"© 2026 Andrzej Borzym · SPINEWORKS {__version__}")
        version_label.setObjectName("versionLabel")
        self.statusBar().addPermanentWidget(version_label)
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
        if self.document is not None and not self._confirm_unsaved_changes():
            return
        try:
            document = HumdrumDocument.from_path(path)
        except (OSError, UnicodeError, HumdrumError) as error:
            QMessageBox.critical(self, "Nie można otworzyć pliku", str(error))
            return

        self.document = document
        self.current_path = path
        self.saved_text = document.to_text()
        self.undo_texts.clear()
        self.enabled_edit_rows.clear()
        self.undo_action.setEnabled(False)
        self.save_action.setEnabled(True)
        self.save_as_action.setEnabled(True)
        self.propagate_button.setEnabled(True)
        self.addic_button.setEnabled(True)
        self.ig_button.setEnabled(True)
        self.barnum_button.setEnabled(True)
        self.empty_spine_button.setEnabled(True)
        self.kern_spine_button.setEnabled(True)
        self.remove_spine_button.setEnabled(document.spine_count > 1)
        self.show_group_row = document.header.instrument_group_line is not None
        self._sync_ig_button()
        self.file_label.setText(path.name)
        self._refresh_table()
        self.statusBar().showMessage(f"Wczytano {document.spine_count} spine’ów")

    def save_file(self) -> bool:
        if self.document is None or self.current_path is None:
            return False
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return False
        try:
            self.current_path.write_text(self.document.to_text(), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, "Nie można zapisać pliku", str(error))
            return False
        self.saved_text = self.document.to_text()
        self._update_window_title()
        self.statusBar().showMessage(f"Zapisano {self.current_path.name}")
        return True

    def save_as_file(self) -> bool:
        if self.document is None or self.current_path is None:
            return False
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return False

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Zapisz plik Humdrum jako",
            str(self.current_path),
            "Pliki Humdrum (*.krn);;Wszystkie pliki (*)",
        )
        if not filename:
            return False

        path = Path(filename)
        if path.suffix.lower() != ".krn":
            path = path.with_name(path.name + ".krn")
        try:
            path.write_text(self.document.to_text(), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, "Nie można zapisać pliku", str(error))
            return False

        self.current_path = path
        self.saved_text = self.document.to_text()
        self.file_label.setText(path.name)
        self._update_window_title()
        self.statusBar().showMessage(f"Zapisano jako {path.name}")
        return True

    def _confirm_unsaved_changes(self) -> bool:
        if self.document is None:
            return True
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return False
        if self.document.to_text() == self.saved_text:
            return True

        box = QMessageBox(self)
        box.setWindowTitle("Niezapisane zmiany")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Dokument zawiera niezapisane zmiany.")
        box.setInformativeText("Czy zapisać je przed kontynuowaniem?")
        save_button = box.addButton("Zapisz", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Nie zapisuj", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()

        if box.clickedButton() is save_button:
            return self.save_file()
        return box.clickedButton() is discard_button

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._confirm_unsaved_changes():
            event.accept()
        else:
            event.ignore()

    def propagate_assignments(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        classes = self.document.instrument_classes()
        missing = [
            str(column + 1)
            for column, (spine_type, instrument_class) in enumerate(
                zip(self.document.spine_types, classes, strict=True)
            )
            if spine_type == "**kern"
            and (
                not instrument_class.startswith("*IC")
                or instrument_class == "*ICUNKNOWN"
            )
        ]
        if missing:
            QMessageBox.warning(
                self,
                "Niekompletne klasy instrumentów",
                "Najpierw uzupełnij kody instrumentów i uruchom addic.\n\n"
                "Brak poprawnej klasy *IC… w spine’ach: " + ", ".join(missing) + ".",
            )
            return

        before = self.document.to_text()
        try:
            changed = self.document.propagate_kern_assignments()
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można poprawić przypisań", str(error))
            return
        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage("Uzupełniono i poprawiono przypisania part i staff")
        else:
            self.statusBar().showMessage("Przypisania part i staff są już prawidłowe")

    def undo(self) -> None:
        if self.field_edits_dirty:
            self.field_edits_dirty = False
            self._refresh_table()
            self.statusBar().showMessage("Cofnięto edycję pola")
            return
        if not self.undo_texts:
            return
        self.document = HumdrumDocument.from_text(self.undo_texts.pop())
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self.undo_action.setEnabled(bool(self.undo_texts))
        self._refresh_table()
        self.statusBar().showMessage("Cofnięto ostatnią zmianę")

    def apply_instrument_codes(self, *, show_unchanged_status: bool = True) -> bool:
        if self.document is None:
            return False
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
            return False
        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage("Zastosowano dane instrumentów")
        elif show_unchanged_status:
            self.statusBar().showMessage("Dane instrumentów nie wymagają zmian")
        return True

    def _row_values(self, kind: str) -> list[str]:
        fields = self.row_inputs.get(kind, {})
        return [
            fields[column].text() if column in fields else ""
            for column in range(self.document.spine_count)
        ]

    def apply_addic(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return
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

    def apply_barnum(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return
        before = self.document.to_text()
        try:
            filtered = run_barnum(self.document)
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można uruchomić barnum", str(error))
            return
        if filtered.to_text() == before:
            self.statusBar().showMessage("Numery taktów są już prawidłowe")
            return
        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self._refresh_table()
        self.statusBar().showMessage("Ponownie ponumerowano takty")

    def remove_selected_spine(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Usuń spine")
        dialog.setMinimumWidth(520)
        form = QFormLayout(dialog)
        spine_combo = QComboBox(dialog)
        spine_combo.addItems(self._spine_descriptions())
        form.addRow("Spine do usunięcia:", spine_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Usuń")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        column = spine_combo.currentIndex()
        description = spine_combo.currentText()
        before = self.document.to_text()
        try:
            filtered = remove_spine(self.document, column=column)
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można usunąć spine’u", str(error))
            return
        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self.remove_spine_button.setEnabled(self.document.spine_count > 1)
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self._refresh_table()
        self.statusBar().showMessage(f"Usunięto spine: {description}")

    def add_empty_spine(self) -> None:
        self._add_spine(kern=False)

    def add_kern_spine(self) -> None:
        self._add_spine(kern=True)

    def _add_spine(self, *, kern: bool) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return
        choice = self._ask_spine_insertion(kern=kern)
        if choice is None:
            return
        reference_column, after, spine_type, hidden_rests = choice
        before = self.document.to_text()
        try:
            filtered = insert_spine(
                self.document,
                reference_column=reference_column,
                after=after,
                spine_type=spine_type,
                hidden_rests=hidden_rests,
            )
        except HumdrumError as error:
            QMessageBox.warning(self, "Nie można dodać spine’u", str(error))
            return
        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self._refresh_table()
        self.statusBar().showMessage(f"Dodano spine {spine_type}")

    def _ask_spine_insertion(
        self, *, kern: bool
    ) -> tuple[int, bool, str, bool] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Dodaj spine **kern" if kern else "Dodaj pusty spine")
        dialog.setMinimumWidth(520)
        form = QFormLayout(dialog)

        location_combo = QComboBox(dialog)
        location_combo.addItems(self._spine_descriptions())
        form.addRow("Spine odniesienia:", location_combo)

        position_widget = QWidget(dialog)
        position_layout = QHBoxLayout(position_widget)
        position_layout.setContentsMargins(0, 0, 0, 0)
        before_radio = QRadioButton("Przed", position_widget)
        after_radio = QRadioButton("Po", position_widget)
        before_radio.setChecked(True)
        position_group = QButtonGroup(dialog)
        position_group.addButton(before_radio)
        position_group.addButton(after_radio)
        position_layout.addWidget(before_radio)
        position_layout.addWidget(after_radio)
        position_layout.addStretch(1)
        form.addRow("Położenie:", position_widget)

        if kern:
            spine_type = "**kern"
            rests_widget = QWidget(dialog)
            rests_layout = QHBoxLayout(rests_widget)
            rests_layout.setContentsMargins(0, 0, 0, 0)
            visible_radio = QRadioButton("Z pauzami", rests_widget)
            hidden_radio = QRadioButton("Z ukrytymi pauzami", rests_widget)
            visible_radio.setChecked(True)
            rests_group = QButtonGroup(dialog)
            rests_group.addButton(visible_radio)
            rests_group.addButton(hidden_radio)
            rests_layout.addWidget(visible_radio)
            rests_layout.addWidget(hidden_radio)
            rests_layout.addStretch(1)
            form.addRow("Wypełnienie:", rests_widget)
        else:
            type_combo = QComboBox(dialog)
            type_combo.addItems(["**fba", "**fbb", "**dynam", "**text", "**fing"])
            form.addRow("Typ spine’u:", type_combo)
            spine_type = ""

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Dodaj")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if not kern:
            spine_type = type_combo.currentText()
        return (
            location_combo.currentIndex(),
            after_radio.isChecked(),
            spine_type,
            kern and hidden_radio.isChecked(),
        )

    def _spine_descriptions(self) -> list[str]:
        if self.document is None:
            return []
        count = self.document.spine_count
        names = ["*"] * count
        abbreviations = ["*"] * count
        codes = self.document.instrument_codes()
        if self.document.header.instrument_name_line is not None:
            names = self.document.fields(self.document.header.instrument_name_line)
        if self.document.header.instrument_abbr_line is not None:
            abbreviations = self.document.fields(self.document.header.instrument_abbr_line)

        descriptions = []
        nearest_instrument = ""
        for column, spine_type in enumerate(self.document.spine_types):
            if spine_type == "**kern":
                candidates = (
                    names[column].removeprefix('*I"'),
                    abbreviations[column].removeprefix("*I'"),
                    codes[column].removeprefix("*I"),
                )
                nearest_instrument = next(
                    (value for value in candidates if value and value != "*"),
                    "bez nazwy",
                )
            instrument = nearest_instrument or "brak instrumentu po lewej"
            descriptions.append(f"{column + 1} — {spine_type} — {instrument}")
        return descriptions

    def toggle_row_editing(self, row: int) -> None:
        kind = self.editable_row_indexes.get(row)
        if kind is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
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
        removing = self.show_group_row
        self.ig_button.setText("Usuń IG" if removing else "IG")
        self.ig_button.setObjectName("dangerButton" if removing else "primaryButton")
        self.ig_button.style().unpolish(self.ig_button)
        self.ig_button.style().polish(self.ig_button)

    def _refresh_table(self) -> None:
        if self.document is None:
            return
        self.field_edits_dirty = False
        self.undo_action.setEnabled(bool(self.undo_texts))
        self.remove_spine_button.setEnabled(self.document.spine_count > 1)
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
                    field.textChanged.connect(self._mark_field_edited)
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
        self._update_window_title()

    def _mark_field_edited(self) -> None:
        self.field_edits_dirty = True
        self.undo_action.setEnabled(True)
        self._update_window_title()

    def _update_window_title(self) -> None:
        if self.document is None:
            self.setWindowTitle("SPINEWORKS")
            return

        composer = ""
        title = ""
        for line in self.document.to_text().splitlines():
            if line.startswith("!!!COM:"):
                composer = line.partition(":")[2].strip().split(",", 1)[0].strip()
            elif line.startswith("!!!OTL:"):
                title = line.partition(":")[2].strip()

        if title:
            description = f"{composer}, {title}" if composer else title
        elif self.current_path is not None:
            description = self.current_path.name
        else:
            description = ""

        dirty = self.field_edits_dirty or (
            self.saved_text is not None and self.document.to_text() != self.saved_text
        )
        prefix = "* " if dirty else ""
        suffix = f" - {description}" if description else ""
        self.setWindowTitle(f"{prefix}SPINEWORKS{suffix}")

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
            for kind, row_fields in self.row_inputs.items():
                for column, field in row_fields.items():
                    if field is target:
                        table_row = next(
                            index
                            for index, row_kind in self.editable_row_indexes.items()
                            if row_kind == kind
                        )
                        self.table.scrollTo(
                            self.table.model().index(table_row, column),
                            QAbstractItemView.ScrollHint.EnsureVisible,
                        )
                        return True
            return True
        if watched in fields and event.type() == QEvent.Type.MouseButtonPress:
            QTimer.singleShot(0, watched.selectAll)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(".krn"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        previous_path = self.current_path
        self.load_path(Path(event.mimeData().urls()[0].toLocalFile()))
        if self.current_path != previous_path:
            event.acceptProposedAction()
        else:
            event.ignore()

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
            QPushButton#dangerButton {
                background: #7a3034; color: #fff1f1; padding: 10px 18px;
                border: 1px solid #ad5559; border-radius: 7px; font-weight: 600;
            }
            QPushButton#dangerButton:hover { background: #914047; }
            QPushButton#dangerButton:pressed { background: #64272b; }
            QWidget#instrumentEditorActive { background: #183d29; }
            QWidget#instrumentEditorKernInactive { background: transparent; }
            QLabel#fixedPrefix { background: transparent; color: #63d297; font-weight: 700; }
            QWidget#instrumentEditorKernInactive QLabel#fixedPrefix {
                color: #d8f8e4; font-weight: 400;
            }
            QLineEdit {
                background: transparent; color: #d8f8e4; border: 0;
                selection-background-color: #177245; padding: 3px 1px;
            }
            QLineEdit:disabled { color: #d8f8e4; }
            QStatusBar { background: #111a14; color: #9fb2a5; }
            QLabel#versionLabel {
                background: transparent; color: #718078;
                font-size: 11px; padding: 0 8px;
            }
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
