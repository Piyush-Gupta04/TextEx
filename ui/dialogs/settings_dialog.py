"""
ui/dialogs/settings_dialog.py
==============================
Settings dialog for Smart Text Extractor.

Four tabs:
    General  — window behaviour
    OCR      — language, confidence threshold
    Hotkey   — capture shortcut
    Storage  — history limit

Changes take effect immediately when the user clicks OK.
Cancel reverts all pending changes (reads back from QSettings).

Usage:
    dlg = SettingsDialog(settings, parent=main_window)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        apply_settings(settings)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.settings import Settings
from services.translation_service import SUPPORTED_LANGUAGES, DEFAULT_TARGET_LANG



class SettingsDialog(QDialog):
    """
    Application settings dialog with tabbed layout.

    Signals:
        hotkey_changed(str):      Emitted when a new hotkey is accepted.
        always_on_top_changed(bool): Emitted when the window-flag setting changes.

    Note: language_changed signal removed in v2.0 — OCR now automatically
    detects and handles all scripts via the per-region best-engine strategy.
    The 'Auto Detect' mode is always active and cannot be disabled.
    """

    hotkey_changed        = pyqtSignal(str)
    always_on_top_changed = pyqtSignal(bool)
    auto_translate_changed = pyqtSignal(bool)

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._s = settings
        # Snapshot to restore on Cancel
        self._snapshot: dict = {
            "start_minimized":          settings.start_minimized,
            "minimize_to_tray":         settings.minimize_to_tray,
            "always_on_top":            settings.always_on_top,
            "auto_clipboard":           settings.auto_clipboard,
            "confidence_threshold":     settings.confidence_threshold,
            "hotkey":                   settings.hotkey,
            "history_limit":            settings.history_limit,
            "keep_screenshots":         settings.keep_screenshots,
            "auto_translate":           settings.auto_translate,
            "translation_target_lang":  settings.translation_target_lang,
            "show_result_overlay":      settings.show_result_overlay,
            "overlay_autohide_secs":    settings.overlay_autohide_secs,
        }

        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self.setMinimumHeight(380)
        self._build_ui()
        self._apply_style()

    # ──────────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        tabs = QTabWidget()
        tabs.setObjectName("SettingsTabs")
        tabs.addTab(self._tab_general(),     "General")
        tabs.addTab(self._tab_ocr(),         "OCR")
        tabs.addTab(self._tab_hotkey(),      "Hotkey")
        tabs.addTab(self._tab_storage(),     "Storage")
        tabs.addTab(self._tab_translation(), "Translation")
        tabs.addTab(self._tab_overlay(),     "Overlay")
        root.addWidget(tabs, 1)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self._on_cancel)
        root.addWidget(buttons)

    # ── Tab: General ──────────────────────────────────────────────────────

    def _tab_general(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        grp = QGroupBox("Window Behaviour")
        form = QFormLayout(grp)
        form.setVerticalSpacing(10)

        self._chk_start_min   = QCheckBox("Start minimized to tray")
        self._chk_start_min.setChecked(self._s.start_minimized)
        form.addRow(self._chk_start_min)

        self._chk_min_tray    = QCheckBox("Minimize to tray on close")
        self._chk_min_tray.setChecked(self._s.minimize_to_tray)
        form.addRow(self._chk_min_tray)

        self._chk_always_top  = QCheckBox("Always on top")
        self._chk_always_top.setChecked(self._s.always_on_top)
        form.addRow(self._chk_always_top)

        self._chk_auto_clip   = QCheckBox("Auto-copy OCR result to clipboard")
        self._chk_auto_clip.setChecked(self._s.auto_clipboard)
        form.addRow(self._chk_auto_clip)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ── Tab: OCR ──────────────────────────────────────────────────────────

    def _tab_ocr(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Auto Detect mode description ──────────────────────────────────
        grp_mode = QGroupBox("Recognition Mode")
        mode_layout = QVBoxLayout(grp_mode)
        mode_layout.setSpacing(8)

        mode_label = QLabel("<b>✦ Auto Detect (always on)</b>")
        mode_label.setObjectName("AutoDetectLabel")
        mode_layout.addWidget(mode_label)

        desc = QLabel(
            "All 7 language engines run on every capture.  "
            "For each detected text region, the engine with the highest "
            "confidence score wins — giving every script its specialist model:"
        )
        desc.setWordWrap(True)
        desc.setObjectName("NoteLabel")
        mode_layout.addWidget(desc)

        engines_info = QLabel(
            "<table style='margin-left:8px; line-height:1.6;'>"
            "<tr><td>🔤</td><td><b>en</b></td>"
            "<td>Latin — English, French, Spanish, German</td></tr>"
            "<tr><td>🀄</td><td><b>ch</b></td>"
            "<td>Chinese (simplified + traditional)</td></tr>"
            "<tr><td>🌙</td><td><b>ar</b></td>"
            "<td>Arabic / Urdu</td></tr>"
            "<tr><td>🇮🇳</td><td><b>hi</b></td>"
            "<td>Hindi / Devanagari</td></tr>"
            "<tr><td>🇷🇺</td><td><b>ru</b></td>"
            "<td>Russian / Cyrillic</td></tr>"
            "<tr><td>🗾</td><td><b>japan</b></td>"
            "<td>Japanese (Hiragana · Katakana · Kanji)</td></tr>"
            "<tr><td>🇰🇷</td><td><b>korean</b></td>"
            "<td>Korean (Hangul)</td></tr>"
            "</table>"
        )
        engines_info.setObjectName("NoteLabel")
        engines_info.setWordWrap(False)
        mode_layout.addWidget(engines_info)

        layout.addWidget(grp_mode)

        # ── Confidence threshold ───────────────────────────────────────────
        grp_conf = QGroupBox("Recognition Threshold")
        form = QFormLayout(grp_conf)
        form.setVerticalSpacing(12)

        thresh_row = QHBoxLayout()
        self._conf_slider = QSlider(Qt.Orientation.Horizontal)
        self._conf_slider.setRange(0, 100)
        self._conf_slider.setValue(int(self._s.confidence_threshold * 100))
        self._conf_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._conf_slider.setTickInterval(10)
        self._conf_val_label = QLabel(f"{self._s.confidence_threshold:.2f}")
        self._conf_slider.valueChanged.connect(
            lambda v: self._conf_val_label.setText(f"{v/100:.2f}")
        )
        thresh_row.addWidget(self._conf_slider)
        thresh_row.addWidget(self._conf_val_label)
        form.addRow("Min confidence:", thresh_row)

        conf_note = QLabel(
            "<i>Regions whose recognition confidence falls below this threshold "
            "are discarded.  Lowering the value includes more (possibly noisy) text; "
            "raising it keeps only high-certainty results.</i>"
        )
        conf_note.setObjectName("NoteLabel")
        conf_note.setWordWrap(True)
        form.addRow(conf_note)

        layout.addWidget(grp_conf)
        layout.addStretch()
        return w

    # ── Tab: Hotkey ───────────────────────────────────────────────────────

    def _tab_hotkey(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        grp = QGroupBox("Capture Hotkey")
        form = QFormLayout(grp)
        form.setVerticalSpacing(12)

        row = QHBoxLayout()
        self._hotkey_edit = QLineEdit(self._s.hotkey)
        self._hotkey_edit.setPlaceholderText("e.g. ctrl+alt+x")
        row.addWidget(self._hotkey_edit)

        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(60)
        reset_btn.clicked.connect(lambda: self._hotkey_edit.setText("ctrl+alt+x"))
        row.addWidget(reset_btn)

        form.addRow("Shortcut combination:", row)

        note = QLabel(
            "<i>Use keyboard library syntax: ctrl+alt+x, ctrl+shift+s, etc.<br>"
            "Changes apply immediately without restart.</i>"
        )
        note.setObjectName("NoteLabel")
        note.setWordWrap(True)
        form.addRow(note)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ── Tab: Storage ──────────────────────────────────────────────────────

    def _tab_storage(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        grp = QGroupBox("History & Screenshots")
        form = QFormLayout(grp)
        form.setVerticalSpacing(12)

        self._hist_spin = QSpinBox()
        self._hist_spin.setRange(10, 10000)
        self._hist_spin.setSuffix("  entries")
        self._hist_spin.setValue(self._s.history_limit)
        form.addRow("History limit:", self._hist_spin)

        self._chk_keep_shots = QCheckBox("Save each capture as a screenshot file")
        self._chk_keep_shots.setChecked(self._s.keep_screenshots)
        form.addRow(self._chk_keep_shots)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ── Tab: Translation ───────────────────────────────────────────

    def _tab_translation(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        grp = QGroupBox("Translation Settings")
        form = QFormLayout(grp)
        form.setVerticalSpacing(14)

        # Auto Translate toggle
        self._chk_auto_trans = QCheckBox("Auto Translate after OCR")
        self._chk_auto_trans.setChecked(self._s.auto_translate)
        self._chk_auto_trans.setToolTip(
            "When checked, translation runs automatically after every OCR capture."
        )
        form.addRow(self._chk_auto_trans)

        auto_note = QLabel(
            "<i>When enabled, the selected target language is applied "
            "automatically every time text is extracted.</i>"
        )
        auto_note.setObjectName("NoteLabel")
        auto_note.setWordWrap(True)
        form.addRow(auto_note)

        # Target language picker
        lang_label = QLabel("Default target language:")
        self._trans_lang_combo = QComboBox()
        self._trans_lang_combo.setObjectName("TransLangCombo")
        for lang in SUPPORTED_LANGUAGES.keys():
            self._trans_lang_combo.addItem(lang)
        current = self._s.translation_target_lang or DEFAULT_TARGET_LANG
        if current in SUPPORTED_LANGUAGES:
            self._trans_lang_combo.setCurrentText(current)
        form.addRow(lang_label, self._trans_lang_combo)

        engine_note = QLabel(
            "<i>Translation uses <b>deep-translator</b> (Google Translate) "
            "via an internet connection. Automatic source-language detection "
            "is used when possible.</i>"
        )
        engine_note.setObjectName("NoteLabel")
        engine_note.setWordWrap(True)
        form.addRow(engine_note)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ── Tab: Overlay ───────────────────────────────────────────

    def _tab_overlay(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        grp = QGroupBox("Result Overlay")
        form = QFormLayout(grp)
        form.setVerticalSpacing(14)

        self._chk_show_overlay = QCheckBox("Show floating result overlay after OCR")
        self._chk_show_overlay.setChecked(self._s.show_result_overlay)
        self._chk_show_overlay.setToolTip(
            "A small window appears near the captured region showing OCR "
            "and translation results."
        )
        form.addRow(self._chk_show_overlay)

        # Auto-hide dropdown
        autohide_lbl = QLabel("Auto-hide after:")
        self._autohide_combo = QComboBox()
        self._autohide_combo.setObjectName("AutohideCombo")
        for label, secs in [
            ("Disabled",   0),
            ("3 seconds",  3),
            ("5 seconds",  5),
            ("10 seconds", 10),
            ("15 seconds", 15),
            ("30 seconds", 30),
        ]:
            self._autohide_combo.addItem(label, secs)
        # Select current value
        current_secs = self._s.overlay_autohide_secs
        for i in range(self._autohide_combo.count()):
            if self._autohide_combo.itemData(i) == current_secs:
                self._autohide_combo.setCurrentIndex(i)
                break
        form.addRow(autohide_lbl, self._autohide_combo)

        overlay_note = QLabel(
            "<i>The overlay appears near the captured screen region and "
            "lets you copy OCR or translation text without opening the main window. "
            "Mouse hover pauses the auto-hide timer.</i>"
        )
        overlay_note.setObjectName("NoteLabel")
        overlay_note.setWordWrap(True)
        form.addRow(overlay_note)

        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QTabWidget::pane {
                background: #1e1e2e;
                border: 1px solid #313244;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #181825;
                color: #6c7086;
                padding: 8px 18px;
                border: 1px solid #313244;
                border-bottom: none;
                border-radius: 4px 4px 0 0;
            }
            QTabBar::tab:selected { background: #1e1e2e; color: #cdd6f4; }
            QGroupBox {
                color: #89b4fa;
                border: 1px solid #313244;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 10px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; }
            QCheckBox { color: #cdd6f4; spacing: 8px; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background: #2979ff;
                border-color: #2979ff;
            }
            QLineEdit, QSpinBox {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QSlider::groove:horizontal {
                background: #313244;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #2979ff;
                width: 16px; height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal { background: #2979ff; border-radius: 3px; }
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 5px 14px;
            }
            QPushButton:hover { background: #45475a; }
            QDialogButtonBox QPushButton { min-width: 80px; }
            QLabel#NoteLabel      { color: #6c7086; font-size: 12px; }
            QLabel#AutoDetectLabel {
                color: #a6e3a1;
                font-size: 13px;
                padding: 2px 0;
            }
            QComboBox#TransLangCombo {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 160px;
            }
            QComboBox#TransLangCombo QAbstractItemView {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                selection-background-color: #313244;
            }
            QComboBox#AutohideCombo {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox#AutohideCombo QAbstractItemView {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                selection-background-color: #313244;
            }
        """)


    # ──────────────────────────────────────────────────────────────────────
    # Accept / Cancel
    # ──────────────────────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        old_hotkey     = self._s.hotkey
        old_always_top = self._s.always_on_top
        old_auto_trans = self._s.auto_translate

        # Persist all settings
        self._s.start_minimized          = self._chk_start_min.isChecked()
        self._s.minimize_to_tray         = self._chk_min_tray.isChecked()
        self._s.always_on_top            = self._chk_always_top.isChecked()
        self._s.auto_clipboard           = self._chk_auto_clip.isChecked()
        self._s.confidence_threshold     = self._conf_slider.value() / 100.0
        self._s.hotkey                   = self._hotkey_edit.text().strip().lower()
        self._s.history_limit            = self._hist_spin.value()
        self._s.keep_screenshots         = self._chk_keep_shots.isChecked()
        self._s.auto_translate           = self._chk_auto_trans.isChecked()
        self._s.translation_target_lang  = self._trans_lang_combo.currentText()
        self._s.show_result_overlay      = self._chk_show_overlay.isChecked()
        self._s.overlay_autohide_secs    = self._autohide_combo.currentData()
        self._s.sync()

        # Emit change signals only when values actually changed
        new_hotkey = self._s.hotkey
        if new_hotkey != old_hotkey:
            self.hotkey_changed.emit(new_hotkey)

        if self._s.always_on_top != old_always_top:
            self.always_on_top_changed.emit(self._s.always_on_top)

        if self._s.auto_translate != old_auto_trans:
            self.auto_translate_changed.emit(self._s.auto_translate)

        self.accept()

    def _on_cancel(self) -> None:
        """Revert settings to the snapshot taken on dialog open."""
        for k, v in self._snapshot.items():
            setattr(self._s, k, v)
        self._s.sync()
        self.reject()
