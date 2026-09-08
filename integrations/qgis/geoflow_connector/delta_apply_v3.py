from __future__ import annotations

import uuid

from qgis.core import QgsDefaultValue, QgsFeatureRequest

from .delta_apply_v2 import DeltaApplyV2Mixin


class DeltaApplyV3Mixin(DeltaApplyV2Mixin):
    """Normalize GeoFlow UUID text across QGIS and Delta application.

    QGIS ``uuid()`` can materialize text with braces (``{uuid}``) while the
    GeoFlow server canonicalizes UUIDs without braces.  A local feature created
    with braces could therefore fail a literal id lookup when its own server
    Delta was replayed, causing a second local row with the same semantic UUID
    but a different text representation.  Keep new local ids canonical and
    compare UUIDs canonically when applying Delta.
    """

    def _configure_layer_fields(self, layer, layer_def: dict, project_id: str, can_write: bool) -> None:
        super()._configure_layer_fields(layer, layer_def, project_id, can_write)
        if not can_write:
            return

        id_idx = self._field_index(layer, "id")
        if id_idx >= 0 and hasattr(layer, "setDefaultValueDefinition"):
            layer.setDefaultValueDefinition(
                id_idx,
                QgsDefaultValue("replace(replace(uuid(), '{', ''), '}', '')"),
            )

    @staticmethod
    def _find_feature(layer, object_id: str):
        try:
            canonical = str(uuid.UUID(str(object_id)))
        except (ValueError, TypeError, AttributeError):
            return None

        escaped = canonical.replace("'", "''")
        expression = (
            "replace(replace(\"id\", '{', ''), '}', '') = "
            f"'{escaped}'"
        )
        request = QgsFeatureRequest().setFilterExpression(expression)
        matches = []
        for feature in layer.getFeatures(request):
            matches.append(feature)
            if len(matches) > 1:
                raise RuntimeError(
                    f"{layer.name()}: 동일 GeoFlow UUID가 로컬 GeoPackage에 중복되어 있습니다. "
                    "프로젝트를 최신 Snapshot으로 다시 여세요."
                )
        return matches[0] if matches else None
