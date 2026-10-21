"""Cached, root-scoped presentation for the photo tab."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def photo_stylesheet() -> str:
    path = Path(__file__).resolve().parents[1] / "resources" / "styles" / "geoflow_photo.qss"
    return path.read_text(encoding="utf-8")


def apply_photo_style(widget) -> None:
    """Apply the photo stylesheet once at the photo-tab root."""
    widget.setStyleSheet(photo_stylesheet())
