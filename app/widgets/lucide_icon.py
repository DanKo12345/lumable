from __future__ import annotations

import warnings
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtSvg import QSvgRenderer

LUCIDE_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "lucide"
FALLBACK_ICON = "circle-dot"


def lucide_renderer(kind: str, parent: QObject | None = None) -> QSvgRenderer:
    """Load one glyph, making a missing asset visible without leaving a blank.

    RuntimeWarning is an error under pytest, so any exercised missing icon fails
    the suite. A packaged application still gets a neutral glyph and a useful
    diagnostic instead of silently painting only the tile behind it.
    """
    name = str(kind).strip()
    renderer = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{name}.svg"), parent)
    if renderer.isValid():
        return renderer

    warnings.warn(
        f"Lucide icon {name!r} is missing or invalid; using {FALLBACK_ICON!r}",
        RuntimeWarning,
        stacklevel=2,
    )
    fallback = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{FALLBACK_ICON}.svg"), parent)
    if not fallback.isValid():
        raise RuntimeError(f"Fallback Lucide icon {FALLBACK_ICON!r} is missing or invalid")
    return fallback
