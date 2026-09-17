"""Shared GeoFlow presentation for central Dynamic Forms."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def form_stylesheet() -> str:
    path = Path(__file__).resolve().parents[2] / "resources" / "styles" / "geoflow_form.qss"
    return path.read_text(encoding="utf-8")


def apply_form_style(widget) -> None:
    """Apply the packaged stylesheet once at the Dynamic Form root."""
    widget.setObjectName("GeoFlowDynamicForm")
    widget.setStyleSheet(form_stylesheet())
