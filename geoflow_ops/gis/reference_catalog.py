from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import connections


REFERENCE_CATALOG_VERSION = "gis-reference-v1"
REFERENCE_STORE = "gis.ref_code_group/gis.ref_code_value"


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

    This runtime contract intentionally reads only the ``gis`` schema. GIS
    references are not backed by ``ops.settings_nodes`` and changing one code
    value must not require a QGIS/QField plugin or package update.
    """

    names = _standard_names(standard_names)
    where = [
        "ft.active",
        "NULLIF(BTRIM(fd.code_group_key), '') IS NOT NULL",
        "g.active",
    ]
    params: list[Any] = []
    if names:
        placeholders = ",".join(["%s"] * len(names))
        where.append(f"UPPER(ft.standard_name) IN ({placeholders})")
        params.extend(names)

    sql = f"""
        SELECT
            UPPER(ft.standard_name) AS feature_standard_name,
            fd.standard_name AS field_standard_name,
            fd.physical_name AS field_physical_name,
            fd.label AS field_label,
            fd.code_group_key,
            g.name AS group_name,
            v.code,
            v.label AS value_label,
            v.sort_order
          FROM gis.meta_field_def fd
          JOIN gis.meta_feature_type ft
            ON ft.id=fd.feature_type_id
          JOIN gis.ref_code_group g
            ON g.group_key=fd.code_group_key
          LEFT JOIN gis.ref_code_value v
            ON v.group_id=g.id
           AND v.active
           AND (v.valid_from IS NULL OR v.valid_from <= CURRENT_DATE)
           AND (v.valid_to IS NULL OR v.valid_to >= CURRENT_DATE)
         WHERE {' AND '.join(where)}
         ORDER BY UPPER(ft.standard_name), fd.sort_order, fd.physical_name,
                  g.group_key, v.sort_order, v.code
    """

    bindings: list[dict[str, Any]] = []
    seen_bindings: set[tuple[str, str, str]] = set()
    groups_by_key: dict[str, dict[str, Any]] = {}
    seen_values: dict[str, set[str]] = {}

    with connections[using].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    for row in rows:
        (
            feature_standard_name,
            field_standard_name,
            field_physical_name,
            field_label,
            code_group_key,
            group_name,
            code,
            value_label,
            sort_order,
        ) = row

        binding_key = (
            str(feature_standard_name),
            str(field_physical_name),
            str(code_group_key),
        )
        if binding_key not in seen_bindings:
            seen_bindings.add(binding_key)
            bindings.append(
                {
                    "standard_name": str(feature_standard_name),
                    "field_standard_name": str(field_standard_name),
                    "field_name": str(field_physical_name),
                    "field_label": str(field_label),
                    "code_group_key": str(code_group_key),
                }
            )

        group_key = str(code_group_key)
        group = groups_by_key.setdefault(
            group_key,
            {
                "code_group_key": group_key,
                "name": str(group_name),
                "values": [],
            },
        )
        value_codes = seen_values.setdefault(group_key, set())
        if code is not None and str(code) not in value_codes:
            value_codes.add(str(code))
            group["values"].append(
                {
                    "code": str(code),
                    "label": str(value_label),
                    "sort_order": int(sort_order or 0),
                }
            )

    groups = [groups_by_key[key] for key in sorted(groups_by_key)]
    return {
        "ok": True,
        "version": REFERENCE_CATALOG_VERSION,
        "reference_store": REFERENCE_STORE,
        "runtime_source": "gis",
        "bindings": bindings,
        "groups": groups,
        "binding_count": len(bindings),
        "group_count": len(groups),
    }
