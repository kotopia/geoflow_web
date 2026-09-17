from __future__ import annotations

from collections.abc import Iterable
from typing import Any

REFERENCE_CATALOG_VERSION = "gis-reference-v2"
REFERENCE_STORE = "central.gis.definition_code"


def _standard_names(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    return sorted(
        {
            str(value or "").strip().upper()
            for value in values
            if str(value or "").strip()
        }
    )


def project_reference_catalog(
    *,
    using: str,
    standard_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Resolve active GIS field/reference bindings from the GIS-owned catalog.

    Tenant metadata fallback is deliberately forbidden: the default database is
    the single source of truth for Web GIS, QGIS and QField.
    """

    names = _standard_names(standard_names)
    if standard_names is not None and not names:
        return {"ok": True, "version": REFERENCE_CATALOG_VERSION,
                "reference_store": REFERENCE_STORE, "runtime_source": "central.gis",
                "bindings": [], "groups": [], "binding_count": 0, "group_count": 0}
    from .central_definitions import central_snapshot, reference_payload
    data = central_snapshot()
    if data is None:
        raise RuntimeError('central GIS definition is not available')
    wanted=set(names)
    layer_ids=[layer['id'] for layer in data['layers']
               if not wanted or layer['standard_name'].upper() in wanted]
    return reference_payload(data,layer_ids)
