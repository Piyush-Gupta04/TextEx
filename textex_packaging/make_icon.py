"""
textex_packaging/make_icon.py
======================
Generates assets/textex.ico — the application icon used by:
  - The Windows taskbar / title bar
  - The system tray
  - The installer shortcut
  - Windows Explorer (shown on TextEx.exe)

Run once before building:
    python textex_packaging/make_icon.py

Requires Pillow (already in requirements.txt).
Produces a multi-resolution ICO containing:
    16 × 16, 24 × 24, 32 × 32, 48 × 48, 64 × 64, 128 × 128, 256 × 256
"""

from __future__ import annotations

import os
import sys

# Allow running as  python textex_packaging/make_icon.py  from the project root
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# ─── Design constants ─────────────────────────────────────────────────────────
BG_GRADIENT_TOP    = (30,  30,  46)    # #1e1e2e  (dark purple-blue)
BG_GRADIENT_BOTTOM = (17,  17,  27)    # #11111b
ACCENT_BLUE        = (137, 180, 250)   # #89b4fa  (Catppuccin blue)
ACCENT_PURPLE      = (203, 166, 247)   # #cba6f7  (Catppuccin mauve)
TEXT_COLOR         = (205, 214, 244)   # #cdd6f4  (foreground)

SIZES = [16, 24, 32, 48, 64, 128, 256]

OUTPUT_PATH = os.path.join(_ROOT, "assets", "textex.ico")


def _draw_icon(size: int) -> Image.Image:
    """Draw the TextEx icon at the given pixel size."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Background rounded rect ───────────────────────────────────────────
    radius = max(2, size // 8)
    # Gradient-ish background: draw top half and bottom half separately
    draw.rounded_rectangle(
        [0, 0, size - 1, size // 2],
        radius=radius,
        fill=BG_GRADIENT_TOP,
    )
    draw.rounded_rectangle(
        [0, size // 2, size - 1, size - 1],
        radius=radius,
        fill=BG_GRADIENT_BOTTOM,
    )
    # Combine with a full rounded rect to get clean corners
    draw.rounded_rectangle(
        [0, 0, size - 1, size - 1],
        radius=radius,
        outline=ACCENT_BLUE,
        width=max(1, size // 32),
    )

    # ── "Tx" text centred ─────────────────────────────────────────────────
    label    = "Tx"
    font_sz  = max(6, int(size * 0.45))

    try:
        font = ImageFont.truetype("arial.ttf", font_sz)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    tx   = (size - tw) // 2 - bbox[0]
    ty   = (size - th) // 2 - bbox[1]

    # Shadow for readability
    if size >= 32:
        draw.text((tx + 1, ty + 1), label, font=font, fill=(0, 0, 0, 160))

    # Gradient text: top = blue, bottom = purple (approximate with single colour)
    draw.text((tx, ty), label, font=font, fill=ACCENT_BLUE)

    return img


def main() -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    frames = [_draw_icon(s) for s in SIZES]

    # Save as ICO (all sizes in one file)
    frames[0].save(
        OUTPUT_PATH,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )

    print(f"[make_icon] Written: {OUTPUT_PATH}")
    print(f"[make_icon] Sizes: {SIZES}")


if __name__ == "__main__":
    main()
