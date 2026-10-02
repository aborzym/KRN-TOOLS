import sys
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QEvent, QModelIndex, QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.meter_rhythm import meter_rest_options
from spineworks.spine_rhythm import meter_at_line, suggest_merge_fill
from spineworks.spine_validation import (
    FragmentDraft,
    build_draft_fragment_rows,
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
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


class SpineEditor(QWidget):
    """Widok pierwszego zakresu wymagającego korekty."""

    def __init__(
        self,
        document: HumdrumDocument,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
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

        self.problem = problems[0]
        view = build_measure_view(trace, self.problem, issues)
        self.rows = build_fragment_rows(trace, self.problem, view)
        self.draft = FragmentDraft(document, self.rows)
        self.original_draft = FragmentDraft(document, self.rows)
        self._editing = False

        self.button_width = 180
        self.view_button = QPushButton("Edytuj", self)
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
        title_row.insertWidget(2, self.move_merge_button)
        self.title_label.setText(f"Takt {self.problem.measure} · zakres 1 z {len(problems)}")
        self._show_rows()
        self.report.setPlainText(
            "\n".join(
                f"Linia {issue.line_number}: {issue.message}" for issue in self.problem.issues
            )
        )
        self.table.itemChanged.connect(self._edit_item)
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

        for identity in identities:
            root = identity.root_column
            column = starts[root]
            label = f"{identity.instrument or 'Bez nazwy'} — {identity.spine_type}"
            helper = root not in editable_roots
            if helper:
                label += " · pomocniczy"
            put(0, column, label, muted=helper)
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

    def _merge_target(self) -> tuple[int, int] | None:
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

            fields = rendered[indices[0]].text.split("\t")
            if "*v" not in fields:
                continue

            return (
                issue.line_number,
                issue.identities[0].root_column,
            )

        return None

    def _move_merge(self) -> None:
        self.move_merge_button.setFocus()
        target = self._merge_target()
        if target is None:
            return

        source_line, root_column = target
        moved = False

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

            timing_start = perf_counter()
            proposal = self.draft.move_merge(*target)
            print(
                f"Przeniesienie scalenia: {perf_counter() - timing_start:.3f} s",
                flush=True,
            )
            if proposal is None:
                return

            moved = True
            timing_start = perf_counter()
            self.draft.propose_tokens(tuple(tokens))
            print(
                f"Wpisanie propozycji: {perf_counter() - timing_start:.3f} s",
                flush=True,
            )

        except (ValueError, HumdrumError) as error:
            if moved:
                self.draft.undo()
            self.report.setPlainText(str(error))
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
        self.move_merge_button.setFocus()
        target = self._merge_target()
        if target is None:
            return

        try:
            proposal = self.draft.move_merge(*target)
        except (ValueError, HumdrumError) as error:
            self.report.setPlainText(str(error))
            return

        if proposal is None:
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

    def _toggle_view(self) -> None:
        # Zakończ edycję aktywnego pola przed odczytaniem szkicu.
        self.view_button.setFocus()

        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()
        current_row = self.table.currentRow()
        current_column = self.table.currentColumn()

        self._editing = not self._editing
        self.view_button.setText("Pokaż oryginał" if self._editing else "Edytuj")
        self.move_merge_button.setVisible(self._editing)

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
        if text.startswith("!"):
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
        finally:
            self.table.blockSignals(False)

        self._update_validation()

    def _update_validation(self) -> None:
        result = validate_draft(
            self.draft if self._editing else self.original_draft,
            start_line=self.problem.start_line,
            end_line=self.problem.end_line,
        )
        self.status_indicator.set_state(result.state)
        self.move_merge_button.setEnabled(self._editing and self._merge_target() is not None)
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
        editor = SpineEditor(document)
    except (OSError, UnicodeError, HumdrumError) as error:
        print(f"Nie można otworzyć edytora: {error}")
        return 1

    editor.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
