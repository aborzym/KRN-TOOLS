SPINEWORKS_STYLE = """
QMainWindow, QWidget { background: #101713; color: #e7f4eb; }
QToolBar { background: #152019; border: 0; padding: 7px; spacing: 8px; }
QToolButton {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #304737,
        stop: 0.5 #263a2d,
        stop: 1 #1b2b21
    );
    color: #e7f4eb;
    padding: 7px 12px;
    border: 1px solid #3b5142;
    border-top-color: #526d5b;
    border-left-color: #49634f;
    border-right-color: #15251b;
    border-bottom-color: #15251b;
    border-radius: 6px;
    font-weight: 600;
}
QToolButton:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #3b5743,
        stop: 0.5 #2e4736,
        stop: 1 #22382a
    );
}
QToolButton:pressed {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #19291f,
        stop: 1 #2a4031
    );
    border-top-color: #15251b;
    border-left-color: #15251b;
    border-right-color: #49634f;
    border-bottom-color: #49634f;
}
QToolButton:disabled {
    background: #202c24;
    color: #718078;
    border: 1px solid #304536;
}

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
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #27a96f,
        stop: 0.45 #168653,
        stop: 1 #10613c
    );
    color: white;
    padding: 10px 18px;
    border: 1px solid #278958;
    border-top: 1px solid #65c997;
    border-bottom: 3px solid #09472b;
    border-radius: 7px;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #35bd80,
        stop: 0.45 #1b9a61,
        stop: 1 #147448
    );
}
QPushButton#primaryButton:pressed {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #105e3a,
        stop: 1 #168653
    );
    border-top: 2px solid #09472b;
    border-bottom: 1px solid #278958;
    padding-top: 11px;
    padding-bottom: 10px;
}
QPushButton#primaryButton:disabled {
    background: #26342b;
    color: #718078;
    border: 1px solid #304536;
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
