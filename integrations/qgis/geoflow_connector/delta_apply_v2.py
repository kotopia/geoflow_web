from __future__ import annotations

from qgis.core import QgsFeature


class DeltaApplyV2Mixin:
    """Apply server Delta without breaking an already-open QGIS edit session.

    QGIS can keep a layer in edit mode after the user saves edits.  The v0.5.0
    Delta path unconditionally called startEditing(), which fails for an
    already-editable layer and prevented last_applied_revision from advancing.
    This mixin reuses an existing clean edit session and commits Delta changes
    while preserving that edit mode where the QGIS API supports it.
    """

    @staticmethod
    def _commit_delta_layer(layer, *, keep_editing: bool) -> None:
        try:
            ok = layer.commitChanges(False if keep_editing else True)
        except TypeError:
            # Compatibility fallback for bindings that do not expose the
            # stopEditing parameter.  Restore the previous edit state after a
            # successful commit when needed.
            ok = layer.commitChanges()
            if ok and keep_editing and not layer.isEditable():
                if not layer.startEditing():
                    raise RuntimeError(
                        f"{layer.name()}: Delta 반영 후 기존 편집 모드를 복원할 수 없습니다."
                    )
        if not ok:
            errors = "; ".join(layer.commitErrors()) if hasattr(layer, "commitErrors") else ""
            raise RuntimeError(
                f"{layer.name()}: Delta 로컬 반영 실패.{(' ' + errors) if errors else ''}"
            )

    def _apply_delta_page(self, changes: list[dict]) -> None:
        if not changes:
            return
        context = self.active_context or {}
        project_id = str(context.get("project_id") or "")
        by_standard = {
            str(layer.customProperty("geoflow/standard_name", "") or ""): layer
            for layer in self._managed_layers()
        }
        grouped: dict[str, list[dict]] = {}
        for change in changes:
            grouped.setdefault(str(change.get("layer") or ""), []).append(change)

        self._suppress_auto_sync = True
        try:
            for standard_name, layer_changes in grouped.items():
                layer = by_standard.get(standard_name)
                if layer is None:
                    continue

                was_editable = bool(layer.isEditable())
                if was_editable:
                    # The automatic sync path only runs after local saves.  If
                    # a new unsaved edit somehow exists, never mix remote Delta
                    # into that edit buffer.
                    if layer.isModified():
                        raise RuntimeError(
                            f"{standard_name}: 저장되지 않은 로컬 편집이 있어 Delta 적용을 연기합니다."
                        )
                elif not layer.startEditing():
                    raise RuntimeError(
                        f"{standard_name}: Delta 적용을 위한 로컬 편집을 시작할 수 없습니다."
                    )

                try:
                    for change in layer_changes:
                        object_id = str(change.get("id") or "")
                        action = str(change.get("action") or "")
                        feature = self._find_feature(layer, object_id)

                        if action == "delete":
                            if feature is not None and not layer.deleteFeature(feature.id()):
                                raise RuntimeError(
                                    f"{standard_name} {object_id}: Delta 삭제 적용 실패"
                                )
                            continue

                        attrs = change.get("attributes") or {}
                        geometry = self._geometry_from_hex(change.get("geometry_wkb"))

                        if feature is None:
                            if action != "create":
                                raise RuntimeError(
                                    f"{standard_name} {object_id}: Delta 대상 객체가 로컬에 없습니다."
                                )
                            feature = QgsFeature(layer.fields())
                            id_idx = self._field_index(layer, "id")
                            project_idx = self._field_index(layer, "project_id")
                            if id_idx >= 0:
                                feature.setAttribute(id_idx, object_id)
                            if project_idx >= 0:
                                feature.setAttribute(project_idx, project_id)
                            for name, value in attrs.items():
                                idx = self._field_index(layer, str(name))
                                if idx >= 0:
                                    feature.setAttribute(idx, self._delta_value(value))
                            if geometry is not None:
                                feature.setGeometry(geometry)
                            if not layer.addFeature(feature):
                                raise RuntimeError(
                                    f"{standard_name} {object_id}: Delta 신규 객체 적용 실패"
                                )
                            continue

                        fid = feature.id()
                        for name, value in attrs.items():
                            idx = self._field_index(layer, str(name))
                            if idx >= 0 and not layer.changeAttributeValue(
                                fid, idx, self._delta_value(value)
                            ):
                                raise RuntimeError(
                                    f"{standard_name} {object_id}: Delta 속성 적용 실패 ({name})"
                                )
                        if geometry is not None and not layer.changeGeometry(fid, geometry):
                            raise RuntimeError(
                                f"{standard_name} {object_id}: Delta 도형 적용 실패"
                            )

                    self._commit_delta_layer(layer, keep_editing=was_editable)
                    layer.triggerRepaint()
                except Exception:
                    if layer.isEditable() and layer.isModified():
                        layer.rollBack()
                    if was_editable and not layer.isEditable():
                        layer.startEditing()
                    raise
        finally:
            self._suppress_auto_sync = False
