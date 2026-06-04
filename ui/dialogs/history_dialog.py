"""
ui/dialogs/history_dialog.py
============================
OCR History viewer dialog for Smart Text Extractor.

Shows all past OCR extractions from the SQLite history database.
The user can:
    - View a list sorted newest-first (timestamp + preview + word count)
    - Double-click an entry to load its text into the main editor
    - Right-click to delete an entry
    - "Clear All" to wipe the entire history
    - "Export JSON" / "Export CSV" to save all records

Usage:
    dlg = HistoryDialog(history_mgr, parent=main_window)
    dlg.exec()
    if dlg.selected_text:
        main_window.set_text(dlg.selected_text)
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.history import HistoryManager
from services.export_service import ExportService


class HistoryDialog(QDialog):
    """
    Modal dialog showing all stored OCR extractions.

    Attributes:
        selected_text: Set to the text of a double-clicked entry so the
                       caller can load it into the editor.
    """

    def __init__(self, history: HistoryManager, parent=None) -> None:
        super().__init__(parent)
        self._history = history
        self.selected_text: str = ""

        self.setWindowTitle("OCR History")
        self.resize(820, 560)
        self._build_ui()
        self._apply_style()
        self._load_records()

    # ──────────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("📋  OCR History")
        title.setObjectName("DialogTitle")
        header.addWidget(title)
        header.addStretch()
        self._count_label = QLabel("")
        self._count_label.setObjectName("CountLabel")
        header.addWidget(self._count_label)
        root.addLayout(header)

        # Splitter: list on left, preview on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # List
        self._list = QListWidget()
        self._list.setObjectName("HistoryList")
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        splitter.addWidget(self._list)

        # Preview
        preview_container = QVBoxLayout()
        self._preview_header = QLabel("Preview")
        self._preview_header.setObjectName("PreviewHeader")
        self._preview = QTextEdit()
        self._preview.setObjectName("PreviewPane")
        self._preview.setReadOnly(True)
        preview_wrap = QWidget()
        preview_wrap.setLayout(preview_container)
        preview_container.addWidget(self._preview_header)
        preview_container.addWidget(self._preview)
        splitter.addWidget(preview_wrap)
        splitter.setSizes([300, 500])

        root.addWidget(splitter, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()

        self._load_btn = QPushButton("Load into Editor")
        self._load_btn.setObjectName("PrimaryButton")
        self._load_btn.clicked.connect(self._on_load)
        self._load_btn.setEnabled(False)
        btn_row.addWidget(self._load_btn)

        btn_row.addStretch()

        export_json_btn = QPushButton("Export JSON")
        export_json_btn.clicked.connect(lambda: self._export("json"))
        btn_row.addWidget(export_json_btn)

        export_csv_btn = QPushButton("Export CSV")
        export_csv_btn.clicked.connect(lambda: self._export("csv"))
        btn_row.addWidget(export_csv_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.setObjectName("DangerButton")
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QLabel#DialogTitle { font-size: 15px; font-weight: bold; color: #89b4fa; }
            QLabel#CountLabel  { font-size: 12px; color: #6c7086; }
            QListWidget#HistoryList {
                background: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 6px;
                alternate-background-color: #1e1e2e;
                font-size: 13px;
            }
            QListWidget#HistoryList::item:selected { background: #313244; }
            QLabel#PreviewHeader { color: #6c7086; font-size: 12px; padding: 4px; }
            QTextEdit#PreviewPane {
                background: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 13px;
                padding: 8px;
            }
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 5px 14px;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton#PrimaryButton {
                background: #2979ff;
                color: white;
                border-color: #2979ff;
            }
            QPushButton#PrimaryButton:hover { background: #448aff; }
            QPushButton#DangerButton  { color: #f38ba8; }
            QSplitter::handle { background: #313244; width: 1px; }
            QScrollBar:vertical { background: #1e1e2e; width: 10px; }
            QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; }
        """)

    # ──────────────────────────────────────────────────────────────────────
    # Data loading
    # ──────────────────────────────────────────────────────────────────────

    def _load_records(self) -> None:
        self._list.clear()
        records = self._history.get_all()
        self._count_label.setText(f"{len(records)} entries")

        for rec in records:
            preview = rec["text"].replace("\n", " ")[:70]
            if len(rec["text"]) > 70:
                preview += "…"
            label = (
                f"[{rec['timestamp']}]  {rec['words']}w  |  "
                f"{rec['language'].upper()}  |  {preview}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, rec)
            self._list.addItem(item)

    # ──────────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────────

    def _on_selection_changed(self, current: QListWidgetItem, _) -> None:
        if current is None:
            self._preview.clear()
            self._load_btn.setEnabled(False)
            return
        rec = current.data(Qt.ItemDataRole.UserRole)
        self._preview.setPlainText(rec["text"])
        stats = (
            f"Timestamp: {rec['timestamp']}    "
            f"Words: {rec['words']}    "
            f"Chars: {rec['chars']}    "
            f"Language: {rec['language'].upper()}    "
            f"Duration: {rec['duration']:.2f}s"
        )
        self._preview_header.setText(stats)
        self._load_btn.setEnabled(True)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        rec = item.data(Qt.ItemDataRole.UserRole)
        self.selected_text = rec["text"]
        self.accept()

    def _on_load(self) -> None:
        item = self._list.currentItem()
        if item:
            rec = item.data(Qt.ItemDataRole.UserRole)
            self.selected_text = rec["text"]
            self.accept()

    def _show_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #1e1e2e; color: #cdd6f4; border: 1px solid #313244; }"
                           "QMenu::item:selected { background: #313244; }")
        del_act = menu.addAction("🗑  Delete Entry")
        action = menu.exec(self._list.mapToGlobal(pos))
        if action == del_act:
            rec = item.data(Qt.ItemDataRole.UserRole)
            self._history.delete(rec["id"])
            self._load_records()

    def _clear_all(self) -> None:
        reply = QMessageBox.question(
            self, "Clear History",
            "Delete ALL history entries? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self._load_records()
            self._preview.clear()

    def _export(self, fmt: str) -> None:
        records = self._history.get_all()
        if not records:
            QMessageBox.information(self, "Export", "No history to export.")
            return
        ext = fmt.upper()
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export as {ext}", f"history.{fmt}",
            f"{ext} Files (*.{fmt})",
        )
        if not path:
            return
        try:
            if fmt == "json":
                ExportService.to_json(records, path)
            else:
                ExportService.to_csv(records, path)
            QMessageBox.information(self, "Export", f"Exported to:\n{path}")
        except RuntimeError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))



