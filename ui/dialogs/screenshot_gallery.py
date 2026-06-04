"""
ui/dialogs/screenshot_gallery.py
=================================
Screenshot gallery dialog for Smart Text Extractor.

Shows all PNG files saved in the captures/ directory (newest first).
The user can:
    - Browse a list of timestamped screenshots
    - Preview the selected screenshot (scaled to fit)
    - Delete individual screenshots
    - Open the captures folder in Windows Explorer

Usage:
    dlg = ScreenshotGallery(capture_service, parent=main_window)
    dlg.exec()
"""

from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from services.capture_service import CaptureService


class ScreenshotGallery(QDialog):
    """Gallery of saved screen captures."""

    def __init__(self, capture_svc: CaptureService, parent=None) -> None:
        super().__init__(parent)
        self._svc = capture_svc
        self.setWindowTitle("Screenshot Gallery")
        self.resize(900, 600)
        self._build_ui()
        self._apply_style()
        self._refresh()

    # ──────────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Title row
        header = QHBoxLayout()
        title = QLabel("🖼  Screenshot Gallery")
        title.setObjectName("DialogTitle")
        header.addWidget(title)
        header.addStretch()
        self._count_label = QLabel("")
        self._count_label.setObjectName("CountLabel")
        header.addWidget(self._count_label)
        root.addLayout(header)

        # Splitter: list on left, preview on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # File list
        self._list = QListWidget()
        self._list.setObjectName("GalleryList")
        self._list.currentItemChanged.connect(self._on_selection)
        splitter.addWidget(self._list)

        # Preview
        preview_wrap = QWidget()
        pv_layout = QVBoxLayout(preview_wrap)
        pv_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = QLabel("Select a screenshot to preview")
        self._preview.setObjectName("PreviewLabel")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(400, 300)
        pv_layout.addWidget(self._preview, 1)
        self._path_label = QLabel("")
        self._path_label.setObjectName("PathLabel")
        self._path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pv_layout.addWidget(self._path_label)
        splitter.addWidget(preview_wrap)
        splitter.setSizes([220, 680])

        root.addWidget(splitter, 1)

        # Buttons
        btn_row = QHBoxLayout()

        self._del_btn = QPushButton("🗑  Delete Selected")
        self._del_btn.setObjectName("DangerButton")
        self._del_btn.clicked.connect(self._delete_selected)
        self._del_btn.setEnabled(False)
        btn_row.addWidget(self._del_btn)

        open_folder_btn = QPushButton("📂  Open Folder")
        open_folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_folder_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QLabel#DialogTitle { font-size: 15px; font-weight: bold; color: #89b4fa; }
            QLabel#CountLabel  { font-size: 12px; color: #6c7086; }
            QListWidget#GalleryList {
                background: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 6px;
                font-size: 12px;
            }
            QListWidget#GalleryList::item:selected { background: #313244; }
            QLabel#PreviewLabel {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 6px;
                color: #6c7086;
                font-size: 13px;
            }
            QLabel#PathLabel { color: #6c7086; font-size: 11px; padding: 4px; }
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 5px 14px;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton#DangerButton { color: #f38ba8; }
            QSplitter::handle { background: #313244; width: 1px; }
            QScrollBar:vertical { background: #1e1e2e; width: 10px; }
            QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; }
        """)

    # ──────────────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._list.clear()
        paths = self._svc.list_screenshots()
        self._count_label.setText(f"{len(paths)} screenshot(s)")
        for path in paths:
            filename = os.path.basename(path)
            item = QListWidgetItem(filename)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self._list.addItem(item)

    # ──────────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────────

    def _on_selection(self, current: QListWidgetItem, _) -> None:
        if current is None:
            self._preview.setText("Select a screenshot to preview")
            self._path_label.clear()
            self._del_btn.setEnabled(False)
            return

        path = current.data(Qt.ItemDataRole.UserRole)
        self._path_label.setText(path)
        self._del_btn.setEnabled(True)

        px = QPixmap(path)
        if px.isNull():
            self._preview.setText("Cannot load image")
            return
        scaled = px.scaled(
            self._preview.width() - 20,
            self._preview.height() - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(scaled)

    def _delete_selected(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete Screenshot",
            f"Delete {os.path.basename(path)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._svc.delete_screenshot(path)
            self._preview.setText("Select a screenshot to preview")
            self._path_label.clear()
            self._del_btn.setEnabled(False)
            self._refresh()

    def _open_folder(self) -> None:
        folder = os.path.abspath(CaptureService.CAPTURE_DIR)
        os.makedirs(folder, exist_ok=True)
        subprocess.Popen(["explorer", folder])
