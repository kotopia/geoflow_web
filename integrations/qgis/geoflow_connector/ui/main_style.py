"""Cached, root-scoped presentation for GeoFlow's main navigation UI."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def main_stylesheet() -> str:
    path = Path(__file__).resolve().parents[1] / "resources" / "styles" / "geoflow_main.qss"
    return path.read_text(encoding="utf-8")


def apply_main_style(widget) -> None:
    """Apply the shared stylesheet once at a named project/layer root."""
    widget.setProperty("geoflowMain", True)
    widget.setStyleSheet(main_stylesheet())
