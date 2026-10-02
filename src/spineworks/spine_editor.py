import sys
from pathlib import Path

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spineworks.humdrum import HumdrumDocument, HumdrumError
from spineworks.spine_validation import (
    build_fragment_rows,
    build_measure_view,
    find_split_issues,
    group_split_issues,
    trace_spines,
)
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
    def __init__(
        self,
        spacers: set[int],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.spacers = spacers

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
        layout.addWidget(self.title_label)

        self.table = QTableWidget(self)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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

        self.title_label.setText(f"Takt {self.problem.measure} · zakres 1 z {len(problems)}")
        self._show_rows()
        self.report.setPlainText(
            "\n".join(
                f"Linia {issue.line_number}: {issue.message}" for issue in self.problem.issues
            )
        )

    def _show_rows(self) -> None:
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
                (sum(cell.identity.root_column == root for cell in row.cells) for row in self.rows),
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
        self.table.setRowCount(len(self.rows) + 1)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setShowGrid(False)
        self.table.setItemDelegate(CellGridDelegate(spacers, self.table))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        def put(
            row: int,
            column: int,
            text: str,
            *,
            editable: bool = False,
            muted: bool = False,
        ) -> None:
            item = QTableWidgetItem(text)
            if column < 2:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

            if editable:
                item.setBackground(QColor("#202b40"))

            if text.startswith("!"):
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

        for table_row, row in enumerate(self.rows, start=1):
            put(table_row, 0, str(row.source_line))
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
                )
                offsets[root] = offset + 1

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(4)

        for column in spacers:
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Fixed,
            )
            self.table.setColumnWidth(column, 4)

            for row in range(self.table.rowCount()):
                # Komentarz globalny może obejmować kilka grup.
                if self.table.columnSpan(row, 3) > 1 and column > 3:
                    continue

                spacer = QWidget(self.table)
                spacer.setStyleSheet("background: #101713;")
                self.table.setCellWidget(row, column, spacer)

        self.table.setHorizontalHeader(SpacerHeader(spacers, self.table))
        header = self.table.horizontalHeader()
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
        header.setMinimumSectionSize(4)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in spacers:
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Fixed,
            )
            self.table.setColumnWidth(column, 4)
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
