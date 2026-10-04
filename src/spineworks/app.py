import json
import os
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from spineworks import __version__
from spineworks.chrome_preview import ChromePreview
from spineworks.filters import (
    HumdrumToolError,
    compact_records,
    insert_spine,
    remove_spine,
    remove_system_breaks,
    run_addic,
    run_barnum,
)
from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_editor import SpineEditor
from spineworks.theme import SPINEWORKS_STYLE
from spineworks.updater import UpdateManager

FORMSPREE_REPORT_URL = "https://formspree.io/f/meaopdyj"
GITHUB_ISSUE_URL = "https://github.com/aborzym/KRN-TOOLS/issues/new"


class MainWindow(QMainWindow):
    ROW_NAMES: ClassVar[dict[str, str]] = {
        "exclusive_line": "Typ spine’u",
        "part_line": "Part",
        "staff_line": "Staff",
        "instrument_name_line": "Nazwa pełna",
        "instrument_abbr_line": "Nazwa skrócona",
        "instrument_class_line": "Klasa instrumentu",
        "instrument_group_line": "Grupa instrumentu",
    }
    EDITABLE_ROWS: ClassVar[dict[str, str]] = {
        "instrument_name_line": '*I"',
        "instrument_abbr_line": "*I'",
        "instrument_class_line": "*IC",
        "instrument_code_line": "*",
        "instrument_group_line": "*IG",
    }

    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings()
        self.report_network_manager = QNetworkAccessManager(self)
        self.update_manager = UpdateManager(
            self,
            settings=self.settings,
            current_version=__version__,
        )
        self.environment_humdrum_paths = [
            path for path in os.environ.get("SPINEWORKS_HUMDRUM_PATH", "").split(os.pathsep) if path
        ]
        self.humdrum_tool_paths: list[str] = []
        self._load_humdrum_tool_paths()
        self.document: HumdrumDocument | None = None
        self.current_path: Path | None = None
        self.chrome_previews: dict[Path, ChromePreview] = {}
        self.saved_text: str | None = None
        self.saved_text: str | None = None
        self.field_edits_dirty = False
        self.undo_texts: list[str] = []
        self.row_inputs: dict[str, dict[int, QLineEdit]] = {}
        self.enabled_edit_rows: set[str] = set()
        self.editable_row_indexes: dict[int, str] = {}
        self.show_group_row = False
        self._coloring_start_measure = 1
        self._coloring_end_measure = 1
        self._coloring_start_spine = 0
        self._coloring_end_spine = 0
        self._coloring_color = "dodgerblue"
        self.setWindowTitle("SPINEWORKS")
        self.resize(1200, 650)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_theme()
        QTimer.singleShot(0, self._load_test_file)
        QTimer.singleShot(
            1500,
            self.update_manager.check_for_updates,
        )

    def _load_humdrum_tool_paths(self) -> None:
        stored_paths = self.settings.value("humdrum/tool_paths", [])
        if isinstance(stored_paths, str):
            stored_paths = [stored_paths]

        self.humdrum_tool_paths = [str(path) for path in stored_paths if str(path).strip()]
        self._apply_humdrum_tool_paths()

    def _apply_humdrum_tool_paths(self) -> None:
        paths = dict.fromkeys([*self.humdrum_tool_paths, *self.environment_humdrum_paths])
        if paths:
            os.environ["SPINEWORKS_HUMDRUM_PATH"] = os.pathsep.join(paths)
        else:
            os.environ.pop("SPINEWORKS_HUMDRUM_PATH", None)

    def configure_humdrum_tool_paths(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Narzędzia Humdrum")
        dialog.resize(620, 360)

        layout = QVBoxLayout(dialog)
        description = QLabel(
            "Podaj katalogi zawierające programy Humdrum — po jednym w każdym wierszu.\n"
            "Standardowe lokalizacje są przeszukiwane automatycznie."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        paths_editor = QPlainTextEdit(dialog)
        paths_editor.setPlainText("\n".join(self.humdrum_tool_paths))
        paths_editor.setPlaceholderText("/usr/local/humlib/bin\n/usr/local/humdrum/bin")
        layout.addWidget(paths_editor, 1)

        add_directory_button = QPushButton("Dodaj katalog…", dialog)

        def add_directory() -> None:
            directory = QFileDialog.getExistingDirectory(
                dialog,
                "Wybierz katalog z narzędziami Humdrum",
            )
            if not directory:
                return

            paths = [
                line.strip() for line in paths_editor.toPlainText().splitlines() if line.strip()
            ]
            if directory not in paths:
                paths.append(directory)
                paths_editor.setPlainText("\n".join(paths))

        add_directory_button.clicked.connect(add_directory)
        layout.addWidget(add_directory_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.humdrum_tool_paths = list(
            dict.fromkeys(
                line.strip() for line in paths_editor.toPlainText().splitlines() if line.strip()
            )
        )
        self.settings.setValue("humdrum/tool_paths", self.humdrum_tool_paths)
        self.settings.sync()
        self._apply_humdrum_tool_paths()
        self.statusBar().showMessage("Zapisano katalogi narzędzi Humdrum")

    def _build_ui(self) -> None:
        toolbar = QToolBar("Plik", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("Otwórz", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_file)
        self.addAction(open_action)

        self.recent_files_menu = QMenu(self)
        self.recent_files_menu.aboutToShow.connect(self._populate_recent_files_menu)

        self.recent_files_button = QToolButton(self)
        self.recent_files_button.setDefaultAction(open_action)
        self.recent_files_button.setMenu(self.recent_files_menu)
        self.recent_files_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.recent_files_button.setToolTip("Otwórz plik · strzałka: ostatnio otwierane pliki")
        self.recent_files_button.setStyleSheet(
            """
            QToolButton {
                padding-right: 18px;
            }
            QToolButton::menu-button {
                width: 16px;
                border: 0;
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
                background: transparent;
            }
            QToolButton::menu-button:hover {
                background: #294333;
            }
            """
        )
        toolbar.addWidget(self.recent_files_button)

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

        toolbar.addSeparator()

        humdrum_tools_action = QAction("Narzędzia Humdrum…", self)
        humdrum_tools_action.triggered.connect(self.configure_humdrum_tool_paths)
        toolbar.addAction(humdrum_tools_action)

        update_action = QAction("Sprawdź aktualizacje…", self)
        update_action.triggered.connect(
            lambda: self.update_manager.check_for_updates(
                show_current_message=True,
            )
        )
        toolbar.addAction(update_action)

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
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        row_labels = [*self.ROW_NAMES.values(), "Kod instrumentu"]
        row_header_width = (
            max(self.table.fontMetrics().horizontalAdvance(label) for label in row_labels) + 32
        )
        self.table.verticalHeader().setFixedWidth(row_header_width)
        self.table.verticalHeader().setSectionsClickable(True)
        self.table.verticalHeader().sectionClicked.connect(self.toggle_row_editing)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        decoration_row = QWidget(self)
        decoration_row.setObjectName("decorationRow")
        decoration_layout = QHBoxLayout(decoration_row)
        decoration_layout.setContentsMargins(0, 0, 0, 0)
        decoration_layout.setSpacing(10)
        decoration_label = QLabel("System decoration:", decoration_row)
        decoration_label.setObjectName("decorationLabel")
        self.system_decoration_input = QLineEdit(decoration_row)
        self.system_decoration_input.setObjectName("systemDecorationInput")
        self.system_decoration_input.setFixedWidth(420)
        self.system_decoration_input.setEnabled(False)
        self.system_decoration_input.textChanged.connect(self._mark_field_edited)
        decoration_layout.addWidget(decoration_label)
        decoration_layout.addWidget(self.system_decoration_input)
        decoration_layout.addStretch(1)
        layout.addWidget(decoration_row)

        operations = QGridLayout()
        operations.setHorizontalSpacing(8)
        operations.setVerticalSpacing(8)
        for column in range(5):
            operations.setColumnStretch(column, 1)

        self.addic_button = QPushButton("Generuj kody IC")
        self.addic_button.setObjectName("primaryButton")
        self.addic_button.setEnabled(False)
        self.addic_button.clicked.connect(self.apply_addic)

        self.ig_button = QPushButton("Dodaj linię IG")
        self.ig_button.setObjectName("primaryButton")
        self.ig_button.setEnabled(False)
        self.ig_button.clicked.connect(self.toggle_instrument_group_row)

        self.barnum_button = QPushButton("Ponumeruj takty")
        self.barnum_button.setObjectName("primaryButton")
        self.barnum_button.setEnabled(False)
        self.barnum_button.clicked.connect(self.apply_barnum)

        self.empty_spine_button = QPushButton("Dodaj spine")
        self.empty_spine_button.setObjectName("primaryButton")
        self.empty_spine_button.setEnabled(False)
        self.empty_spine_button.clicked.connect(self.add_empty_spine)

        self.kern_spine_button = QPushButton("Dodaj spine **kern")
        self.kern_spine_button.setObjectName("primaryButton")
        self.kern_spine_button.setEnabled(False)
        self.kern_spine_button.clicked.connect(self.add_kern_spine)

        self.segment_button = QPushButton("Segment")
        self.segment_button.setObjectName("primaryButton")
        self.segment_button.setEnabled(False)
        self.segment_button.clicked.connect(self.apply_segment)

        self.italics_button = QPushButton("Oznacz kursywę")
        self.italics_button.setObjectName("primaryButton")
        self.italics_button.setEnabled(False)
        self.italics_button.clicked.connect(self.apply_text_italics)

        self.custos_button = QPushButton("Popraw custosy")
        self.custos_button.setObjectName("primaryButton")
        self.custos_button.setEnabled(False)
        self.custos_button.clicked.connect(self.apply_custos)

        self.hide_range_button = QPushButton("Ukryj zakres")
        self.hide_range_button.setObjectName("primaryButton")
        self.hide_range_button.setEnabled(False)
        self.hide_range_button.clicked.connect(self.apply_hidden_measure_range)

        self.right_align_dynamics_button = QPushButton("Dynamika do prawej")
        self.right_align_dynamics_button.setObjectName("primaryButton")
        self.right_align_dynamics_button.setEnabled(False)
        self.right_align_dynamics_button.clicked.connect(self.apply_right_align_dynamics)

        self.color_elements_button = QPushButton("Koloruj elementy")
        self.color_elements_button.setObjectName("primaryButton")
        self.color_elements_button.setEnabled(False)
        self.color_elements_button.clicked.connect(self.apply_element_coloring)

        self.compact_records_button = QPushButton("Kompaktuj rekordy")
        self.compact_records_button.setObjectName("primaryButton")
        self.compact_records_button.setEnabled(False)
        self.compact_records_button.setToolTip(
            "Porządkuje komentarze lokalne i interpretacje oraz usuwa puste rekordy."
        )
        self.compact_records_button.clicked.connect(self.apply_record_compaction)

        self.breaks_button = QPushButton("Usuń łamania")
        self.breaks_button.setObjectName("dangerButton")
        self.breaks_button.setEnabled(False)
        self.breaks_button.clicked.connect(self.remove_system_break_records)

        self.remove_spine_button = QPushButton("Usuń spine")
        self.remove_spine_button.setObjectName("dangerButton")
        self.remove_spine_button.setEnabled(False)
        self.remove_spine_button.clicked.connect(self.remove_selected_spine)

        primary_operations = [
            self.addic_button,
            self.ig_button,
            self.barnum_button,
            self.kern_spine_button,
            self.empty_spine_button,
        ]
        for column, button in enumerate(primary_operations):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            operations.addWidget(button, 0, column)

        self.segment_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        operations.addWidget(self.segment_button, 1, 0)

        self.italics_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        operations.addWidget(self.italics_button, 1, 1)

        self.custos_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        operations.addWidget(self.custos_button, 1, 2)

        self.hide_range_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        operations.addWidget(self.hide_range_button, 1, 3)

        self.right_align_dynamics_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        operations.addWidget(self.right_align_dynamics_button, 1, 4)

        for column, button in enumerate((self.breaks_button, self.remove_spine_button)):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            operations.addWidget(button, 2, column)

        self.color_elements_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        operations.addWidget(self.color_elements_button, 2, 2)

        self.compact_records_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        operations.addWidget(self.compact_records_button, 2, 3)

        self.spine_editor_button = QPushButton("Napraw rozdwojenia")
        self.spine_editor_button.setObjectName("primaryButton")
        self.spine_editor_button.setEnabled(False)
        self.spine_editor_button.setToolTip("Otwórz edytor rozdwojeń i scaleń spinów.")
        self.spine_editor_button.clicked.connect(self.open_spine_editor)
        self.spine_editor_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        operations.addWidget(self.spine_editor_button, 2, 4)

        self.propagate_button = QPushButton("Uzupełnij i popraw przypisania spine’ów")
        self.propagate_button.setObjectName("primaryButton")
        self.propagate_button.setEnabled(False)
        self.propagate_button.clicked.connect(self.propagate_assignments)
        self.propagate_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        operations.addWidget(self.propagate_button, 3, 0, 1, 5)
        layout.addLayout(operations)

        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(0, 8, 0, 0)
        preview_row.addStretch()

        self.chrome_button = QPushButton("Otwórz w Chrome", self)
        self.chrome_button.setObjectName("chromeButton")
        self.chrome_button.clicked.connect(self.open_in_chrome)
        self.chrome_button.setToolTip("Otwórz zapisany plik w VHV.")
        self.chrome_button.setStyleSheet(
            """
            QPushButton#chromeButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #4189d4,
                    stop: 0.45 #245fa8,
                    stop: 1 #19477e
                );
                color: white;
                border: 1px solid #356fae;
                border-top: 1px solid #80b7ed;
                border-bottom: 3px solid #102f56;
                border-radius: 8px;
                padding: 8px 18px;
                font-weight: 600;
            }
            QPushButton#chromeButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #529ce8,
                    stop: 0.45 #2e73c4,
                    stop: 1 #20558f
                );
            }
            QPushButton#chromeButton:pressed {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #19477e,
                    stop: 1 #245fa8
                );
                border-top: 2px solid #102f56;
                border-bottom: 1px solid #356fae;
                padding-top: 9px;
                padding-bottom: 8px;
            }
            """
        )
        preview_row.addWidget(self.chrome_button)
        layout.addLayout(preview_row)

        self.setCentralWidget(central)
        version_label = QLabel(f"© 2026 Andrzej Borzym · SPINEWORKS {__version__}")
        version_label.setObjectName("versionLabel")
        self.statusBar().addPermanentWidget(version_label)
        self.statusBar().showMessage("Gotowe")

    def open_in_chrome(self) -> None:
        if self.document is None or self.current_path is None:
            self.statusBar().showMessage("Najpierw otwórz plik .krn")
            return

        if not self._confirm_unsaved_changes():
            return

        path = self.current_path.expanduser().resolve()
        preview = self.chrome_previews.get(path)
        created = preview is None

        try:
            if preview is None:
                preview = ChromePreview(path)
                self.chrome_previews[path] = preview
            preview.open()
        except (OSError, subprocess.TimeoutExpired) as error:
            if created and preview is not None:
                preview.close()
                self.chrome_previews.pop(path, None)
            QMessageBox.warning(
                self,
                "Nie można otworzyć Chrome",
                str(error),
            )
            return

        self.statusBar().showMessage("Otwarto zapisany plik w VHV w Chrome.")

    def _load_test_file(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        test_path = project_root / "data.krn"
        if test_path.is_file():
            self.load_path(test_path)

    def _remember_recent_file(self, path: Path) -> None:
        filename = str(path.expanduser().resolve())
        recent = self.settings.value("files/recent", [], type=list)
        recent = [filename, *(entry for entry in recent if entry != filename)]
        self.settings.setValue("files/recent", recent[:10])

    def _populate_recent_files_menu(self) -> None:
        self.recent_files_menu.clear()
        recent = self.settings.value("files/recent", [], type=list)

        if not recent:
            action = self.recent_files_menu.addAction("Brak ostatnio otwieranych plików")
            action.setEnabled(False)
            return

        for filename in recent[:10]:
            path = Path(filename)
            label = f"{path.name} — {path.parent}"
            action = self.recent_files_menu.addAction(label.replace("&", "&&"))
            action.setToolTip(str(path))
            action.triggered.connect(lambda checked=False, selected=path: self.load_path(selected))

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
        self.system_decoration_input.setEnabled(True)
        self.propagate_button.setEnabled(True)
        self.addic_button.setEnabled(True)
        self.ig_button.setEnabled(True)
        self.barnum_button.setEnabled(True)
        self.breaks_button.setEnabled(True)
        self.empty_spine_button.setEnabled(True)
        self.kern_spine_button.setEnabled(True)
        self.segment_button.setEnabled(True)
        self.italics_button.setEnabled(True)
        self.custos_button.setEnabled(True)
        self.hide_range_button.setEnabled(
            any(spine_type == "**kern" for spine_type in document.spine_types)
        )
        self.right_align_dynamics_button.setEnabled(
            any(spine_type == "**kern" for spine_type in document.spine_types)
            and any(spine_type == "**dynam" for spine_type in document.spine_types)
        )
        self.color_elements_button.setEnabled(
            any(spine_type == "**kern" for spine_type in document.spine_types)
        )
        self.compact_records_button.setEnabled(True)
        self.spine_editor_button.setEnabled(True)
        self.remove_spine_button.setEnabled(document.spine_count > 1)
        self.show_group_row = document.header.instrument_group_line is not None
        self._sync_ig_button()
        self.file_label.setText(path.name)
        self._refresh_table()
        self.table.verticalHeader().setVisible(True)
        self._remember_recent_file(path)
        self.statusBar().showMessage(f"Wczytano {document.spine_count} spine’ów")

    def open_spine_editor(self) -> None:
        if self.document is None or self.current_path is None:
            return

        self.spine_editor_button.setFocus()

        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        if self.document.to_text() != self.saved_text:
            answer = QMessageBox.question(
                self,
                "Zapis przed otwarciem edytora",
                "Przed otwarciem edytora rozdwojeń trzeba zapisać "
                "bieżące zmiany, aby numery linii odpowiadały plikowi.\n\n"
                "Zapisać i otworzyć edytor?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer != QMessageBox.StandardButton.Save:
                return
            if not self.save_file():
                return

        path = self.current_path

        try:
            document = HumdrumDocument.from_path(path)
            before = document.to_text()
            editor = SpineEditor(document, self, file_path=path)
            editor.exec()
            after = HumdrumDocument.from_path(path).to_text()
        except (OSError, UnicodeError, HumdrumError) as error:
            QMessageBox.critical(
                self,
                "Edytor rozdwojeń",
                str(error),
            )
            return

        if after != before or after != self.saved_text:
            self.load_path(path)

    def save_file(self) -> bool:
        if self.document is None or self.current_path is None:
            return False
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return False
        try:
            document = HumdrumDocument.from_text(self.document.to_text())
            document.sort_header_rows()
            text = document.to_text()
            self.current_path.write_text(text, encoding="utf-8")
        except (OSError, HumdrumError) as error:
            QMessageBox.critical(self, "Nie można zapisać pliku", str(error))
            return False

        self.document = document
        self.saved_text = text
        self._refresh_table()
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
            document = HumdrumDocument.from_text(self.document.to_text())
            document.sort_header_rows()
            text = document.to_text()
            path.write_text(text, encoding="utf-8")
        except (OSError, HumdrumError) as error:
            QMessageBox.critical(self, "Nie można zapisać pliku", str(error))
            return False

        self.document = document
        self.current_path = path
        self.saved_text = text
        self.file_label.setText(path.name)
        self._refresh_table()
        self._update_window_title()
        self._remember_recent_file(path)
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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_unsaved_changes():
            for preview in self.chrome_previews.values():
                preview.close()
            self.chrome_previews.clear()
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
            and (not instrument_class.startswith("*IC") or instrument_class == "*ICUNKNOWN")
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

    def apply_segment(self) -> None:
        if self.document is None or self.current_path is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        before = self.document.to_text()
        changed = self.document.set_segment(self.current_path.name)
        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage("Uzupełniono rekord !!!!SEGMENT:")
        else:
            self.statusBar().showMessage("Rekord !!!!SEGMENT: jest już prawidłowy")

    def _show_copyable_error(self, title: str, message: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)

        layout = QVBoxLayout(dialog)
        description = QLabel(
            "Dokument zawiera błędy wymagające ręcznej korekty:",
            dialog,
        )
        layout.addWidget(description)

        text_box = QPlainTextEdit(dialog)
        text_box.setPlainText(message)
        text_box.setReadOnly(True)
        text_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(text_box)

        buttons = QDialogButtonBox(dialog)
        copy_button = buttons.addButton("Kopiuj", QDialogButtonBox.ButtonRole.ActionRole)
        ok_button = buttons.addButton("OK", QDialogButtonBox.ButtonRole.AcceptRole)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(message))
        ok_button.clicked.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.resize(760, 320)
        dialog.exec()

    def _show_filter_error(self, title: str, error: HumdrumError) -> None:
        if isinstance(error, HumdrumToolError):
            self._show_tool_error(title, error)
            return

        QMessageBox.warning(self, title, str(error))

    def _show_tool_error(self, title: str, error: HumdrumToolError) -> None:
        report = error.diagnostic_report

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(820, 480)

        layout = QVBoxLayout(dialog)

        description = QLabel(str(error), dialog)
        description.setWordWrap(True)
        layout.addWidget(description)

        privacy_note = QLabel(
            "Raport nie zawiera treści dokumentu .krn. Przed wysłaniem możesz "
            "przejrzeć całą jego zawartość.",
            dialog,
        )
        privacy_note.setWordWrap(True)
        layout.addWidget(privacy_note)

        report_box = QPlainTextEdit(dialog)
        report_box.setPlainText(report)
        report_box.setReadOnly(True)
        report_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(report_box, 1)

        buttons = QDialogButtonBox(dialog)
        send_button = buttons.addButton(
            "Wyślij raport",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        github_button = buttons.addButton(
            "Zgłoś na GitHubie",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        copy_button = buttons.addButton(
            "Kopiuj raport",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        ok_button = buttons.addButton(
            "OK",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )

        send_button.clicked.connect(lambda: self._send_diagnostic_report(report, dialog))
        github_button.clicked.connect(lambda: self._open_github_issue(report))
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(report))
        ok_button.clicked.connect(dialog.accept)

        layout.addWidget(buttons)
        dialog.exec()

    def _send_diagnostic_report(self, report: str, parent: QWidget) -> None:
        confirmation = QMessageBox.question(
            parent,
            "Wysłać raport?",
            "Raport zostanie przesłany do autora SPINEWORKS przez usługę Formspree. "
            "Nie zawiera treści dokumentu .krn.\n\nCzy wysłać raport?",
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        payload = json.dumps(
            {
                "_subject": f"SPINEWORKS {__version__} — raport błędu",
                "message": report,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = QNetworkRequest(QUrl(FORMSPREE_REPORT_URL))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/json",
        )
        request.setRawHeader(b"Accept", b"application/json")

        reply = self.report_network_manager.post(request, payload)
        self.statusBar().showMessage("Wysyłanie raportu błędu…")
        reply.finished.connect(lambda: self._finish_diagnostic_report_submission(reply, parent))

    def _finish_diagnostic_report_submission(
        self,
        reply: QNetworkReply,
        parent: QWidget,
    ) -> None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        response = bytes(reply.readAll()).decode("utf-8", errors="replace")

        if (
            reply.error() == QNetworkReply.NetworkError.NoError
            and status is not None
            and 200 <= int(status) < 300
        ):
            self.statusBar().showMessage("Wysłano raport błędu")
            QMessageBox.information(
                parent,
                "Raport wysłany",
                "Raport został wysłany. Dziękuję za zgłoszenie.",
            )
        else:
            self.statusBar().showMessage("Nie udało się wysłać raportu")
            QMessageBox.warning(
                parent,
                "Nie udało się wysłać raportu",
                "Formspree nie przyjęło raportu.\n\n"
                f"Kod HTTP: {status or 'brak'}\n"
                f"{response or reply.errorString()}\n\n"
                "Możesz skopiować raport albo zgłosić problem na GitHubie.",
            )

        reply.deleteLater()

    def _open_github_issue(self, report: str) -> None:
        query = QUrlQuery()
        query.addQueryItem(
            "title",
            f"Raport błędu SPINEWORKS {__version__}",
        )
        query.addQueryItem(
            "body",
            f"## Raport diagnostyczny\n\n```text\n{report}\n```\n",
        )

        url = QUrl(GITHUB_ISSUE_URL)
        url.setQuery(query)
        if not QDesktopServices.openUrl(url):
            QApplication.clipboard().setText(report)
            QMessageBox.warning(
                self,
                "Nie można otworzyć przeglądarki",
                "Nie udało się otworzyć GitHuba. Raport został skopiowany do schowka.",
            )

    def apply_text_italics(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        before = self.document.to_text()
        try:
            changed, warnings = self.document.mark_text_italics()
        except HumdrumError as error:
            self._show_copyable_error(
                "Nie można oznaczyć kursywy",
                str(error),
            )
            return

        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            if warnings:
                self.statusBar().showMessage(
                    "Oznaczono poprawne fragmenty kursywy; część wymaga kontroli"
                )
            else:
                self.statusBar().showMessage("Oznaczono kursywę w tekście")
        elif warnings:
            self.statusBar().showMessage("Nie oznaczono kursywy — znaleziono błędne znaczniki")
        else:
            self.statusBar().showMessage("Nie znaleziono znaczników kursywy w tekście")

        if warnings:
            self._show_copyable_error(
                "Kursywa przetworzona z ostrzeżeniami",
                "\n".join(warnings),
            )

    def _ask_hidden_measure_range(
        self,
    ) -> tuple[int, int, set[int], bool] | None:
        if self.document is None:
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle("Ukryj zakres")
        dialog.setMinimumWidth(560)
        form = QFormLayout(dialog)

        start_input = QSpinBox(dialog)
        start_input.setRange(0, 999_999)
        start_input.setValue(1)
        form.addRow("Od taktu:", start_input)

        end_input = QSpinBox(dialog)
        end_input.setRange(0, 999_999)
        end_input.setValue(1)
        form.addRow("Do taktu:", end_input)

        duplicate_checkbox = QCheckBox(
            "Zamień istniejące yy na yyyy",
            dialog,
        )
        duplicate_checkbox.setChecked(False)
        form.addRow(duplicate_checkbox)

        spine_widget = QWidget(dialog)
        spine_layout = QVBoxLayout(spine_widget)
        spine_layout.setContentsMargins(0, 0, 0, 0)

        descriptions = self._spine_descriptions()
        spine_checkboxes: list[tuple[int, QCheckBox]] = []
        for column, spine_type in enumerate(self.document.spine_types):
            if spine_type != "**kern":
                continue

            checkbox = QCheckBox(descriptions[column], spine_widget)
            spine_layout.addWidget(checkbox)
            spine_checkboxes.append((column, checkbox))

        spine_layout.addStretch(1)

        spine_scroll = QScrollArea(dialog)
        spine_scroll.setWidgetResizable(True)
        spine_scroll.setMinimumHeight(180)
        spine_scroll.setWidget(spine_widget)
        form.addRow("Spine’y **kern:", spine_scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Ukryj")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        while dialog.exec() == QDialog.DialogCode.Accepted:
            start_measure = start_input.value()
            end_measure = end_input.value()
            selected_columns = {
                column for column, checkbox in spine_checkboxes if checkbox.isChecked()
            }

            if start_measure > end_measure:
                QMessageBox.warning(
                    dialog,
                    "Nieprawidłowy zakres",
                    "Pierwszy takt nie może być późniejszy niż ostatni.",
                )
                continue

            if not selected_columns:
                QMessageBox.warning(
                    dialog,
                    "Nie wybrano spine’u",
                    "Wybierz co najmniej jeden spine **kern.",
                )
                continue

            return (
                start_measure,
                end_measure,
                selected_columns,
                duplicate_checkbox.isChecked(),
            )

        return None

    def apply_hidden_measure_range(self) -> None:
        if self.document is None:
            return

        choice = self._ask_hidden_measure_range()
        if choice is None:
            return

        (
            start_measure,
            end_measure,
            selected_columns,
            duplicate_existing,
        ) = choice
        before = self.document.to_text()

        try:
            changed = self.document.hide_measure_range(
                start_measure=start_measure,
                end_measure=end_measure,
                kern_columns=selected_columns,
                duplicate_existing=duplicate_existing,
            )
        except HumdrumError as error:
            self._show_copyable_error(
                "Nie można ukryć zakresu",
                str(error),
            )
            return

        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage(f"Ukryto takty {start_measure}–{end_measure}")
        else:
            self.statusBar().showMessage(
                f"Brak danych do ukrycia w taktach {start_measure}–{end_measure}"
            )

    def _ask_right_align_dynamics(
        self,
    ) -> tuple[int | None, int | None, set[int]] | None:
        if self.document is None:
            return None

        kern_columns = [
            column
            for column, spine_type in enumerate(self.document.spine_types)
            if spine_type == "**kern"
        ]
        if not kern_columns:
            return None

        descriptions = self._spine_descriptions()
        part_groups: dict[int, set[int]] = {}

        if self.document.header.part_line is not None:
            part_fields = self.document.fields(self.document.header.part_line)
            for column in kern_columns:
                token = part_fields[column]
                number = token.removeprefix("*part")
                if token.startswith("*part") and number.isdigit():
                    part_groups.setdefault(int(number), set()).add(column)

        part_options: list[tuple[str, set[int]]] = []

        if part_groups:
            for part_number in sorted(part_groups):
                columns = part_groups[part_number]
                names = list(
                    dict.fromkeys(
                        descriptions[column].rsplit(" — ", 1)[-1] for column in sorted(columns)
                    )
                )
                part_options.append(
                    (
                        f"{part_number} — {' / '.join(names)}",
                        columns,
                    )
                )

            grouped_columns = set().union(*(columns for _label, columns in part_options))
            for column in kern_columns:
                if column in grouped_columns:
                    continue
                name = descriptions[column].rsplit(" — ", 1)[-1]
                part_options.append((f"? — {name}", {column}))
        else:
            for part_number, column in enumerate(
                reversed(kern_columns),
                start=1,
            ):
                name = descriptions[column].rsplit(" — ", 1)[-1]
                part_options.append((f"{part_number} — {name}", {column}))

        dialog = QDialog(self)
        dialog.setWindowTitle("Dynamika do prawej")
        dialog.setMinimumWidth(520)
        form = QFormLayout(dialog)

        all_measures_checkbox = QCheckBox("Wszystkie takty", dialog)
        all_measures_checkbox.setChecked(True)
        form.addRow(all_measures_checkbox)

        measure_input_width = 150

        start_measure_input = QSpinBox(dialog)
        start_measure_input.setRange(0, 999_999)
        start_measure_input.setValue(1)
        start_measure_input.setFixedWidth(measure_input_width)
        form.addRow("Od taktu:", start_measure_input)

        end_measure_widget = QWidget(dialog)
        end_measure_layout = QHBoxLayout(end_measure_widget)
        end_measure_layout.setContentsMargins(0, 0, 0, 0)

        end_measure_input = QSpinBox(end_measure_widget)
        end_measure_input.setRange(0, 999_999)
        end_measure_input.setValue(1)
        end_measure_input.setFixedWidth(measure_input_width)

        to_end_checkbox = QCheckBox("Do końca", end_measure_widget)
        to_end_checkbox.setChecked(False)

        end_measure_layout.addWidget(end_measure_input)
        end_measure_layout.addWidget(to_end_checkbox)
        end_measure_layout.addStretch(1)
        form.addRow("Do taktu:", end_measure_widget)

        all_spines_checkbox = QCheckBox("Wszystkie spiny", dialog)
        all_spines_checkbox.setChecked(True)
        form.addRow(all_spines_checkbox)

        start_spine_combo = QComboBox(dialog)
        end_spine_combo = QComboBox(dialog)

        for label, _columns in part_options:
            start_spine_combo.addItem(label)
            end_spine_combo.addItem(label)

        end_spine_combo.setCurrentIndex(end_spine_combo.count() - 1)
        form.addRow("Od spinu:", start_spine_combo)
        form.addRow("Do spinu:", end_spine_combo)

        def sync_measure_inputs() -> None:
            range_enabled = not all_measures_checkbox.isChecked()
            start_measure_input.setEnabled(range_enabled)
            to_end_checkbox.setEnabled(range_enabled)
            end_measure_input.setEnabled(range_enabled and not to_end_checkbox.isChecked())

        def sync_spine_inputs() -> None:
            range_enabled = not all_spines_checkbox.isChecked()
            start_spine_combo.setEnabled(range_enabled)
            end_spine_combo.setEnabled(range_enabled)

        all_measures_checkbox.toggled.connect(sync_measure_inputs)
        to_end_checkbox.toggled.connect(sync_measure_inputs)
        all_spines_checkbox.toggled.connect(sync_spine_inputs)
        sync_measure_inputs()
        sync_spine_inputs()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Przesuń")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        while dialog.exec() == QDialog.DialogCode.Accepted:
            if all_measures_checkbox.isChecked():
                start_measure = None
                end_measure = None
            else:
                start_measure = start_measure_input.value()
                end_measure = None if to_end_checkbox.isChecked() else end_measure_input.value()

            if (
                start_measure is not None
                and end_measure is not None
                and start_measure > end_measure
            ):
                QMessageBox.warning(
                    dialog,
                    "Nieprawidłowy zakres taktów",
                    "Pierwszy takt nie może być późniejszy niż ostatni.",
                )
                continue

            if all_spines_checkbox.isChecked():
                selected_columns = set(kern_columns)
            else:
                start_index = start_spine_combo.currentIndex()
                end_index = end_spine_combo.currentIndex()

                if start_index > end_index:
                    QMessageBox.warning(
                        dialog,
                        "Nieprawidłowy zakres spinów",
                        "Pierwszy spine nie może znajdować się za ostatnim.",
                    )
                    continue

                selected_columns = set().union(
                    *(columns for _label, columns in part_options[start_index : end_index + 1])
                )

            return start_measure, end_measure, selected_columns

        return None

    def apply_right_align_dynamics(self) -> None:
        if self.document is None:
            return

        choice = self._ask_right_align_dynamics()
        if choice is None:
            return

        start_measure, end_measure, selected_columns = choice
        before = self.document.to_text()

        try:
            changed_count = self.document.right_align_dynamics(
                start_measure=start_measure,
                end_measure=end_measure,
                kern_columns=selected_columns,
            )
        except HumdrumError as error:
            self._show_copyable_error(
                "Nie można przesunąć dynamiki",
                str(error),
            )
            return

        if changed_count:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage(f"Liczba przesuniętych oznaczeń dynamiki: {changed_count}")
        else:
            self.statusBar().showMessage("Nie znaleziono dynamiki wymagającej przesunięcia")

    def _ask_element_coloring(
        self,
    ) -> tuple[int | None, int | None, set[int], str, set[str]] | None:
        if self.document is None:
            return None

        kern_columns = [
            column
            for column, spine_type in enumerate(self.document.spine_types)
            if spine_type == "**kern"
        ]
        if not kern_columns:
            return None

        descriptions = self._spine_descriptions()
        part_groups: dict[int, set[int]] = {}

        if self.document.header.part_line is not None:
            part_fields = self.document.fields(self.document.header.part_line)
            for column in kern_columns:
                token = part_fields[column]
                number = token.removeprefix("*part")
                if token.startswith("*part") and number.isdigit():
                    part_groups.setdefault(int(number), set()).add(column)

        part_options: list[tuple[str, set[int]]] = []

        if part_groups:
            for part_number in sorted(part_groups):
                columns = part_groups[part_number]
                names = list(
                    dict.fromkeys(
                        descriptions[column].rsplit(" — ", 1)[-1] for column in sorted(columns)
                    )
                )
                part_options.append(
                    (
                        f"{part_number} — {' / '.join(names)}",
                        columns,
                    )
                )

            grouped_columns = set().union(*(columns for _label, columns in part_options))
            for column in kern_columns:
                if column in grouped_columns:
                    continue
                name = descriptions[column].rsplit(" — ", 1)[-1]
                part_options.append((f"? — {name}", {column}))
        else:
            for part_number, column in enumerate(
                reversed(kern_columns),
                start=1,
            ):
                name = descriptions[column].rsplit(" — ", 1)[-1]
                part_options.append((f"{part_number} — {name}", {column}))

        dialog = QDialog(self)
        dialog.setWindowTitle("Koloruj elementy")
        dialog.setMinimumWidth(560)
        form = QFormLayout(dialog)

        all_measures_checkbox = QCheckBox("Wszystkie takty", dialog)
        all_measures_checkbox.setChecked(False)
        form.addRow(all_measures_checkbox)

        measure_input_width = 150

        start_measure_input = QSpinBox(dialog)
        start_measure_input.setRange(0, 999_999)
        start_measure_input.setValue(self._coloring_start_measure)
        start_measure_input.setFixedWidth(measure_input_width)
        form.addRow("Od taktu:", start_measure_input)

        end_measure_widget = QWidget(dialog)
        end_measure_layout = QHBoxLayout(end_measure_widget)
        end_measure_layout.setContentsMargins(0, 0, 0, 0)

        end_measure_input = QSpinBox(end_measure_widget)
        end_measure_input.setRange(0, 999_999)
        end_measure_input.setValue(self._coloring_end_measure)
        end_measure_input.setFixedWidth(measure_input_width)

        to_end_checkbox = QCheckBox("Do końca", end_measure_widget)
        to_end_checkbox.setChecked(False)

        end_measure_layout.addWidget(end_measure_input)
        end_measure_layout.addWidget(to_end_checkbox)
        end_measure_layout.addStretch(1)
        form.addRow("Do taktu:", end_measure_widget)

        all_spines_checkbox = QCheckBox("Wszystkie spiny", dialog)
        all_spines_checkbox.setChecked(False)
        form.addRow(all_spines_checkbox)

        start_spine_combo = QComboBox(dialog)
        end_spine_combo = QComboBox(dialog)

        for label, _columns in part_options:
            start_spine_combo.addItem(label)
            end_spine_combo.addItem(label)

        last_spine_index = end_spine_combo.count() - 1
        start_spine_index = min(
            max(self._coloring_start_spine, 0),
            last_spine_index,
        )
        end_spine_index = min(
            max(self._coloring_end_spine, start_spine_index),
            last_spine_index,
        )
        start_spine_combo.setCurrentIndex(start_spine_index)
        end_spine_combo.setCurrentIndex(end_spine_index)
        form.addRow("Od spinu:", start_spine_combo)
        form.addRow("Do spinu:", end_spine_combo)

        color_combo = QComboBox(dialog)
        color_combo.setEditable(True)
        color_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        color_combo.addItems(
            [
                "blue",
                "dodgerblue",
                "red",
                "purple",
                "green",
            ]
        )
        color_combo.setCurrentText(self._coloring_color)

        color_completer = color_combo.completer()
        if color_completer is not None:
            color_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            color_completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)

        form.addRow("Kolor:", color_combo)

        elements_widget = QWidget(dialog)
        elements_layout = QGridLayout(elements_widget)
        elements_layout.setContentsMargins(0, 0, 0, 0)
        elements_layout.setHorizontalSpacing(18)
        elements_layout.setVerticalSpacing(6)

        element_labels = [
            ("accidentals", "Akcydencje"),
            ("articulations", "Artykulacje"),
            ("hairpins", "Dynamika graficzna"),
            ("dynamics", "Dynamika literowa"),
            ("clefs", "Klucze"),
            ("ties", "Ligatury"),
            ("slurs", "Łuki"),
            ("texts", "Teksty"),
        ]
        element_checkboxes: dict[str, QCheckBox] = {}

        for index, (element, label) in enumerate(element_labels):
            checkbox = QCheckBox(label, elements_widget)
            checkbox.setChecked(False)
            element_checkboxes[element] = checkbox
            elements_layout.addWidget(checkbox, index // 2, index % 2)

        has_dynamic_spine = any(spine_type == "**dynam" for spine_type in self.document.spine_types)
        element_checkboxes["hairpins"].setEnabled(has_dynamic_spine)
        element_checkboxes["dynamics"].setEnabled(has_dynamic_spine)

        form.addRow("Koloruj:", elements_widget)

        def sync_measure_inputs() -> None:
            range_enabled = not all_measures_checkbox.isChecked()
            start_measure_input.setEnabled(range_enabled)
            to_end_checkbox.setEnabled(range_enabled)
            end_measure_input.setEnabled(range_enabled and not to_end_checkbox.isChecked())

        def sync_spine_inputs() -> None:
            range_enabled = not all_spines_checkbox.isChecked()
            start_spine_combo.setEnabled(range_enabled)
            end_spine_combo.setEnabled(range_enabled)

        all_measures_checkbox.toggled.connect(sync_measure_inputs)
        to_end_checkbox.toggled.connect(sync_measure_inputs)
        all_spines_checkbox.toggled.connect(sync_spine_inputs)
        sync_measure_inputs()
        sync_spine_inputs()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Koloruj")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        while dialog.exec() == QDialog.DialogCode.Accepted:
            color = color_combo.currentText().strip()
            if not color:
                QMessageBox.warning(
                    dialog,
                    "Brak koloru",
                    "Wybierz albo wpisz kolor.",
                )
                continue

            selected_elements = {
                element for element, checkbox in element_checkboxes.items() if checkbox.isChecked()
            }
            if not selected_elements:
                QMessageBox.warning(
                    dialog,
                    "Brak elementów",
                    "Zaznacz przynajmniej jeden rodzaj elementów do kolorowania.",
                )
                continue

            if all_measures_checkbox.isChecked():
                start_measure = None
                end_measure = None
            else:
                start_measure = start_measure_input.value()
                end_measure = None if to_end_checkbox.isChecked() else end_measure_input.value()

            if (
                start_measure is not None
                and end_measure is not None
                and start_measure > end_measure
            ):
                QMessageBox.warning(
                    dialog,
                    "Nieprawidłowy zakres taktów",
                    "Pierwszy takt nie może być późniejszy niż ostatni.",
                )
                continue

            if all_spines_checkbox.isChecked():
                selected_columns = set(kern_columns)
            else:
                start_index = start_spine_combo.currentIndex()
                end_index = end_spine_combo.currentIndex()

                if start_index > end_index:
                    QMessageBox.warning(
                        dialog,
                        "Nieprawidłowy zakres spinów",
                        "Pierwszy spin nie może znajdować się za ostatnim.",
                    )
                    continue

                selected_columns = set().union(
                    *(columns for _label, columns in part_options[start_index : end_index + 1])
                )
            self._coloring_start_measure = start_measure_input.value()
            self._coloring_end_measure = end_measure_input.value()
            self._coloring_start_spine = start_spine_combo.currentIndex()
            self._coloring_end_spine = end_spine_combo.currentIndex()
            self._coloring_color = color

            return (
                start_measure,
                end_measure,
                selected_columns,
                color,
                selected_elements,
            )

        return None

    def apply_element_coloring(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        choice = self._ask_element_coloring()
        if choice is None:
            return

        (
            start_measure,
            end_measure,
            selected_columns,
            color,
            selected_elements,
        ) = choice
        before = self.document.to_text()

        try:
            changed_count = self.document.color_notation_elements(
                start_measure=start_measure,
                end_measure=end_measure,
                kern_columns=selected_columns,
                color=color,
                elements=selected_elements,
            )
        except HumdrumError as error:
            self._show_copyable_error(
                "Nie można pokolorować elementów",
                str(error),
            )
            return

        if changed_count:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage(f"Liczba dodanych oznaczeń koloru: {changed_count}")
        else:
            self.statusBar().showMessage("Nie znaleziono elementów wymagających kolorowania")

    def apply_custos(self) -> None:
        if self.document is None:
            return

        before = self.document.to_text()
        try:
            changed = self.document.correct_custos()
        except HumdrumError as error:
            self._show_copyable_error(
                "Nie można poprawić custosów",
                str(error),
            )
            return

        if changed:
            self.undo_texts.append(before)
            self.undo_action.setEnabled(True)
            self._refresh_table()
            self.statusBar().showMessage("Poprawiono custosy")
        else:
            self.statusBar().showMessage("Nie znaleziono custosów do poprawienia")

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
            if "instrument_class_line" in self.enabled_edit_rows:
                changed |= self.document.set_instrument_classes(
                    self._row_values("instrument_class_line")
                )
            if "instrument_code_line" in self.enabled_edit_rows:
                codes = [
                    f"*{value}" if value else "*"
                    for value in self._row_values("instrument_code_line")
                ]
                changed |= self.document.set_instrument_codes(codes)
            if "instrument_group_line" in self.enabled_edit_rows:
                changed |= self.document.set_instrument_groups(
                    self._row_values("instrument_group_line")
                )
            changed |= self.document.set_system_decoration(self.system_decoration_input.text())
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
        instrument_codes = self.document.instrument_codes()
        kern_codes = [
            code
            for spine_type, code in zip(
                self.document.spine_types,
                instrument_codes,
                strict=True,
            )
            if spine_type == "**kern"
        ]

        if kern_codes and all(code == "*" for code in kern_codes):
            QMessageBox.information(
                self,
                "Brak kodów instrumentów",
                "Dokument nie zawiera żadnego kodu instrumentu w spine’ach **kern.\n\n"
                "Filtr addic nie został uruchomiony. Uzupełnij najpierw wiersz "
                "„Kod instrumentu”.",
            )
            return

        missing = [
            str(column + 1)
            for column, (spine_type, code) in enumerate(
                zip(
                    self.document.spine_types,
                    instrument_codes,
                    strict=True,
                )
            )
            if spine_type == "**kern" and code == "*"
        ]
        if missing:
            box = QMessageBox(self)
            box.setWindowTitle("Brak kodów instrumentów")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("Brak kodów instrumentów w spine’ach: " + ", ".join(missing) + ".")
            box.setInformativeText("Czy mimo to uruchomić filtr addic?")
            proceed = box.addButton("Kontynuuj", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Wróć do edycji", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not proceed:
                return
        before = self.document.to_text()
        try:
            document = run_addic(self.document)
            document.sort_header_rows()
            self.document = document
        except HumdrumError as error:
            self._show_filter_error("Nie można uruchomić addic", error)
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
        had_measure_numbers = self.document.has_numbered_measures()

        try:
            filtered = run_barnum(self.document)
        except HumdrumError as error:
            self._show_filter_error("Nie można uruchomić barnum", error)
            return
        if filtered.to_text() == before:
            self.statusBar().showMessage("Numery taktów są już prawidłowe")
            return
        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self._refresh_table()
        if had_measure_numbers:
            self.statusBar().showMessage("Ponownie ponumerowano takty")
        else:
            self.statusBar().showMessage("Ponumerowano takty")

    def remove_system_break_records(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return
        before = self.document.to_text()
        try:
            filtered = remove_system_breaks(self.document)
        except HumdrumError as error:
            self._show_filter_error("Nie można usunąć łamań systemów", error)
            return
        if filtered.to_text() == before:
            self.statusBar().showMessage("Dokument nie zawiera łamań systemów")
            return
        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self._refresh_table()
        self.statusBar().showMessage("Usunięto łamania systemów")

    def apply_record_compaction(self) -> None:
        if self.document is None:
            return
        if not self.apply_instrument_codes(show_unchanged_status=False):
            return

        before = self.document.to_text()

        try:
            filtered = compact_records(self.document)
        except HumdrumError as error:
            self._show_filter_error(
                "Nie można skompaktować rekordów",
                error,
            )
            return

        if filtered.to_text() == before:
            self.statusBar().showMessage("Komentarze i interpretacje nie wymagają porządkowania")
            return

        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self._refresh_table()
        self.statusBar().showMessage("Uporządkowano komentarze i interpretacje")

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
            self._show_filter_error("Nie można usunąć spine’u", error)
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
            self._show_filter_error("Nie można dodać spine’u", error)
            return
        self.document = filtered
        self.undo_texts.append(before)
        self.undo_action.setEnabled(True)
        self.show_group_row = self.document.header.instrument_group_line is not None
        self._sync_ig_button()
        self._refresh_table()
        self.statusBar().showMessage(f"Dodano spine {spine_type}")

    def _ask_spine_insertion(self, *, kern: bool) -> tuple[int, bool, str, bool] | None:
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
        self.ig_button.setText("Usuń linię IG" if removing else "Dodaj linię IG")
        self.ig_button.setObjectName("dangerButton" if removing else "primaryButton")
        self.ig_button.style().unpolish(self.ig_button)
        self.ig_button.style().polish(self.ig_button)

    def _edit_checkbox_icon(self, checked: bool) -> QIcon:
        size = QSize(18, 18)
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        box = pixmap.rect().adjusted(2, 2, -2, -2)
        painter.setPen(QPen(QColor("#63d297"), 1.5))
        painter.setBrush(QColor("#168653") if checked else QColor("#18271e"))
        painter.drawRoundedRect(box, 3, 3)

        if checked:
            painter.setPen(QPen(QColor("#f2fff7"), 2.0))
            painter.drawLine(5, 9, 8, 12)
            painter.drawLine(8, 12, 14, 5)

        painter.end()
        return QIcon(pixmap)

    def _refresh_table(self) -> None:
        if self.document is None:
            return
        vertical_scroll = self.table.verticalScrollBar().value()
        self.field_edits_dirty = False
        self.undo_action.setEnabled(bool(self.undo_texts))
        self.remove_spine_button.setEnabled(self.document.spine_count > 1)
        self.right_align_dynamics_button.setEnabled(
            any(spine_type == "**kern" for spine_type in self.document.spine_types)
            and any(spine_type == "**dynam" for spine_type in self.document.spine_types)
        )
        self.color_elements_button.setEnabled(
            any(spine_type == "**kern" for spine_type in self.document.spine_types)
        )
        self.compact_records_button.setEnabled(True)

        self.system_decoration_input.blockSignals(True)
        self.system_decoration_input.setText(self.document.system_decoration())
        self.system_decoration_input.blockSignals(False)
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
            label, _, _, _ = row
            order = {
                "Typ spine’u": 0,
                "Part": 1,
                "Staff": 2,
                "Nazwa pełna": 3,
                "Nazwa skrócona": 4,
                "Kod instrumentu": 5,
                "Klasa instrumentu": 6,
                "Grupa instrumentu": 7,
            }
            return order[label]

        rows.sort(key=row_order)
        available_edit_rows = {kind for _, _, kind, _ in rows if kind is not None}
        self.enabled_edit_rows.intersection_update(available_edit_rows)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(self.document.spine_count)
        for column, spine_type in enumerate(self.document.spine_types):
            header_item = QTableWidgetItem(str(column + 1))
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            header_item.setToolTip(spine_type)
            header_item.setForeground(QColor("#eef7f1"))
            if spine_type == "**kern":
                font = header_item.font()
                font.setBold(True)
                header_item.setFont(font)
                header_item.setBackground(QColor("#294234"))
            self.table.setHorizontalHeaderItem(column, header_item)
        self.editable_row_indexes.clear()
        for row, (label, _, kind, _) in enumerate(rows):
            header_item = QTableWidgetItem(label)
            if kind:
                self.editable_row_indexes[row] = kind
                header_item.setIcon(self._edit_checkbox_icon(kind in self.enabled_edit_rows))
                header_item.setToolTip("Edytuj wiersz")
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
                    editor.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                        kind not in self.enabled_edit_rows,
                    )
                    editor_layout = QHBoxLayout(editor)
                    editor_layout.setContentsMargins(7, 2, 5, 2)
                    editor_layout.setSpacing(1)
                    prefix = QLabel(fixed_prefix)
                    prefix.setObjectName("fixedPrefix")
                    field = QLineEdit("" if value == "*" else value.removeprefix(fixed_prefix))
                    field.setFrame(False)
                    field.installEventFilter(self)
                    active = kind in self.enabled_edit_rows
                    field.setEnabled(active)
                    field.setFocusPolicy(
                        Qt.FocusPolicy.StrongFocus if active else Qt.FocusPolicy.NoFocus
                    )
                    field.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not active)
                    field.textChanged.connect(self._mark_field_edited)
                    field.textChanged.connect(
                        lambda text, column=column, fixed_prefix=fixed_prefix: (
                            self._ensure_column_text_width(column, fixed_prefix + text)
                        )
                    )
                    editor_layout.addWidget(prefix)
                    editor_layout.addWidget(field, 1)
                    self.row_inputs.setdefault(kind, {})[column] = field
                    self.table.setCellWidget(row, column, editor)
                    continue

                item = QTableWidgetItem(value)
                item.setFlags(
                    item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable
                )
                if self.document.spine_types[column] == "**kern":
                    item.setBackground(QColor("#18271e"))
                self.table.setItem(row, column, item)

        editable_fields = [
            field
            for kind, fields in self.row_inputs.items()
            if kind in self.enabled_edit_rows
            for field in fields.values()
        ]
        for current, following in pairwise(editable_fields):
            QWidget.setTabOrder(current, following)

        self.table.resizeRowsToContents()
        self.table.resizeColumnsToContents()
        for column in range(self.table.columnCount()):
            self.table.setColumnWidth(column, max(140, self.table.columnWidth(column)))
        self.table.verticalScrollBar().setValue(vertical_scroll)
        self._update_window_title()

    def _ensure_column_text_width(self, column: int, text: str) -> None:
        required = self.table.fontMetrics().horizontalAdvance(text) + 34
        if required > self.table.columnWidth(column):
            self.table.setColumnWidth(column, required)

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

    def eventFilter(self, watched, event) -> bool:
        editable_fields = [
            field
            for kind, fields in self.row_inputs.items()
            if kind in self.enabled_edit_rows
            for field in fields.values()
        ]
        if (
            watched in editable_fields
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
        ):
            current = editable_fields.index(watched)
            step = -1 if event.key() == Qt.Key.Key_Backtab else 1
            target = editable_fields[(current + step) % len(editable_fields)]
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
        if (
            watched in editable_fields
            and event.type() == QEvent.Type.MouseButtonDblClick
            and watched.cursorPositionAt(event.position().toPoint()) >= len(watched.text())
        ):
            watched.setCursorPosition(len(watched.text()))
            watched.deselect()
            return True
        if watched in editable_fields and event.type() == QEvent.Type.MouseButtonPress:
            QTimer.singleShot(0, watched.selectAll)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(".krn"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        previous_path = self.current_path
        self.load_path(Path(event.mimeData().urls()[0].toLocalFile()))
        if self.current_path != previous_path:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _apply_theme(self) -> None:
        self.setStyleSheet(SPINEWORKS_STYLE)

        buttons = [
            *self.findChildren(QPushButton),
            *self.findChildren(QToolButton),
        ]
        for button in buttons:
            if button.graphicsEffect() is not None:
                continue

            shadow = QGraphicsDropShadowEffect(button)
            shadow.setBlurRadius(6)
            shadow.setOffset(0, 1)
            shadow.setColor(QColor(0, 0, 0, 65))
            button.setGraphicsEffect(shadow)


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("aborzym")
    app.setApplicationName("SPINEWORKS")
    icon_path = Path(__file__).with_name("assets") / "spineworks.png"
    app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
