SPINEWORKS_STYLE = """
QMainWindow, QWidget { background: #101713; color: #e7f4eb; }
QToolBar { background: #152019; border: 0; padding: 7px; spacing: 8px; }
QToolButton { padding: 7px 12px; border-radius: 6px; }
QToolButton:hover { background: #24372a; }

QLabel#fileLabel { color: #b7cabe; font-size: 14px; padding: 4px; }
QWidget#decorationRow { background: transparent; }
QLabel#decorationLabel { color: #b7cabe; font-weight: 600; }

QLineEdit#systemDecorationInput {
    background: #18271e; color: #d8f8e4;
    border: 1px solid #304536; border-radius: 6px; padding: 7px 9px;
}
QLineEdit#systemDecorationInput:focus { border-color: #35a36d; }
QLineEdit#systemDecorationInput:disabled { color: #718078; }

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
QPlainTextEdit {
    background: #121c16; color: #b7cabe;
    border: 1px solid #304536; border-radius: 6px;
    selection-background-color: #177245;
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
QPushButton#dangerButton:disabled {
    background: #38292c; color: #8b7074; border-color: #594044;
}

QWidget#instrumentEditorActive { background: #183d29; }
QWidget#instrumentEditorKernInactive { background: transparent; }
QLabel#fixedPrefix {
    background: transparent; color: #63d297; font-weight: 700;
}
QWidget#instrumentEditorKernInactive QLabel#fixedPrefix {
    color: #d8f8e4; font-weight: 400;
}
QLineEdit {
    background: transparent; color: #d8f8e4; border: 0;
    selection-background-color: #177245; padding: 3px 1px;
}
QLineEdit:disabled { color: #d8f8e4; }
QSpinBox:disabled, QComboBox:disabled {
    color: #718078; background: #18211b; border-color: #26372c;
}
QCheckBox:disabled { color: #718078; }
QStatusBar { background: #111a14; color: #9fb2a5; }
QLabel#versionLabel {
    background: transparent; color: #718078;
    font-size: 11px; padding: 0 8px;
}
"""
