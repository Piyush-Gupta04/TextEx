"""
services/export_service.py
==========================
Export OCR results as TXT, JSON, or CSV for Smart Text Extractor.

All methods are static and accept the data plus a destination path.
They raise RuntimeError on write failure so callers can show user-facing
error messages without catching generic exceptions.

Usage:
    ExportService.to_txt("Hello World", "/path/to/file.txt")
    ExportService.to_json(records, "/path/to/file.json")
    ExportService.to_csv(records, "/path/to/file.csv")
"""

from __future__ import annotations

import csv
import json
import os
from typing import List


class ExportService:
    """Static methods for exporting OCR data to various file formats."""

    # ── TXT ───────────────────────────────────────────────────────────────

    @staticmethod
    def to_txt(text: str, path: str) -> None:
        """
        Save plain text to a .txt file (UTF-8).

        Args:
            text: The text to save.
            path: Absolute or relative destination path.

        Raises:
            RuntimeError: On any I/O failure.
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:
            raise RuntimeError(f"TXT export failed: {exc}") from exc

    # ── JSON ──────────────────────────────────────────────────────────────

    @staticmethod
    def to_json(records: List[dict], path: str) -> None:
        """
        Save a list of history records to a JSON file (UTF-8, indented).

        Each record dict may contain: id, timestamp, text, words,
        chars, language, duration.

        Args:
            records: List of record dicts from HistoryManager.get_all().
            path:    Destination .json path.

        Raises:
            RuntimeError: On any I/O failure.
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            raise RuntimeError(f"JSON export failed: {exc}") from exc

    # ── CSV ───────────────────────────────────────────────────────────────

    @staticmethod
    def to_csv(records: List[dict], path: str) -> None:
        """
        Save a list of history records to a CSV file (UTF-8-sig for Excel).

        Columns: id, timestamp, words, chars, language, duration, text
        (text last so long strings don't break column reading).

        Args:
            records: List of record dicts from HistoryManager.get_all().
            path:    Destination .csv path.

        Raises:
            RuntimeError: On any I/O failure.
        """
        fieldnames = ["id", "timestamp", "words", "chars", "language", "duration", "text"]
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(records)
        except Exception as exc:
            raise RuntimeError(f"CSV export failed: {exc}") from exc
