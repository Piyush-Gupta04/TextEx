"""
ui/main_window.py
=================
Main application window for Smart Text Extractor.

Layout (top to bottom):
    ┌────────────────────────────────────────────┐
    │  Menu Bar                                  │
    ├────────────────────────────────────────────┤
    │  Tool Bar  [Capture][Copy][Clear][Save][…] │
    ├────────────────────────────────────────────┤
    │                                            │
    │  ── OCR RESULT ──────────────────────────  │
    │  QTextEdit  (OCR text, read/write)         │
    │  [⎘ Copy OCR]  [💾 Save OCR]              │
    │                                            │
    │  ── TRANSLATION ─────────────────────────  │
    │  [Language ▾] [🌐 Translate] [⟳ Auto]     │
    │  QTextEdit  (translated text, read-only)   │
    │  [⎘ Copy Translation]  [💾 Save Trans.]   │
    │                                            │
    ├─ Search Bar (hidden until Ctrl+F) ─────────┤
    │  🔍 [__________] [< Prev][Next >] [×] N/N  │
    ├────────────────────────────────────────────┤
    │  Status Bar                │  Stats Label  │
    └────────────────────────────────────────────┘

Signals emitted upward (connected in app.py):
    capture_requested   — toolbar "Capture" clicked
    copy_requested      — toolbar "Copy OCR" clicked  (Ctrl+C)
    history_requested   — toolbar "History" clicked
    settings_requested  — toolbar "Settings" clicked
    gallery_requested   — toolbar "Gallery" clicked
    save_txt_requested  — toolbar/menu "Save OCR TXT"
    export_requested    — File > Export menu
    translate_requested — "Translate" button clicked with (text, lang_code)
    save_translation_requested — "Save Translation" clicked
    copy_translation_requested — "Copy Translation" clicked
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    """
    Primary application window for Smart Text Extractor.

    Provides OCR text display, translation panel, toolbar actions,
    search, and stats.  Business logic lives in core/app.py; this class
    only manages the visual layer and emits signals for everything else.
    """

    WINDOW_TITLE  = "Smart Text Extractor"
    WINDOW_WIDTH  = 1100
    WINDOW_HEIGHT = 800

    # ── Upward signals ──────────────────────────────────────────────────
    capture_requested          = pyqtSignal()
    copy_requested             = pyqtSignal()
    history_requested          = pyqtSignal()
    settings_requested         = pyqtSignal()
    gallery_requested          = pyqtSignal()
    save_txt_requested         = pyqtSignal()
    export_requested           = pyqtSignal(str)   # format: "json" or "csv"
    translate_requested        = pyqtSignal(str, str)  # text, lang_code
    save_translation_requested = pyqtSignal()
    copy_translation_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.WINDOW_TITLE)
        self.resize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)

        self._search_matches: list[int] = []  # character positions
        self._search_index: int = 0

        self._build_ui()
        self._apply_stylesheet()

    # ──────────────────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._init_menu_bar()
        self._init_tool_bar()
        self._init_central()
        self._init_status_bar()

    def _init_menu_bar(self):
        bar = self.menuBar()

        # ── File ──────────────────────────────────────────────────────────
        file_menu: QMenu = bar.addMenu("&File")
        file_menu.addAction(self._action("&Capture Text",    "Ctrl+Alt+X", self.capture_requested))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Save OCR as &TXT...",  "Ctrl+S",     self.save_txt_requested))
        file_menu.addAction(self._action("Save &Translation...",  "",           self.save_translation_requested))
        export_menu = file_menu.addMenu("&Export")
        export_menu.addAction("Export as &JSON...", lambda: self.export_requested.emit("json"))
        export_menu.addAction("Export as &CSV...",  lambda: self.export_requested.emit("csv"))
        file_menu.addSeparator()
        file_menu.addAction(self._action("E&xit", "Alt+F4", self.close))

        # ── Edit ──────────────────────────────────────────────────────────
        edit_menu: QMenu = bar.addMenu("&Edit")
        edit_menu.addAction(self._action("&Copy OCR",       "Ctrl+C", self.copy_requested))
        edit_menu.addAction(self._action("Copy &Translation", "Ctrl+T", self.copy_translation_requested))
        edit_menu.addAction(self._action("Select &All", "Ctrl+A", lambda: self._text_edit.selectAll()))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("C&lear Text", "", self.clear_text))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("&Find...",    "Ctrl+F", self.toggle_search_bar))

        # ── View ──────────────────────────────────────────────────────────
        view_menu: QMenu = bar.addMenu("&View")
        view_menu.addAction(self._action("&History",    "Ctrl+H", self.history_requested))
        view_menu.addAction(self._action("&Gallery",    "Ctrl+G", self.gallery_requested))

        # ── Tools ──────────────────────────────────────────────────────────
        tools_menu: QMenu = bar.addMenu("&Tools")
        tools_menu.addAction(self._action("&Settings",  "Ctrl+,", self.settings_requested))

        # ── Help ──────────────────────────────────────────────────────────
        help_menu: QMenu = bar.addMenu("&Help")
        help_menu.addAction("&About", self._on_about)

    def _action(self, label: str, shortcut: str, slot) -> QAction:
        """Create a QAction and connect it to a slot or signal."""
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        # Connect to either a signal or a callable
        if hasattr(slot, "emit"):      # pyqtSignal
            act.triggered.connect(slot.emit)
        else:
            act.triggered.connect(slot)
        return act

    def _init_tool_bar(self):
        tb: QToolBar = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setObjectName("MainToolBar")

        def tb_btn(label: str, tip: str, slot, shortcut: str = ""):
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setObjectName("ToolButton")
            if shortcut:
                btn.setShortcut(QKeySequence(shortcut))
            btn.clicked.connect(slot if callable(slot) else slot.emit)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            return btn

        tb.addWidget(tb_btn("⌨  Capture",  "Capture screen region (Ctrl+Alt+X)", self.capture_requested))
        tb.addSeparator()
        tb.addWidget(tb_btn("⎘  Copy OCR",  "Copy OCR text to clipboard (Ctrl+C)",     self.copy_requested))
        tb.addWidget(tb_btn("✕  Clear",     "Clear extracted text",                self.clear_text))
        tb.addWidget(tb_btn("💾  Save TXT", "Save OCR text as .txt file (Ctrl+S)",     self.save_txt_requested))
        tb.addSeparator()
        tb.addWidget(tb_btn("🕓  History",  "Open OCR history (Ctrl+H)",           self.history_requested))
        tb.addWidget(tb_btn("🖼  Gallery",  "Screenshot gallery (Ctrl+G)",          self.gallery_requested))
        tb.addSeparator()
        tb.addWidget(tb_btn("⚙  Settings", "Open settings (Ctrl+,)",              self.settings_requested))

        # right-aligned language label
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self._lang_label = QLabel("🌐 English")
        self._lang_label.setObjectName("LangLabel")
        tb.addWidget(self._lang_label)

    def _init_central(self):
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Splitter: OCR pane (top) / Translation pane (bottom) ──────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("MainSplitter")
        splitter.setChildrenCollapsible(False)

        # ── OCR Result Pane ────────────────────────────────────────────────
        ocr_pane = QWidget()
        ocr_pane.setObjectName("OCRPane")
        ocr_layout = QVBoxLayout(ocr_pane)
        ocr_layout.setContentsMargins(0, 0, 0, 0)
        ocr_layout.setSpacing(0)

        # OCR section header
        ocr_header = self._section_header("📄  OCR RESULT")
        ocr_layout.addWidget(ocr_header)

        self._text_edit = QTextEdit()
        self._text_edit.setObjectName("MainTextEdit")
        self._text_edit.setPlaceholderText(
            "Extracted text will appear here…\n\n"
            "Press  Ctrl+Alt+X  to select a screen region and extract text."
        )
        self._text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._text_edit.setAcceptRichText(False)
        ocr_layout.addWidget(self._text_edit, 1)

        # OCR action row
        ocr_actions = self._build_ocr_action_row()
        ocr_layout.addWidget(ocr_actions)

        splitter.addWidget(ocr_pane)

        # ── Translation Pane ───────────────────────────────────────────────
        trans_pane = QWidget()
        trans_pane.setObjectName("TransPane")
        trans_layout = QVBoxLayout(trans_pane)
        trans_layout.setContentsMargins(0, 0, 0, 0)
        trans_layout.setSpacing(0)

        # Translation section header
        trans_header = self._section_header("🌐  TRANSLATION")
        trans_layout.addWidget(trans_header)

        # Translation controls (language picker, Translate button, Auto toggle)
        trans_controls = self._build_translation_controls()
        trans_layout.addWidget(trans_controls)

        # Translation output area
        self._trans_edit = QTextEdit()
        self._trans_edit.setObjectName("TransTextEdit")
        self._trans_edit.setReadOnly(True)
        self._trans_edit.setPlaceholderText(
            "Translated text will appear here…\n\n"
            "Select a target language and click  🌐 Translate."
        )
        self._trans_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        trans_layout.addWidget(self._trans_edit, 1)

        # Translation action row
        trans_actions = self._build_translation_action_row()
        trans_layout.addWidget(trans_actions)

        splitter.addWidget(trans_pane)

        # Give OCR pane 55%, translation pane 45% initial share
        splitter.setStretchFactor(0, 55)
        splitter.setStretchFactor(1, 45)

        main_layout.addWidget(splitter, 1)

        # Search bar (initially hidden)
        self._search_bar = self._build_search_bar()
        main_layout.addWidget(self._search_bar)

        self.setCentralWidget(container)

    # ── Section header helper ──────────────────────────────────────────────

    def _section_header(self, title: str) -> QWidget:
        """Styled section separator bar with a title label."""
        bar = QWidget()
        bar.setObjectName("SectionHeader")
        bar.setFixedHeight(32)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 12, 0)
        lbl = QLabel(title)
        lbl.setObjectName("SectionTitle")
        h.addWidget(lbl)
        h.addStretch()
        return bar

    # ── OCR action row ─────────────────────────────────────────────────────

    def _build_ocr_action_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("ActionRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 5, 10, 5)
        h.setSpacing(8)

        copy_ocr = QPushButton("⎘  Copy OCR Text")
        copy_ocr.setObjectName("ActionButton")
        copy_ocr.setToolTip("Copy OCR text to clipboard")
        copy_ocr.clicked.connect(self.copy_requested.emit)
        h.addWidget(copy_ocr)

        save_ocr = QPushButton("💾  Save OCR Text")
        save_ocr.setObjectName("ActionButton")
        save_ocr.setToolTip("Save OCR text as .txt file")
        save_ocr.clicked.connect(self.save_txt_requested.emit)
        h.addWidget(save_ocr)

        h.addStretch()
        return row

    # ── Translation controls ───────────────────────────────────────────────

    def _build_translation_controls(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TransControls")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(10)

        lang_lbl = QLabel("Target:")
        lang_lbl.setObjectName("ControlLabel")
        h.addWidget(lang_lbl)

        self._lang_combo = QComboBox()
        self._lang_combo.setObjectName("LangCombo")
        self._lang_combo.setToolTip("Select translation target language")
        # Populated by set_translation_languages() from app.py
        h.addWidget(self._lang_combo)

        self._translate_btn = QPushButton("🌐  Translate")
        self._translate_btn.setObjectName("TranslateButton")
        self._translate_btn.setToolTip("Translate OCR text to selected language")
        self._translate_btn.clicked.connect(self._on_translate_clicked)
        h.addWidget(self._translate_btn)

        # Status indicator (shown during translation)
        self._trans_status_lbl = QLabel("")
        self._trans_status_lbl.setObjectName("TransStatusLabel")
        h.addWidget(self._trans_status_lbl)

        h.addStretch()

        self._auto_trans_chk = QCheckBox("Auto Translate")
        self._auto_trans_chk.setObjectName("AutoTransCheck")
        self._auto_trans_chk.setToolTip("Automatically translate after each OCR capture")
        # Value set later via set_auto_translate()
        h.addWidget(self._auto_trans_chk)

        return bar

    # ── Translation action row ─────────────────────────────────────────────

    def _build_translation_action_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("ActionRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 5, 10, 5)
        h.setSpacing(8)

        copy_trans = QPushButton("⎘  Copy Translation")
        copy_trans.setObjectName("ActionButton")
        copy_trans.setToolTip("Copy translated text to clipboard")
        copy_trans.clicked.connect(self.copy_translation_requested.emit)
        h.addWidget(copy_trans)

        save_trans = QPushButton("💾  Save Translation")
        save_trans.setObjectName("ActionButton")
        save_trans.setToolTip("Save translated text as .txt file")
        save_trans.clicked.connect(self.save_translation_requested.emit)
        h.addWidget(save_trans)

        # Detected source language label
        self._detected_lang_lbl = QLabel("")
        self._detected_lang_lbl.setObjectName("DetectedLangLabel")
        h.addWidget(self._detected_lang_lbl)

        h.addStretch()
        return row

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("SearchBar")
        bar.hide()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 4)

        h.addWidget(QLabel("🔍"))

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Find in text...")
        self._search_input.setObjectName("SearchInput")
        self._search_input.textChanged.connect(self._run_search)
        self._search_input.returnPressed.connect(self._next_match)
        h.addWidget(self._search_input)

        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.setObjectName("SearchNav")
        self._prev_btn.clicked.connect(self._prev_match)
        self._prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        h.addWidget(self._prev_btn)

        self._next_btn = QPushButton("Next ▶")
        self._next_btn.setObjectName("SearchNav")
        self._next_btn.clicked.connect(self._next_match)
        self._next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        h.addWidget(self._next_btn)

        self._match_label = QLabel("No results")
        self._match_label.setObjectName("MatchLabel")
        h.addWidget(self._match_label)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("SearchClose")
        close_btn.setFixedWidth(28)
        close_btn.clicked.connect(self.hide_search_bar)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        h.addWidget(close_btn)

        return bar

    def _init_status_bar(self):
        sb: QStatusBar = self.statusBar()
        sb.setObjectName("StatusBar")

        # Left — status message (default Qt behaviour)
        self._status_msg = QLabel("Ready")
        sb.addWidget(self._status_msg, 1)

        # Right — OCR stats
        self._stats_label = QLabel()
        self._stats_label.setObjectName("StatsLabel")
        sb.addPermanentWidget(self._stats_label)

    # ──────────────────────────────────────────────────────────────────────
    # Stylesheet
    # ──────────────────────────────────────────────────────────────────────

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow {
                background: #1e1e2e;
            }
            QMenuBar {
                background: #181825;
                color: #cdd6f4;
                border-bottom: 1px solid #313244;
            }
            QMenuBar::item:selected {
                background: #313244;
                border-radius: 4px;
            }
            QMenu {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
            }
            QMenu::item:selected { background: #313244; }
            QToolBar {
                background: #181825;
                border-bottom: 1px solid #313244;
                spacing: 4px;
                padding: 4px 6px;
            }
            QPushButton#ToolButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
            }
            QPushButton#ToolButton:hover  { background: #45475a; }
            QPushButton#ToolButton:pressed { background: #585b70; }
            QLabel#LangLabel {
                color: #89b4fa;
                font-size: 12px;
                padding-right: 6px;
            }

            /* Section headers */
            QWidget#SectionHeader {
                background: #181825;
                border-top: 1px solid #313244;
                border-bottom: 1px solid #313244;
            }
            QLabel#SectionTitle {
                color: #89b4fa;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
            }

            /* Text areas */
            QTextEdit#MainTextEdit {
                background: #1e1e2e;
                color: #cdd6f4;
                border: none;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 14px;
                padding: 12px;
                selection-background-color: #313244;
            }
            QTextEdit#TransTextEdit {
                background: #12121f;
                color: #a6e3a1;
                border: none;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 14px;
                padding: 12px;
                selection-background-color: #313244;
            }

            /* Splitter */
            QSplitter::handle {
                background: #313244;
                height: 4px;
            }
            QSplitter::handle:hover { background: #45475a; }

            /* Action rows */
            QWidget#ActionRow {
                background: #181825;
                border-top: 1px solid #313244;
            }
            QPushButton#ActionButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 4px 14px;
                font-size: 12px;
            }
            QPushButton#ActionButton:hover  { background: #45475a; }
            QPushButton#ActionButton:pressed { background: #585b70; }

            /* Translation controls */
            QWidget#TransControls {
                background: #1a1a2e;
                border-bottom: 1px solid #313244;
            }
            QLabel#ControlLabel {
                color: #6c7086;
                font-size: 12px;
            }
            QComboBox#LangCombo {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 12px;
                min-width: 160px;
            }
            QComboBox#LangCombo::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox#LangCombo QAbstractItemView {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                selection-background-color: #313244;
            }
            QPushButton#TranslateButton {
                background: #2979ff;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 5px 18px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#TranslateButton:hover  { background: #448aff; }
            QPushButton#TranslateButton:pressed { background: #1565c0; }
            QPushButton#TranslateButton:disabled { background: #313244; color: #6c7086; }
            QLabel#TransStatusLabel {
                color: #f9e2af;
                font-size: 12px;
                font-style: italic;
            }
            QCheckBox#AutoTransCheck {
                color: #cdd6f4;
                font-size: 12px;
                spacing: 6px;
            }
            QCheckBox#AutoTransCheck::indicator {
                width: 16px; height: 16px;
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 3px;
            }
            QCheckBox#AutoTransCheck::indicator:checked {
                background: #2979ff;
                border-color: #2979ff;
            }
            QLabel#DetectedLangLabel {
                color: #6c7086;
                font-size: 11px;
                font-style: italic;
            }

            /* Search bar */
            QWidget#SearchBar {
                background: #181825;
                border-top: 1px solid #313244;
            }
            QLineEdit#SearchInput {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 220px;
            }
            QPushButton#SearchNav {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 3px 10px;
            }
            QPushButton#SearchNav:hover { background: #45475a; }
            QPushButton#SearchClose {
                background: transparent;
                color: #6c7086;
                border: none;
                font-size: 14px;
            }
            QPushButton#SearchClose:hover { color: #f38ba8; }
            QLabel#MatchLabel {
                color: #6c7086;
                font-size: 12px;
                min-width: 80px;
            }

            /* Status bar */
            QStatusBar {
                background: #181825;
                color: #6c7086;
                border-top: 1px solid #313244;
                font-size: 12px;
            }
            QLabel#StatsLabel {
                color: #89b4fa;
                font-size: 12px;
                padding: 0 8px;
            }

            /* Scrollbars */
            QScrollBar:vertical {
                background: #1e1e2e;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: #45475a;
                border-radius: 5px;
            }
            QScrollBar:horizontal {
                background: #1e1e2e;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background: #45475a;
                border-radius: 5px;
            }
        """)

    # ──────────────────────────────────────────────────────────────────────
    # Public API — OCR
    # ──────────────────────────────────────────────────────────────────────

    def set_status(self, message: str, timeout_ms: int = 0) -> None:
        """Update the status bar message."""
        self._status_msg.setText(message)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, lambda: self._status_msg.setText("Ready"))

    def set_stats(self, chars: int, words: int, lines: int, duration: float) -> None:
        """Update the OCR stats label."""
        self._stats_label.setText(
            f"  {chars} chars  |  {words} words  |  {lines} lines  |  {duration:.2f}s"
        )

    def clear_stats(self) -> None:
        """Clear the stats label."""
        self._stats_label.clear()

    def set_text(self, text: str) -> None:
        """Replace editor content with OCR result."""
        self._text_edit.setPlainText(text)
        # Re-run search highlights if search bar is open
        if not self._search_bar.isHidden():
            self._run_search(self._search_input.text())

    def get_text(self) -> str:
        """Return current plain text content (OCR area)."""
        return self._text_edit.toPlainText()

    def clear_text(self) -> None:
        """Clear the OCR text area, translation area, and stats."""
        self._text_edit.clear()
        self._trans_edit.clear()
        self._detected_lang_lbl.setText("")
        self.clear_stats()
        self.set_status("Text cleared")

    def set_language_label(self, label: str) -> None:
        """Update the language indicator in the toolbar."""
        self._lang_label.setText(f"🌐 {label}")

    def set_always_on_top(self, enabled: bool) -> None:
        """Toggle always-on-top window flag."""
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    # ──────────────────────────────────────────────────────────────────────
    # Public API — Translation
    # ──────────────────────────────────────────────────────────────────────

    def set_translation_languages(self, languages: list[str], current: str = "") -> None:
        """
        Populate the language dropdown.

        Args:
            languages: Ordered list of display names.
            current:   Display name to pre-select (uses first entry if empty).
        """
        self._lang_combo.blockSignals(True)
        self._lang_combo.clear()
        for lang in languages:
            self._lang_combo.addItem(lang)
        if current and current in languages:
            self._lang_combo.setCurrentText(current)
        elif languages:
            self._lang_combo.setCurrentIndex(0)
        self._lang_combo.blockSignals(False)

    def get_selected_language(self) -> str:
        """Return the currently selected target language display name."""
        return self._lang_combo.currentText()

    def set_auto_translate(self, enabled: bool) -> None:
        """Set the Auto Translate checkbox state (without triggering the signal)."""
        self._auto_trans_chk.blockSignals(True)
        self._auto_trans_chk.setChecked(enabled)
        self._auto_trans_chk.blockSignals(False)

    def is_auto_translate(self) -> bool:
        """Return whether Auto Translate is checked."""
        return self._auto_trans_chk.isChecked()

    def get_auto_translate_checkbox(self) -> QCheckBox:
        """Return the Auto Translate checkbox widget (for signal connection)."""
        return self._auto_trans_chk

    def get_language_combo(self) -> QComboBox:
        """Return the language combo widget (for signal connection)."""
        return self._lang_combo

    def set_translation_text(self, text: str) -> None:
        """Display translated text in the translation pane."""
        self._trans_edit.setPlainText(text)

    def get_translation_text(self) -> str:
        """Return the current translated text."""
        return self._trans_edit.toPlainText()

    def set_translation_status(self, message: str) -> None:
        """Update the inline translation status label."""
        self._trans_status_lbl.setText(message)

    def set_detected_lang(self, detected: str) -> None:
        """Show the detected source language label."""
        if detected:
            self._detected_lang_lbl.setText(f"Detected: {detected}")
        else:
            self._detected_lang_lbl.setText("")

    def set_translate_button_enabled(self, enabled: bool) -> None:
        """Enable or disable the Translate button."""
        self._translate_btn.setEnabled(enabled)

    # ──────────────────────────────────────────────────────────────────────
    # Translation Internal Handlers
    # ──────────────────────────────────────────────────────────────────────

    def _on_translate_clicked(self) -> None:
        """Emit translate_requested with current OCR text and selected lang code."""
        text = self.get_text()
        lang_name = self.get_selected_language()
        if not text.strip():
            self.set_translation_status("No OCR text to translate.")
            return
        # Convert display name → lang code
        from services.translation_service import get_language_code
        lang_code = get_language_code(lang_name)
        self.translate_requested.emit(text, lang_code)

    # ──────────────────────────────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────────────────────────────

    def toggle_search_bar(self) -> None:
        """Show or hide the search bar."""
        if self._search_bar.isVisible():
            self.hide_search_bar()
        else:
            self._search_bar.show()
            self._search_input.setFocus()
            self._search_input.selectAll()

    def hide_search_bar(self) -> None:
        """Hide search bar and clear all highlights."""
        self._search_bar.hide()
        self._clear_highlights()
        self._search_matches.clear()
        self._search_index = 0

    def _run_search(self, query: str) -> None:
        """Find all occurrences of query and highlight them."""
        self._clear_highlights()
        self._search_matches.clear()
        self._search_index = 0

        if not query:
            self._match_label.setText("No results")
            return

        doc   = self._text_edit.document()
        text  = doc.toPlainText().lower()
        q_low = query.lower()
        pos   = 0
        while True:
            idx = text.find(q_low, pos)
            if idx == -1:
                break
            self._search_matches.append(idx)
            pos = idx + 1

        if not self._search_matches:
            self._match_label.setText("No results")
            return

        self._apply_highlights(query)
        self._jump_to(0)

    def _apply_highlights(self, query: str) -> None:
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#f9e2af"))    # yellow highlight
        fmt.setForeground(QColor("#1e1e2e"))

        cursor = self._text_edit.textCursor()
        cursor.beginEditBlock()
        extras = []
        for pos in self._search_matches:
            c = QTextCursor(self._text_edit.document())
            c.setPosition(pos)
            c.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                len(query),
            )
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            sel.cursor = c
            extras.append(sel)
        cursor.endEditBlock()
        self._text_edit.setExtraSelections(extras)

    def _clear_highlights(self) -> None:
        self._text_edit.setExtraSelections([])

    def _next_match(self) -> None:
        if not self._search_matches:
            return
        self._search_index = (self._search_index + 1) % len(self._search_matches)
        self._jump_to(self._search_index)

    def _prev_match(self) -> None:
        if not self._search_matches:
            return
        self._search_index = (self._search_index - 1) % len(self._search_matches)
        self._jump_to(self._search_index)

    def _jump_to(self, idx: int) -> None:
        pos = self._search_matches[idx]
        cursor = QTextCursor(self._text_edit.document())
        cursor.setPosition(pos)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.ensureCursorVisible()
        total = len(self._search_matches)
        self._match_label.setText(f"{idx + 1} / {total}")

    # ──────────────────────────────────────────────────────────────────────
    # Key events
    # ──────────────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._search_bar.isVisible():
            self.hide_search_bar()
        else:
            super().keyPressEvent(event)

    # ──────────────────────────────────────────────────────────────────────
    # Window events
    # ──────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """
        Intercepted by app.py to minimise-to-tray when that setting is on.
        app.py calls event.ignore() + self.hide() if appropriate.
        """
        super().closeEvent(event)

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _on_about(self):
        QMessageBox.about(
            self,
            "About Smart Text Extractor",
            "<b>Smart Text Extractor v2.0</b><br><br>"
            "PaddleOCR-powered screen text extraction with translation.<br><br>"
            "• Press <b>Ctrl+Alt+X</b> to capture a screen region.<br>"
            "• Press <b>Ctrl+F</b> to search extracted text.<br>"
            "• Press <b>Ctrl+H</b> to view extraction history.<br>"
            "• Use the 🌐 Translate panel to translate OCR output.",
        )
