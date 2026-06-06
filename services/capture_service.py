"""
services/capture_service.py
===========================
Screen capture service for Smart Text Extractor.

Uses `mss` to grab a specific screen region and returns it as a
BGR numpy array ready for OCR processing.

Saves every capture as a timestamped PNG in the captures/ directory.
The gallery dialog reads this directory to show a screenshot history.
"""

from __future__ import annotations

import os
from datetime import datetime

import mss
import mss.tools
import numpy as np
from PIL import Image


import pathlib as _pathlib

# Phase 10: captures always live in %APPDATA%\TextEx\captures\ so the
# packaged app can write them when installed under Program Files.
from textex_packaging.paths import get_captures_dir as _get_captures_dir

_CAPTURE_DIR = _get_captures_dir()


class CaptureService:
    """
    Captures a rectangular region of the screen using mss.

    Returns the image as a BGR numpy array suitable for PaddleOCR.
    Every capture is saved as captures/<timestamp>.png for the gallery.
    An additional captures/debug.png (latest capture) is always written.
    """

    CAPTURE_DIR = _CAPTURE_DIR
    DEBUG_PATH  = os.path.join(_CAPTURE_DIR, "debug.png")

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def capture(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        save_named: bool = True,
    ) -> tuple[np.ndarray, str]:
        """
        Capture a screen region and return a BGR numpy array.

        Args:
            x:          Left edge in physical screen pixels.
            y:          Top edge in physical screen pixels.
            width:      Region width in physical pixels.
            height:     Region height in physical pixels.
            save_named: If True, also save a timestamped copy for gallery.

        Returns:
            (image, saved_path) where image is BGR ndarray (H x W x 3)
            and saved_path is the path of the timestamped file
            (or empty string if save_named is False).

        Raises:
            ValueError:   If width or height is not positive.
            RuntimeError: If mss fails to capture the region.
        """
        # Validate
        if width <= 0 or height <= 0:
            raise ValueError(
                f"Invalid region dimensions: width={width}, height={height}. "
                "Both must be positive."
            )
        if x < 0 or y < 0:
            raise ValueError(
                f"Invalid region origin: x={x}, y={y}. "
                "Coordinates must be non-negative."
            )

        # Capture
        monitor = {"top": y, "left": x, "width": width, "height": height}
        try:
            with mss.mss() as sct:
                shot = sct.grab(monitor)
                img_bgra = np.array(shot)
                img_bgr  = img_bgra[:, :, :3]
        except Exception as exc:
            raise RuntimeError(
                f"Screen capture failed for region "
                f"({x}, {y}, {width}x{height}): {exc}"
            ) from exc

        # Save debug copy (always)
        named_path = self._save(img_bgr, save_named=save_named)
        return img_bgr, named_path

    def list_screenshots(self) -> list[str]:
        """
        Return a sorted list of timestamped screenshot paths in captures/.

        Excludes debug.png.

        Returns:
            List of absolute paths, newest first.
        """
        if not os.path.isdir(self.CAPTURE_DIR):
            return []
        files = [
            os.path.join(self.CAPTURE_DIR, f)
            for f in os.listdir(self.CAPTURE_DIR)
            if f.endswith(".png") and f != "debug.png"
        ]
        files.sort(reverse=True)
        return files

    def delete_screenshot(self, path: str) -> bool:
        """
        Delete a screenshot file.

        Returns True on success, False if the file was not found.
        """
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            print(f"[CaptureService] Warning: could not delete {path}: {exc}")
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────────

    def _save(self, img_bgr: np.ndarray, save_named: bool = True) -> str:
        """
        Save the captured image to disk.

        Always writes captures/debug.png (overwritten each time).
        Optionally writes captures/<timestamp>.png for the gallery.

        Args:
            img_bgr:    BGR numpy array.
            save_named: Whether to also write the timestamped copy.

        Returns:
            Path of the named (timestamped) file, or "" if not saved.
        """
        os.makedirs(self.CAPTURE_DIR, exist_ok=True)
        img_rgb = img_bgr[:, :, ::-1]   # BGR -> RGB for Pillow
        pil_img = Image.fromarray(img_rgb)

        named_path = ""

        try:
            # Debug copy (always overwritten)
            pil_img.save(self.DEBUG_PATH)

            # Timestamped copy for the gallery
            if save_named:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
                named_path = os.path.join(self.CAPTURE_DIR, f"{ts}.png")
                pil_img.save(named_path)

            print(f"[CaptureService] Saved -> {named_path or self.DEBUG_PATH}")

        except Exception as exc:
            print(f"[CaptureService] Warning: could not save image: {exc}")

        return named_path
