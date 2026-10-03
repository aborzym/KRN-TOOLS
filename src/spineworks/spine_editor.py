import sys
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QEvent, QModelIndex, QObject, QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spineworks.draft_save import prepare_save_text, write_verified_text
from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.meter_rhythm import meter_rest_options
from spineworks.spine_rhythm import (
    meter_at_line,
    suggest_merge_fill,
    suggest_reopening_fill,
    suggest_split_fill,
)
from spineworks.spine_validation import (
    FragmentDraft,
    RecordKind,
    ValidationState,
    build_draft_fragment_rows,
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    read_records,
    trace_spines,
    validate_draft,
)
from spineworks.status_indicator import StatusIndicator
from spineworks.theme import SPINEWORKS_STYLE


class SpacerHeader(QHeaderView):
    def __init__(
        self,
        spacers: set[int],
        parent: QWidget,
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.spacers = spacers

    def paintSection(
        self,
        painter: QPainter,
        rect: QRect,
        logical_index: int,
    ) -> None:
        if logical_index in self.spacers:
            painter.save()
            painter.fillRect(rect, QColor("#101713"))
            painter.restore()
            return
        super().paintSection(painter, rect, logical_index)


class CellGridDelegate(QStyledItemDelegate):
    navigation_requested = Signal(int, int, str)

    def __init__(
        self,
        spacers: set[int],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.spacers = spacers

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget | None:
        editor = super().createEditor(parent, option, index)

        if isinstance(editor, QLineEdit):
            editor.setProperty("table_row", index.row())
            editor.setProperty("table_column", index.column())
            brush = index.data(Qt.ItemDataRole.ForegroundRole)
            color = brush.color().name() if brush is not None else "#dce7f5"
            editor.setStyleSheet(
                f"""
                QLineEdit {{
                    background: #202b40;
                    color: {color};
                    border: 0;
                    padding: 3px 1px;
                    selection-background-color: #177245;
                    selection-color: #ffffff;
                }}
                """
            )

        return editor

    def updateEditorGeometry(
        self,
        editor: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        editor.setGeometry(option.rect.adjusted(1, 1, -1, -1))

    def setEditorData(
        self,
        editor: QWidget,
        index: QModelIndex,
    ) -> None:
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            editor.selectAll()

    def eventFilter(
        self,
        watched: QObject,
        event: QEvent,
    ) -> bool:
        if isinstance(watched, QLineEdit) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            direction = None

            if key in {Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
                backward = key == Qt.Key.Key_Backtab or bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                direction = "previous" if backward else "next"
            elif key == Qt.Key.Key_Up:
                direction = "up"
            elif key == Qt.Key.Key_Down:
                direction = "down"
            elif (
                key == Qt.Key.Key_Right
                and not watched.hasSelectedText()
                and watched.cursorPosition() == len(watched.text())
            ):
                direction = "right"
            elif (
                key == Qt.Key.Key_Left
                and not watched.hasSelectedText()
                and watched.cursorPosition() == 0
            ):
                direction = "left"

            if direction is not None:
                row = watched.property("table_row")
                column = watched.property("table_column")
                self.commitData.emit(watched)
                self.closeEditor.emit(
                    watched,
                    QAbstractItemDelegate.EndEditHint.NoHint,
                )
                self.navigation_requested.emit(row, column, direction)
                return True

        return super().eventFilter(watched, event)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        if index.column() in self.spacers:
            painter.fillRect(option.rect, QColor("#101713"))
            return

        super().paint(painter, option, index)
        painter.save()
        painter.setPen(QPen(QColor("#304536"), 1))
        rect = option.rect
        painter.drawLine(
            rect.bottomLeft(),
            rect.bottomRight(),
        )
        painter.drawLine(
            rect.topRight(),
            rect.bottomRight(),
        )
        painter.drawLine(
            rect.topLeft(),
            rect.bottomLeft(),
        )
        painter.restore()


class SpineEditor(QDialog):
    """Widok pierwszego zakresu wymagającego korekty."""

    def __init__(
        self,
        document: HumdrumDocument,
        parent: QWidget | None = None,
        *,
        file_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_path = file_path.expanduser().resolve() if file_path is not None else None
        self.setStyleSheet(SPINEWORKS_STYLE)
        self.setWindowTitle("SPINEWORKS — kontrola rozdwojeń")
        self.resize(1100, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.title_label = QLabel(self)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_row = QHBoxLayout()
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.status_indicator = StatusIndicator(self)
        title_row.addWidget(self.status_indicator)

        self.help_button = QPushButton("?", self)
        self.help_button.setObjectName("helpButton")
        self.help_button.setFixedSize(30, 30)
        self.help_button.setToolTip("Pomoc — edytor rozdwojeń")
        self.help_button.setAccessibleName("Pomoc — edytor rozdwojeń")
        self.help_button.clicked.connect(self._show_help)
        self.help_button.setStyleSheet(
            """
            QPushButton#helpButton {
                background: #1c2a20;
                color: #d9eee0;
                border: 1px solid #45634e;
                border-radius: 15px;
                font-size: 17px;
                font-weight: 600;
                padding: 0;
            }
            QPushButton#helpButton:hover {
                background: #294333;
                border-color: #63d297;
            }
            QPushButton#helpButton:pressed {
                background: #183d29;
            }
            """
        )
        title_row.addWidget(self.help_button)
        layout.addLayout(title_row)

        self.table = QTableWidget(self)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.CurrentChanged
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.AnyKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table_frame = QWidget(self)
        table_frame.setObjectName("splitTableFrame")
        table_frame.setStyleSheet(
            """
            QWidget#splitTableFrame {
                background: #121c16;
                border: 0;
            }
            QTableWidget#splitTable {
                background: #121c16;
                border: 1px solid #304536;
            }
            """
        )
        self.table.setObjectName("splitTable")
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.table)
        layout.addWidget(table_frame, 1)

        self.report = QPlainTextEdit(self)
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(150)
        layout.addWidget(self.report)

        trace = trace_spines(document)
        if trace.issue is not None:
            raise HumdrumError(f"Linia {trace.issue.line_number}: {trace.issue.message}")

        issues = find_split_issues(trace)
        problems = group_split_issues(trace, issues)
        if not problems:
            self.title_label.setText("Nie wykryto problemów rozdwojenia spinów.")
            return

        self._source_document = document
        self._source_trace = trace
        self._source_issues = issues
        self._problems = problems
        self._problem_index = 0
        self._drafts: dict[int, FragmentDraft] = {}
        self._range_states: dict[int, ValidationState] = {}

        self.problem = problems[0]
        view = build_measure_view(trace, self.problem, issues)
        self.rows = build_fragment_rows(trace, self.problem, view)
        self.draft = FragmentDraft(document, self.rows)
        self._drafts[0] = self.draft
        self.original_draft = FragmentDraft(document, self.rows)
        self._editing = True

        self.button_width = 180
        self.view_button = QPushButton("Pokaż oryginał", self)
        self.view_button.setFixedWidth(self.button_width)
        self.view_button.setObjectName("primaryButton")
        self.view_button.clicked.connect(self._toggle_view)
        title_row.insertWidget(1, self.view_button)
        self.move_merge_button = QPushButton("Przenieś scalenie", self)
        self.move_merge_button.setFixedWidth(self.button_width)
        self.move_merge_button.setObjectName("primaryButton")
        self.move_merge_button.setToolTip("Przenieś scalenie na koniec taktu.")
        self.move_merge_button.clicked.connect(self._move_merge)
        self.move_merge_button.hide()

        self.approve_button = QPushButton("Zatwierdź propozycje", self)
        self.approve_button.setFixedWidth(self.button_width)
        self.approve_button.setObjectName("primaryButton")
        self.approve_button.setToolTip("Zatwierdź wszystkie oczekujące propozycje.")
        self.approve_button.clicked.connect(self._approve_suggestions)
        self.approve_button.hide()
        title_row.insertWidget(2, self.approve_button)

        self.undo_button = QPushButton("Cofnij", self)
        self.undo_button.setFixedWidth(self.button_width)
        self.undo_button.setObjectName("primaryButton")
        self.undo_button.clicked.connect(self._undo)
        self.undo_button.setEnabled(False)
        title_row.insertWidget(2, self.undo_button)

        self.repair_button = QPushButton("Napraw rozdwojenia", self)
        self.repair_button.setFixedWidth(self.button_width)
        self.repair_button.setObjectName("primaryButton")
        self.repair_button.setToolTip(
            "Napraw rozdwojenia w bieżącym zakresie i zaproponuj wypełnienie."
        )
        self.repair_button.clicked.connect(self._repair_range)
        title_row.insertWidget(3, self.repair_button)

        navigation = QHBoxLayout()

        self.move_split_button = QPushButton("Przenieś rozdwojenie", self)
        self.move_split_button.setFixedWidth(self.button_width)
        self.move_split_button.setObjectName("primaryButton")
        self.move_split_button.setToolTip("Przenieś rozdwojenie przed pierwsze dane taktu.")
        self.move_split_button.clicked.connect(self._move_split)
        self.move_split_button.hide()

        self.join_button = QPushButton("Połącz rozdwojenia", self)
        self.join_button.setFixedWidth(self.button_width)
        self.join_button.setObjectName("primaryButton")
        self.join_button.setToolTip("Połącz zamknięcia i ponowne otwarcia w bieżącym takcie.")
        self.join_button.clicked.connect(self._join_reopenings)
        self.join_button.hide()

        navigation.addWidget(self.join_button)
        navigation.addWidget(self.move_split_button)
        navigation.addWidget(self.move_merge_button)
        navigation.addStretch()

        self.previous_button = QPushButton("Poprzedni", self)
        self.previous_button.setFixedWidth(self.button_width)
        self.previous_button.setObjectName("primaryButton")
        self.previous_button.clicked.connect(lambda: self._change_problem(-1))
        navigation.addWidget(self.previous_button)

        self.next_button = QPushButton("Następny", self)
        self.next_button.setFixedWidth(self.button_width)
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(lambda: self._change_problem(1))
        navigation.addWidget(self.next_button)

        layout.addLayout(navigation)

        self.save_button = QPushButton("Zatwierdź i zapisz wszystko", self)
        self.save_button.setFixedWidth(
            self.previous_button.width() + navigation.spacing() + self.next_button.width()
        )
        self.save_button.setObjectName("primaryButton")
        self.save_button.setToolTip("Zatwierdź propozycje i zapisz wszystkie poprawione zakresy.")
        self.save_button.clicked.connect(self._save_changes)

        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(self.save_button)
        layout.addLayout(save_row)

        self.title_label.setText(f"Takt {self.problem.measure} · zakres 1 z {len(problems)}")
        self._show_rows()
        self.report.setPlainText(
            "\n".join(
                f"Linia {issue.line_number}: {issue.message}" for issue in self.problem.issues
            )
        )
        self.table.itemChanged.connect(self._edit_item)
        self._update_validation()

    def _show_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("SPINEWORKS — pomoc do edytora rozdwojeń")
        dialog.setStyleSheet(SPINEWORKS_STYLE)
        dialog.resize(760, 650)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(
            """EDYTOR ROZDWOJEŃ SPINÓW

Edytor pokazuje takty wymagające poprawienia otwarć (*^) lub
zamknięć (*v) rozdwojonych spinów. Każda kolumna „warstwa”
odpowiada jednej gałęzi danego instrumentu.

Wiersze zachowują numery z pliku źródłowego aż do zapisu.
Nowe wiersze otrzymują opis zamiast numeru źródłowego.
„Liczba spinów” obejmuje cały rekord, również niewidoczne
w tym oknie instrumenty.


WIDOK I EDYCJA

Edytowalne pola mają niebieskawe tło. Instrumenty pomocnicze
są tylko do odczytu i mają przyciemniony tekst.

Pokaż oryginał — pozwala porównać szkic ze stanem źródłowym.
Edytuj — przywraca widok szkicu z dotychczasowymi zmianami.
Przełączanie widoku nie usuwa zmian.

Poprzedni i Następny przechodzą między zakresami.
Szkice są zachowywane podczas przechodzenia między nimi.



KONTROLKA STANU

Czerwona — zakres zawiera błąd lub pole wymagające uzupełnienia.
Żółta — zakres przeszedł kontrolę, ale ma niezatwierdzone propozycje.
Zielona — zakres przeszedł kontrolę i nie ma oczekujących propozycji.

Zielony stan nie oznacza jeszcze zapisania pliku.
Kontrola dotyczy bieżącego zakresu i obsługiwanych reguł.
Nie zastępuje sprawdzenia zgodności nut z rękopisem.


NAPRAWA

Napraw rozdwojenia — wykonuje dostępne naprawy w bieżącym
zakresie i proponuje uzupełnienie dodatkowych warstw.
Całą operację można cofnąć jednym kliknięciem „Cofnij”.

Przyciski pomocnicze:

Połącz rozdwojenia — usuwa zbędne zamknięcia i ponowne
otwarcia tej samej gałęzi w obrębie taktu.

Przenieś rozdwojenie — przenosi otwarcie przed pierwsze
dane taktu i proponuje wypełnienie dodanej warstwy.

Przenieś scalenie — przenosi zamknięcie na koniec taktu
i proponuje wypełnienie przedłużonej warstwy.

Nieaktywne przyciski oznaczają, że dana operacja nie jest
obecnie dostępna.


ZASADY OTWIERANIA I ZAMYKANIA

Otwarcia powinny występować przed pierwszym rekordem danych
w takcie. Rekord zawierający kropki również jest rekordem danych.

Scalenia powinny występować po ostatnich danych taktu.
Po scaleniu mogą pozostać komentarze oraz końcowy blok scaleń.

Sąsiadujące tokeny *v muszą zamykać komplet gałęzi jednego
rozdwojenia. Scalenia różnych instrumentów mogą znajdować się
w jednym wierszu, jeżeli rozdziela je neutralne pole *.

Program zachowuje poprawne istniejące zamknięcia i próbuje
dopisać scalenie do istniejącego wiersza. Nowy wiersz dodaje,
gdy połączenie nie jest możliwe przy uwzględnieniu zasad. 
Przy wyborze kolejności nowych zamknięć preferuje kierunek 
od prawej do lewej. Inna poprawna kolejność nie jest błędem.


PROPOZYCJE PAUZ

Ukryte pauzy mają oznaczenie ryy. Kropka oznacza kontynuację
wcześniejszego tokenu; sama nie rozpoczyna nowej pauzy.

Program uwzględnia metrum, granice dostępnych wierszy oraz
trwające wartości rytmiczne. Propozycje można edytować ręcznie.

W metrach 6/8, 9/8 i 12/8 program pyta o zapis grup pauz:
ćwierćnuta i ósemka albo ćwierćnuta z kropką.
W 6/4 pyta o podział 3+3 albo 2+2+2.

Zatwierdź propozycje — zatwierdza propozycje bieżącego zakresu.
Nie zapisuje pliku.


KLAWIATURA

Tab / Shift+Tab — następne / poprzednie edytowalne pole.
Strzałka w prawo na końcu tekstu — edytowalne pole po prawej.
Strzałka w lewo na początku tekstu — edytowalne pole po lewej.
Strzałki góra / dół — edytowalne pole w tej samej kolumnie.
Pola tylko do odczytu są pomijane.


COFANIE I ZAPIS

Cofnij przywraca stan sprzed ostatniej operacji w bieżącym
szkicu. Jedno kliknięcie przycisku naprawy stanowi jedną operację.

Zatwierdź i zapisz wszystko — zapisuje zmiany ze wszystkich
zmienionych zakresów, także tych aktualnie niewidocznych,
i zatwierdza oczekujące propozycje.

Przed zapisem każdy zmieniony zakres musi przejść kontrolę.
Czerwony zakres blokuje zapis wszystkich zmian.

Program sprawdza, czy plik na dysku nie zmienił się od wczytania.
Po zapisie aktualizuje numery linii i rozpoczyna nowy stan
źródłowy. Historia cofania szkiców zostaje wyczyszczona.

Przy zamykaniu okna z niezapisanymi zmianami można je zapisać,
odrzucić albo anulować zamknięcie.


OGRANICZENIA

Manipulatory *x i *+ oraz niektóre bardziej złożone przypadki
strukturalne wymagają osobnej obsługi. Jeśli program nie może
bezpiecznie przygotować naprawy, pokazuje komunikat.
"""
        )
        layout.addWidget(text, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Zamknij", dialog)
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(dialog.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        dialog.exec()

    def _change_problem(self, step: int) -> None:
        button = self.next_button if step > 0 else self.previous_button
        button.setFocus()

        if not button.isEnabled():
            return

        self._load_problem(self._problem_index + step)

    def _load_problem(self, index: int) -> None:
        if not 0 <= index < len(self._problems):
            return

        self._problem_index = index
        self.problem = self._problems[index]
        view = build_measure_view(
            self._source_trace,
            self.problem,
            self._source_issues,
        )
        self.rows = build_fragment_rows(
            self._source_trace,
            self.problem,
            view,
        )

        if index not in self._drafts:
            self._drafts[index] = FragmentDraft(
                self._source_document,
                self.rows,
            )

        self.draft = self._drafts[index]
        self.original_draft = FragmentDraft(
            self._source_document,
            self.rows,
        )
        self._editing = True
        self.view_button.setText("Pokaż oryginał")
        self.move_merge_button.setVisible(True)
        self.title_label.setText(
            f"Takt {self.problem.measure} · zakres {index + 1} z {len(self._problems)}"
        )

        self.table.blockSignals(True)
        try:
            self._show_rows()
        finally:
            self.table.blockSignals(False)

        self.table.verticalScrollBar().setValue(0)
        self.table.horizontalScrollBar().setValue(0)
        self._update_validation()

    def _show_rows(self) -> None:
        if self._editing:
            rows = build_draft_fragment_rows(
                self.draft,
                start_line=min(row.source_line for row in self.rows),
                end_line=max(row.source_line for row in self.rows),
                editable_roots={
                    identity.root_column for identity in self.problem.editable_identities
                },
                helper_roots={identity.root_column for identity in self.problem.helper_identities},
            )
        else:
            rows = self.rows

        identities = sorted(
            (
                *self.problem.editable_identities,
                *self.problem.helper_identities,
            ),
            key=lambda identity: identity.root_column,
        )
        editable_roots = {identity.root_column for identity in self.problem.editable_identities}

        starts: dict[int, int] = {}
        widths: dict[int, int] = {}
        spacers: set[int] = set()
        headers = ["Linia źródłowa", "Liczba spinów"]
        column_count = 2

        for identity in identities:
            root = identity.root_column
            widths[root] = max(
                (sum(cell.identity.root_column == root for cell in row.cells) for row in rows),
                default=1,
            )

            spacers.add(column_count)
            headers.append("")
            column_count += 1

            starts[root] = column_count
            headers.extend(f"Warstwa {voice + 1}" for voice in range(widths[root]))
            column_count += widths[root]

        self.table.clearSpans()
        self.table.clear()
        self.table.setColumnCount(column_count)
        self.table.setRowCount(len(rows) + 1)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setShowGrid(False)
        delegate = CellGridDelegate(spacers, self.table)
        delegate.navigation_requested.connect(self._navigate_cell)
        self.table.setItemDelegate(delegate)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        pending_cells = set(self.draft.pending_suggestions) if self._editing else set()

        def put(
            row: int,
            column: int,
            text: str,
            *,
            editable: bool = False,
            muted: bool = False,
            pending: bool = False,
            source_cell: tuple[int, int] | None = None,
        ) -> None:
            item = QTableWidgetItem(text)
            if column < 2:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if editable and self._editing:
                flags |= Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)

            if source_cell is not None:
                item.setData(Qt.ItemDataRole.UserRole, source_cell)

            if editable:
                item.setBackground(QColor("#202b40"))
            if pending:
                color = "#729f9b"
                item.setToolTip("Propozycja — oczekuje na zatwierdzenie.")
            elif text.startswith("!"):
                color = "#a17c56" if muted else "#dfa060"
            elif text in {"*^", "*v"}:
                color = "#a4788d" if muted else "#d69ab7"
            elif text.startswith("*"):
                color = "#7e6d8c" if muted else "#a98bbf"
            elif muted:
                color = "#87978c"
            else:
                color = "#dce7f5" if editable else "#e7f4eb"

            item.setForeground(QColor(color))
            self.table.setItem(row, column, item)

        self.table.setRowHeight(
            0,
            self.table.fontMetrics().height() * 2 + 12,
        )

        for identity in identities:
            root = identity.root_column
            column = starts[root]
            label = f"{identity.instrument or 'Bez nazwy'} — {identity.spine_type}"
            helper = root not in editable_roots

            if helper:
                label += "\npomocniczy"

            put(0, column, label, muted=helper)
            self.table.item(0, column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            if widths[root] > 1:
                self.table.setSpan(0, column, 1, widths[root])

        for table_row, row in enumerate(rows, start=1):
            line_label = str(row.source_line) if row.source_line is not None else row.description
            put(table_row, 0, line_label)
            put(
                table_row,
                1,
                "" if row.spine_count is None else str(row.spine_count),
            )

            if row.global_text:
                put(table_row, 3, row.global_text)
                if column_count > 4:
                    self.table.setSpan(
                        table_row,
                        3,
                        1,
                        column_count - 3,
                    )
                continue

            offsets: dict[int, int] = {}
            for cell in row.cells:
                root = cell.identity.root_column
                offset = offsets.get(root, 0)
                put(
                    table_row,
                    starts[root] + offset,
                    cell.token,
                    editable=cell.editable,
                    muted=root not in editable_roots,
                    pending=(row.source_line, cell.source_column) in pending_cells,
                    source_cell=(
                        (row.rendered_index, cell.source_column) if self._editing else None
                    ),
                )
                offsets[root] = offset + 1

        vertical_header = self.table.verticalHeader()
        normal_height = vertical_header.defaultSectionSize()
        barline_height = max(
            self.table.fontMetrics().height() + 4,
            normal_height - 5,
        )
        vertical_header.setMinimumSectionSize(barline_height)

        helper_columns = {
            starts[root] + offset
            for root in starts
            if root not in editable_roots
            for offset in range(widths[root])
        }

        for table_row, row in enumerate(rows, start=1):
            is_barline = row.kind is RecordKind.BARLINE
            self.table.setRowHeight(
                table_row,
                barline_height if is_barline else normal_height,
            )

            if not is_barline:
                continue

            for column in range(column_count):
                if column in spacers:
                    continue

                item = self.table.item(table_row, column)
                if item is None:
                    continue

                item.setBackground(QColor("#342a20"))
                item.setForeground(QColor("#9c8c76" if column in helper_columns else "#d7bd99"))

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(5)

        for column in spacers:
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Fixed,
            )
            self.table.setColumnWidth(column, 5)

            for row in range(self.table.rowCount()):
                # Komentarz globalny może obejmować kilka grup.
                if self.table.columnSpan(row, 3) > 1 and column > 3:
                    continue

                spacer = QWidget(self.table)
                spacer.setStyleSheet("background: #101713;")
                self.table.setCellWidget(row, column, spacer)

        self.table.setHorizontalHeader(SpacerHeader(spacers, self.table))
        header = self.table.horizontalHeader()
        header.show()
        header.setStyleSheet(
            """
            QHeaderView {
                background: #121c16;
                border: 0;
            }
            QHeaderView::section {
                background: #1c2a20;
                color: #d9eee0;
                padding: 8px;
                border: 0;
                border-right: 1px solid #304536;
                border-bottom: 1px solid #304536;
            }
            """
        )
        header.setMinimumSectionSize(5)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in spacers:
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Fixed,
            )
            self.table.setColumnWidth(column, 5)
        metrics = self.table.fontMetrics()
        base_width = metrics.horizontalAdvance("Warstwa 1") + 32

        for identity in identities:
            root = identity.root_column
            for offset in range(widths[root]):
                column = starts[root] + offset
                required_width = base_width

                for row in range(1, self.table.rowCount()):
                    if self.table.columnSpan(row, column) > 1:
                        continue
                    item = self.table.item(row, column)
                    if item is not None:
                        required_width = max(
                            required_width,
                            metrics.horizontalAdvance(item.text()) + 20,
                        )

                header.setSectionResizeMode(
                    column,
                    QHeaderView.ResizeMode.Interactive,
                )
                self.table.setColumnWidth(column, required_width)

    def _target_structure(self):
        rendered = self.draft.rendered_lines()
        positions = [
            index
            for index, line in enumerate(rendered)
            if (
                (
                    reference := (
                        line.source_line if line.source_line is not None else line.anchor_line
                    )
                )
                is not None
                and self.problem.start_line <= reference <= self.problem.end_line
            )
        ]
        prefix = rendered[: max(positions) + 1] if positions else ()

        cached = getattr(self, "_target_structure_cache", None)
        if cached is not None and cached[0] == prefix:
            return prefix, cached[1]

        records = read_records("\n".join(line.text for line in prefix))
        tracing_lines = [
            "\t".join(token or "." for token in record.fields)
            if record.kind is RecordKind.DATA
            else record.text
            for record in records
        ]
        trace = trace_spines(HumdrumDocument(tracing_lines, False)) if prefix else None
        self._target_structure_cache = (prefix, trace)
        return prefix, trace

    def _reopening_target(self) -> tuple[int, int] | None:
        rendered, trace = self._target_structure()
        if trace is None or trace.issue is not None:
            return None

        editable_roots = {identity.root_column for identity in self.problem.editable_identities}

        for index, row in enumerate(trace.records):
            source_line = rendered[index].source_line
            if source_line is None:
                continue
            if not self.problem.start_line <= source_line < self.problem.end_line:
                continue
            if row.record.kind is not RecordKind.INTERPRETATION:
                continue

            roots = {
                branch.identity.root_column
                for token, branch in zip(
                    row.record.fields,
                    row.branches,
                    strict=True,
                )
                if token == "*v" and branch.identity.root_column in editable_roots
            }
            if not roots:
                continue

            for following in trace.records[index + 1 :]:
                if following.record.kind is RecordKind.BARLINE:
                    break
                if following.record.kind is not RecordKind.INTERPRETATION:
                    continue

                for token, branch in zip(
                    following.record.fields,
                    following.branches,
                    strict=True,
                ):
                    root = branch.identity.root_column
                    if token == "*^" and root in roots:
                        return source_line, root

        return None

    def _split_target(self) -> tuple[int, int] | None:
        rendered, trace = self._target_structure()
        if trace is None:
            return None

        for issue in self.problem.issues:
            if issue.code != "late_split":
                continue

            indices = [
                index
                for index, line in enumerate(rendered)
                if line.source_line == issue.line_number
            ]
            if len(indices) != 1:
                continue

            index = indices[0]
            if trace.issue is not None and trace.issue.line_number <= index + 1:
                continue
            if index >= len(trace.records):
                continue

            selected = trace.records[index]
            if selected.record.kind is not RecordKind.INTERPRETATION:
                continue

            roots = {identity.root_column for identity in issue.identities}
            for token, branch in zip(
                selected.record.fields,
                selected.branches,
                strict=True,
            ):
                root = branch.identity.root_column
                if token == "*^" and root in roots:
                    return issue.line_number, root

        return None

    def _merge_target(self) -> tuple[int, int] | None:
        rendered, trace = self._target_structure()
        if trace is None:
            return None

        for issue in self.problem.issues:
            if issue.code != "early_merge":
                continue

            indices = [
                index
                for index, line in enumerate(rendered)
                if line.source_line == issue.line_number
            ]
            if len(indices) != 1:
                continue

            index = indices[0]
            if trace.issue is not None and trace.issue.line_number <= index + 1:
                continue
            if index >= len(trace.records):
                continue

            selected = trace.records[index]
            if selected.record.kind is not RecordKind.INTERPRETATION:
                continue

            roots = {identity.root_column for identity in issue.identities}
            for token, branch in zip(
                selected.record.fields,
                selected.branches,
                strict=True,
            ):
                root = branch.identity.root_column
                if token == "*v" and root in roots:
                    return issue.line_number, root

        return None
        rendered = self.draft.rendered_lines()

        for issue in self.problem.issues:
            if issue.code != "early_merge":
                continue

            indices = [
                index
                for index, line in enumerate(rendered)
                if line.source_line == issue.line_number
            ]
            if len(indices) != 1:
                continue

            index = indices[0]
            fields = rendered[index].text.split("\t")
            if "*v" not in fields:
                continue

            tracing_lines: list[str] = []
            for line in rendered[: index + 1]:
                records = read_records(line.text)
                if records and records[0].kind is RecordKind.DATA:
                    tracing_lines.append("\t".join(token or "." for token in records[0].fields))
                else:
                    tracing_lines.append(line.text)

            trace = trace_spines(HumdrumDocument(tracing_lines, False))
            if trace.issue is not None:
                continue

            selected = trace.records[-1]
            if selected.record.kind is not RecordKind.INTERPRETATION:
                continue

            roots = {identity.root_column for identity in issue.identities}
            for token, branch in zip(fields, selected.branches, strict=True):
                root = branch.identity.root_column
                if token == "*v" and root in roots:
                    return issue.line_number, root

        return None

    def _apply_repair_operation(
        self,
        operation: str,
        target: tuple[int, int],
    ) -> bool:
        source_line, root_column = target
        rendered = self.draft.rendered_lines()
        current_line = self.draft.rendered_index(source_line) + 1
        analysis_end = len(rendered)

        for index in range(current_line, len(rendered)):
            records = read_records(rendered[index].text)
            if records and records[0].kind is RecordKind.BARLINE:
                analysis_end = index + 1
                break

        candidate = HumdrumDocument(
            [line.text for line in rendered[:analysis_end]],
            False,
        )
        trace = trace_spines(candidate)
        if trace.issue is not None:
            raise HumdrumError(trace.issue.message)

        selected = next(row for row in trace.records if row.record.line_number == current_line)
        identity = next(
            branch.identity
            for branch in selected.branches
            if branch.identity.root_column == root_column
        )

        functions = {
            "join": (suggest_reopening_fill, self.draft.join_reopenings),
            "split": (suggest_split_fill, self.draft.move_split),
            "merge": (suggest_merge_fill, self.draft.move_merge),
        }
        if operation not in functions:
            raise ValueError("Nieznana operacja naprawy rozdwojenia.")

        suggest, apply = functions[operation]
        rest_option = None

        if identity.spine_type == "**kern":
            meter = meter_at_line(candidate, current_line, root_column)
            options = meter_rest_options(meter)

            if len(options) == 1:
                rest_option = options[0]
            else:
                labels = [option.label for option in options]
                label, accepted = QInputDialog.getItem(
                    self,
                    "Podział pauz",
                    (
                        f"{identity.instrument or 'Bez nazwy'} — "
                        f"{meter.numerator}/{meter.denominator}\n"
                        "Wybierz sposób podziału ukrytych pauz:"
                    ),
                    labels,
                    0,
                    False,
                )
                if not accepted:
                    return False
                rest_option = options[labels.index(label)]

        timing_start = perf_counter()
        if operation == "join" and identity.spine_type != "**kern":
            suggestions = ()
        else:
            suggestions = suggest(
                candidate,
                current_line,
                root_column,
                rest_option=rest_option,
            )
        print(
            f"Obliczenie propozycji: {perf_counter() - timing_start:.3f} s",
            flush=True,
        )

        tokens: list[tuple[int, int, str]] = []
        for suggestion in suggestions:
            original_line = rendered[suggestion.source_line - 1].source_line
            if original_line is None:
                raise HumdrumError("Pole propozycji nie ma numeru linii źródłowej.")
            tokens.append((original_line, suggestion.source_column, suggestion.token))

        with self.draft.group_changes():
            structure_start = perf_counter()
            proposal = apply(*target)
            print(
                f"Zmiana struktury {operation}: {perf_counter() - structure_start:.3f} s",
                flush=True,
            )
            if proposal is None:
                return False

            fill_start = perf_counter()
            if operation == "join" and identity.spine_type == "**kern":
                joined_lines = self.draft.rendered_lines()
                replacements: list[tuple[int, int, str, str]] = []

                for number, column, token in tokens:
                    row_index = self.draft.rendered_index(number)
                    expected = joined_lines[row_index].text.split("\t")[column]
                    replacements.append((number, column, expected, token))

                self.draft.propose_hidden_rest_tokens(tuple(replacements))

            elif operation == "join":
                self.draft.propose_tokens(
                    tuple((number, column, ".") for number, column in proposal.proposed_cells)
                )
            else:
                self.draft.propose_tokens(tuple(tokens))

            print(
                f"Wpisanie propozycji {operation}: {perf_counter() - fill_start:.3f} s",
                flush=True,
            )

        return True

    def _repair_range(self) -> None:
        repair_start = perf_counter()
        self.repair_button.setFocus()
        if not self._editing:
            return

        try:
            with self.draft.group_changes():
                seen_states: set[str] = set()

                while True:
                    operation = ""
                    target = None
                    search_start = perf_counter()
                    for name, find_target in (
                        ("join", self._reopening_target),
                        ("split", self._split_target),
                        ("merge", self._merge_target),
                    ):
                        target = find_target()
                        if target is not None:
                            operation = name
                            break
                    print(
                        f"Wyszukiwanie operacji: {perf_counter() - search_start:.3f} s",
                        flush=True,
                    )
                    if target is None:
                        break

                    before = self.draft.to_text()
                    if before in seen_states:
                        raise ValueError(
                            "Naprawa powtarza ten sam stan — zakres wymaga ręcznej edycji."
                        )
                    seen_states.add(before)

                    operation_start = perf_counter()
                    applied = self._apply_repair_operation(operation, target)
                    print(
                        f"Operacja {operation}: {perf_counter() - operation_start:.3f} s",
                        flush=True,
                    )
                    if not applied:
                        raise ValueError(
                            "Naprawa została przerwana. Zmiany z tego kliknięcia zostały wycofane."
                        )

                    if self.draft.to_text() == before:
                        raise ValueError("Operacja nie zmieniła zakresu — wymagana ręczna edycja.")

                result = validate_draft(
                    self.draft,
                    start_line=self.problem.start_line,
                    end_line=self.problem.end_line,
                )
                if result.state is ValidationState.ERROR:
                    raise ValueError(
                        "Nie udało się poprawić całego zakresu. "
                        "Zmiany z tego kliknięcia zostały wycofane.\n\n"
                        + "\n".join(result.messages)
                    )

        except (ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        self._refresh_after_repair(result)
        print(
            f"Cała naprawa zakresu: {perf_counter() - repair_start:.3f} s",
            flush=True,
        )

    def _refresh_after_repair(self, validation_result=None) -> None:
        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()

        timing_start = perf_counter()
        self.table.blockSignals(True)
        try:
            self._show_rows()
        finally:
            self.table.blockSignals(False)

        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)
        print(
            f"Odbudowa tabeli: {perf_counter() - timing_start:.3f} s",
            flush=True,
        )

        timing_start = perf_counter()
        self._update_validation(validation_result)
        print(
            f"Kontrola zakresu: {perf_counter() - timing_start:.3f} s",
            flush=True,
        )

    def _join_reopenings(self) -> None:
        self.join_button.setFocus()
        target = self._reopening_target()
        if target is None:
            return

        try:
            changed = self._apply_repair_operation("join", target)
        except (ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        if changed:
            self._refresh_after_repair()

    def _move_split(self) -> None:
        self.move_split_button.setFocus()
        target = self._split_target()
        if target is None:
            return

        try:
            changed = self._apply_repair_operation("split", target)
        except (ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        if changed:
            self._refresh_after_repair()

    def _move_merge(self) -> None:
        self.move_merge_button.setFocus()
        target = self._merge_target()
        if target is None:
            return

        try:
            changed = self._apply_repair_operation("merge", target)
        except (ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        if changed:
            self._refresh_after_repair()

        self.move_merge_button.setFocus()
        target = self._merge_target()
        if target is None:
            return

        source_line, root_column = target

        try:
            rendered = self.draft.rendered_lines()
            current_line = self.draft.rendered_index(source_line) + 1
            candidate = HumdrumDocument.from_text(self.draft.to_text())
            trace = trace_spines(candidate)

            if trace.issue is not None:
                raise HumdrumError(trace.issue.message)

            selected = next(row for row in trace.records if row.record.line_number == current_line)
            identity = next(
                branch.identity
                for branch in selected.branches
                if branch.identity.root_column == root_column
            )

            rest_option = None

            if identity.spine_type == "**kern":
                meter = meter_at_line(candidate, current_line, root_column)
                options = meter_rest_options(meter)

                if len(options) == 1:
                    rest_option = options[0]
                else:
                    labels = [option.label for option in options]
                    label, accepted = QInputDialog.getItem(
                        self,
                        "Podział pauz",
                        (
                            f"{identity.instrument or 'Bez nazwy'} — "
                            f"{meter.numerator}/{meter.denominator}\n"
                            "Wybierz sposób podziału ukrytych pauz:"
                        ),
                        labels,
                        0,
                        False,
                    )
                    if not accepted:
                        return

                    rest_option = options[labels.index(label)]

            timing_start = perf_counter()
            suggestions = suggest_merge_fill(
                candidate,
                current_line,
                root_column,
                rest_option=rest_option,
            )
            print(
                f"Obliczenie propozycji: {perf_counter() - timing_start:.3f} s",
                flush=True,
            )

            tokens: list[tuple[int, int, str]] = []

            for suggestion in suggestions:
                original_line = rendered[suggestion.source_line - 1].source_line
                if original_line is None:
                    raise HumdrumError("Pole propozycji nie ma numeru linii źródłowej.")

                tokens.append(
                    (
                        original_line,
                        suggestion.source_column,
                        suggestion.token,
                    )
                )

            with self.draft.group_changes():
                timing_start = perf_counter()
                proposal = self.draft.move_merge(*target)
                print(
                    f"Przeniesienie scalenia: {perf_counter() - timing_start:.3f} s",
                    flush=True,
                )
                if proposal is None:
                    return

                timing_start = perf_counter()
                self.draft.propose_tokens(tuple(tokens))
                print(
                    f"Wpisanie propozycji: {perf_counter() - timing_start:.3f} s",
                    flush=True,
                )

        except (ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()

        timing_start = perf_counter()
        self.table.blockSignals(True)
        try:
            self._show_rows()
        finally:
            self.table.blockSignals(False)

        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)
        print(
            f"Odbudowa tabeli: {perf_counter() - timing_start:.3f} s",
            flush=True,
        )

        timing_start = perf_counter()
        self._update_validation()
        print(
            f"Kontrola zakresu: {perf_counter() - timing_start:.3f} s",
            flush=True,
        )

    def _undo(self) -> None:
        self.undo_button.setFocus()

        if not self._editing or not self.draft.undo():
            return

        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()

        self.table.blockSignals(True)
        try:
            self._show_rows()
        finally:
            self.table.blockSignals(False)

        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)
        self._update_validation()

    def _approve_suggestions(self) -> None:
        self.approve_button.setFocus()

        if not self._editing or not self.draft.approve_suggestions():
            return

        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()

        self.table.blockSignals(True)
        try:
            self._show_rows()
        finally:
            self.table.blockSignals(False)

        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)
        self._update_validation()

    def _toggle_view(self) -> None:
        # Zakończ edycję aktywnego pola przed odczytaniem szkicu.
        self.view_button.setFocus()

        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()
        current_row = self.table.currentRow()
        current_column = self.table.currentColumn()

        self._editing = not self._editing
        self.view_button.setText("Pokaż oryginał" if self._editing else "Edytuj")
        self.move_merge_button.setVisible(True)

        self.table.blockSignals(True)
        try:
            self._show_rows()
            if current_row >= 0 and current_column >= 0:
                self.table.setCurrentCell(current_row, current_column)
        finally:
            self.table.blockSignals(False)

        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)
        self._update_validation()

    def _navigate_cell(
        self,
        row: int,
        column: int,
        direction: str,
    ) -> None:
        editable = [
            (r, c)
            for r in range(self.table.rowCount())
            for c in range(self.table.columnCount())
            if (
                (item := self.table.item(r, c)) is not None
                and item.flags() & Qt.ItemFlag.ItemIsEditable
            )
        ]
        current = (row, column)
        target = None

        if direction in {"next", "previous"}:
            if current in editable:
                position = editable.index(current)
                step = 1 if direction == "next" else -1
                destination = position + step
                if 0 <= destination < len(editable):
                    target = editable[destination]
        elif direction == "right":
            target = next(
                ((r, c) for r, c in editable if r == row and c > column),
                None,
            )
        elif direction == "left":
            target = next(
                ((r, c) for r, c in reversed(editable) if r == row and c < column),
                None,
            )
        elif direction == "down":
            target = next(
                ((r, c) for r, c in editable if c == column and r > row),
                None,
            )
        elif direction == "up":
            target = next(
                ((r, c) for r, c in reversed(editable) if c == column and r < row),
                None,
            )

        if target is None:
            target = current

        item = self.table.item(*target)
        if item is not None:
            self.table.setCurrentItem(item)
            self.table.scrollToItem(item)
            self.table.editItem(item)

    def _edit_item(self, item: QTableWidgetItem) -> None:
        source_cell = item.data(Qt.ItemDataRole.UserRole)
        if source_cell is None or not self._editing:
            return

        rendered_index, column = source_cell

        try:
            self.draft.edit_rendered_token(
                rendered_index,
                column,
                item.text(),
            )
        except (ValueError, HumdrumError) as error:
            previous = self.draft.rendered_lines()[rendered_index].text.split("\t")[column]
            self.table.blockSignals(True)
            try:
                item.setText(previous)
            finally:
                self.table.blockSignals(False)
            self.report.setPlainText(str(error))
            return

        text = item.text()
        source_line = self.draft.rendered_lines()[rendered_index].source_line
        pending = (source_line, column) in self.draft.pending_suggestions

        if pending:
            color = "#729f9b"
        elif text.startswith("!"):
            color = "#dfa060"
        elif text in {"*^", "*v"}:
            color = "#d69ab7"
        elif text.startswith("*"):
            color = "#a98bbf"
        else:
            color = "#dce7f5"

        self.table.blockSignals(True)
        try:
            item.setForeground(QColor(color))
            item.setToolTip("Propozycja — oczekuje na zatwierdzenie." if pending else "")
        finally:
            self.table.blockSignals(False)

        self._update_validation()

    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "save_button"):
            self.save_button.setFocus()

        drafts = getattr(self, "_drafts", {})
        if not any(draft.dirty for draft in drafts.values()):
            event.accept()
            return

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Niezapisane zmiany")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText("W edytorze są niezapisane zmiany.")
        dialog.setInformativeText(
            "Możesz je zatwierdzić i zapisać, porzucić albo wrócić do edycji."
        )

        save = dialog.addButton(
            "Zatwierdź i zapisz",
            QMessageBox.ButtonRole.AcceptRole,
        )
        discard = dialog.addButton(
            "Porzuć zmiany",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel = dialog.addButton(
            "Anuluj",
            QMessageBox.ButtonRole.RejectRole,
        )
        save.setEnabled(self.save_button.isEnabled())
        if not save.isEnabled():
            save.setToolTip(
                "Przed zapisem popraw wszystkie zmienione zakresy oznaczone na czerwono."
            )

        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked is discard:
            event.accept()
        elif clicked is save:
            self._save_changes()
            if any(draft.dirty for draft in self._drafts.values()):
                event.ignore()
            else:
                event.accept()
        else:
            event.ignore()

    def _save_changes(self) -> None:
        self.save_button.setFocus()
        if self._file_path is None:
            self.report.setPlainText("Nie podano ścieżki pliku do zapisu.")
            return

        ranges = tuple(
            (
                draft,
                self._problems[index].start_line,
                self._problems[index].end_line,
            )
            for index, draft in sorted(self._drafts.items())
            if draft.dirty
        )
        if not ranges:
            return

        try:
            text = prepare_save_text(self._source_document, ranges)
            document = HumdrumDocument.from_text(text)
            trace = trace_spines(document)
            if trace.issue is not None:
                raise HumdrumError(trace.issue.message)

            issues = find_split_issues(trace)
            problems = group_split_issues(trace, issues)

            write_verified_text(
                self._file_path,
                expected_text=self._source_document.to_text(),
                new_text=text,
            )
        except (OSError, UnicodeError, ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        self._source_document = document
        self._source_trace = trace
        self._source_issues = issues
        self._problems = problems
        self._drafts.clear()
        self._range_states.clear()

        if problems:
            self._load_problem(0)
            self.report.appendPlainText(
                "\nZapisano wszystkie poprawione zakresy. "
                "Numery linii odpowiadają teraz zapisanemu plikowi."
            )
        else:
            self._editing = False
            self.table.blockSignals(True)
            try:
                self.table.clearSpans()
                self.table.clear()
                self.table.setRowCount(0)
            finally:
                self.table.blockSignals(False)

            self.table.setEnabled(False)
            for button in (
                self.view_button,
                self.undo_button,
                self.repair_button,
                self.approve_button,
                self.join_button,
                self.move_split_button,
                self.move_merge_button,
                self.previous_button,
                self.next_button,
                self.save_button,
            ):
                button.setEnabled(False)

            self.status_indicator.set_state(ValidationState.VALID)
            self.title_label.setText("Wszystkie rozdwojenia poprawione.")
            self.report.setPlainText(
                "Zapisano wszystkie zmiany. Nie wykryto kolejnych problemów rozdwojenia spinów."
            )

    def _update_validation(self, result=None) -> None:
        if result is None:
            result = validate_draft(
                self.draft if self._editing else self.original_draft,
                start_line=self.problem.start_line,
                end_line=self.problem.end_line,
            )
        self.status_indicator.set_state(result.state)
        if self._editing:
            self._range_states[self._problem_index] = result.state

        changed_indices = [index for index, draft in self._drafts.items() if draft.dirty]
        self.save_button.setEnabled(
            self._file_path is not None
            and bool(changed_indices)
            and all(
                self._range_states.get(index, ValidationState.ERROR)
                in {ValidationState.PENDING, ValidationState.VALID}
                for index in changed_indices
            )
        )

        self.view_button.setEnabled(self.draft.dirty or not self._editing)
        self.move_merge_button.setVisible(True)
        self.move_merge_button.setEnabled(self._editing and self._merge_target() is not None)
        self.approve_button.setVisible(True)
        self.approve_button.setEnabled(self._editing and bool(self.draft.pending_suggestions))
        self.undo_button.setVisible(True)
        self.undo_button.setEnabled(self._editing and self.draft.can_undo)
        self.move_split_button.setVisible(True)
        self.move_split_button.setEnabled(self._editing and self._split_target() is not None)
        self.join_button.setVisible(True)
        self.join_button.setEnabled(self._editing and self._reopening_target() is not None)
        self.repair_button.setEnabled(
            self._editing
            and (
                self.join_button.isEnabled()
                or self.move_split_button.isEnabled()
                or self.move_merge_button.isEnabled()
            )
        )
        self.previous_button.setEnabled(self._problem_index > 0)
        self.next_button.setEnabled(self._problem_index + 1 < len(self._problems))
        instruments = list(
            dict.fromkeys(
                identity.instrument or "Bez nazwy" for identity in self.problem.editable_identities
            )
        )
        heading = "Do poprawienia: " + ", ".join(instruments)
        self.report.setPlainText(heading + "\n\n" + "\n".join(result.messages))


def main() -> int:
    if len(sys.argv) != 2:
        print("Użycie: python -m spineworks.spine_editor plik.krn")
        return 2

    app = QApplication(sys.argv)

    try:
        path = Path(sys.argv[1]).expanduser()
        document = HumdrumDocument.from_text(path.read_text(encoding="utf-8"))
        editor = SpineEditor(document, file_path=path)
    except (OSError, UnicodeError, HumdrumError) as error:
        print(f"Nie można otworzyć edytora: {error}")
        return 1

    editor.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
