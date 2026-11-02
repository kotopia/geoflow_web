"""Water-depth calculation from an spatially matched Survey point and nearby H."""
from __future__ import annotations

import json
import math

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea,
    QgsFeature, QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsProject,
    QgsRectangle, QgsSpatialIndex, QgsVectorLayer,
)

from .nearby import NearbySearchService, within_radius
from .settings import GeoFlowSettingsService
from ..survey.code_normalizer import normalize_raw_code, standard_code_role
from .survey_spatial import active_feature, value


FAILURE_REASONS = {
    "no_nearby_survey": "적합한 주변 Survey 없음",
    "source_z_missing": "source Z 없음",
    "invalid_source_z": "source Z 비정상",
    "no_nearby_h": "주변 H 없음",
    "no_height_candidate": "주변 표고 기준점(H) 없음",
    "calculation_failed": "심도 계산 실패",
    "h_z_missing": "H Z 없음",
    "out_of_radius": "검색반경 초과",
    "invalid_result": "계산 결과 비정상",
}


class DepthFromNearbySurveyH:
    """Pure business rule; source discovery and writes stay in ``DepthService``."""

    standard_name = "WTL_PIPE_PS"
    depth_field = "pip_dep"
    survey_z_field = "raw_z"
    survey_code_field = "code"

    def __init__(self, *, depth_field="pip_dep", subtract="reference-source"):
        if depth_field != self.depth_field or subtract != "reference-source":
            raise ValueError("WTL_PIPE_PS 심도 계약은 pip_dep=H.raw_z-source.raw_z 입니다.")
        self.subtract = subtract

    @staticmethod
    def is_h(value):
        return str(value or "").strip().casefold() == "h"

    def calculate(self, source_z, reference_z):
        try:
            source = float(source_z)
        except (TypeError, ValueError):
            return None, "source_z_missing"
        try:
            reference = float(reference_z)
        except (TypeError, ValueError):
            return None, "h_z_missing"
        result = reference - source
        if not math.isfinite(result):
            return None, "invalid_result"
        return round(result, 3), None


def _clean(value):
    if value is None:
        return None
    try:
        return None if value.isNull() else value
    except AttributeError:
        return value


def _source_z_reason(value):
    if value is None:
        return 'source_z_missing'
    try:
        return None if math.isfinite(float(value)) else 'invalid_source_z'
    except (TypeError, ValueError, OverflowError):
        return 'invalid_source_z'


class DepthService:
    """Find source Survey, calculate evidence, and stage local QGIS edits only."""

    def __init__(self, plugin, *, settings=None, project=None):
        self.plugin = plugin
        self.settings_service = (
            settings if isinstance(settings, GeoFlowSettingsService)
            else GeoFlowSettingsService(plugin, settings=settings)
        )
        self.project = project or QgsProject.instance()
        self.nearby = NearbySearchService(self.project, logger=self._plain_log)
        self.strategy = DepthFromNearbySurveyH()

    def _plain_log(self, message):
        logger = getattr(self.plugin, "log", None)
        if callable(logger):
            logger(message)

    def _log(self, event, **values):
        logger = getattr(self.plugin, "log", None)
        if not callable(logger):
            return
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
        logger(event + (" " + payload if values else ""))

    @property
    def radius_m(self):
        return self.settings_service.get_depth_radius()

    def _layer(self, standard):
        standard = str(standard).upper()
        managed = getattr(self.plugin, "_managed_layers", None)
        layers = managed() if callable(managed) else ()
        return next((layer for layer in layers
                     if str(layer.customProperty(
                         "geoflow/standard_name", ""
                     )).upper() == standard), None)

    def _normalized_code(self, value):
        context = getattr(self.plugin, "active_context", None) or {}
        client = getattr(self.plugin, "active_client", None)
        return normalize_raw_code(
            context.get("project_id", ""), value,
            origin=getattr(client, "base_url", ""),
        )

    def _is_h(self, value):
        # Survey `code` is the resolved survey_code written at import time.
        return str(value or "").strip() == "H"

    def _survey_layer(self):
        layer = self._layer("SURVEY")
        if not isinstance(layer, QgsVectorLayer):
            return None
        required = {
            self.strategy.survey_code_field,
            self.strategy.survey_z_field,
            "id",
        }
        return layer if required.issubset(set(layer.fields().names())) else None

    def prepare_batch(self):
        """Scan Survey/H rows once and reuse one spatial index for this batch."""
        survey = self._survey_layer()
        self._batch_ready = True
        self._batch_survey = survey
        self._batch_by_id = {}
        self._batch_h = {}
        self._batch_h_wgs84 = {}
        self._batch_index = QgsSpatialIndex()
        if survey is None:
            return self
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = (QgsCoordinateTransform(
            survey.crs(), wgs84, self.project.transformContext()
        ) if survey.crs() != wgs84 else None)
        for feature in survey.getFeatures():
            if not self._active(feature):
                continue
            self._batch_by_id[str(_clean(feature["id"]) or "").strip("{}")] = feature
            if not self._is_h(feature[self.strategy.survey_code_field]):
                continue
            geometry = QgsGeometry(feature.geometry())
            if transform is not None:
                geometry.transform(transform)
            point = self.nearby._point(geometry)
            if point is None:
                continue
            indexed = QgsFeature()
            indexed.setId(feature.id())
            indexed.setGeometry(QgsGeometry.fromPointXY(point))
            self._batch_index.addFeature(indexed)
            self._batch_h[feature.id()] = feature
            self._batch_h_wgs84[feature.id()] = point
        self._batch_distance = QgsDistanceArea()
        self._batch_distance.setSourceCrs(wgs84, self.project.transformContext())
        ellipsoid = str(self.project.ellipsoid() or "").strip()
        self._batch_distance.setEllipsoid(
            "WGS84" if not ellipsoid or ellipsoid.upper() == "NONE" else ellipsoid
        )
        return self

    def _calculate_batch_point(self, point):
        survey = self._batch_survey
        if survey is None:
            return {"ok": False, "reason": "no_nearby_survey"}
        source_id = str(point.get("id") or "").strip("{}")
        source = self._batch_by_id.get(source_id)
        source_z = _clean(source[self.strategy.survey_z_field]) if source is not None else point.get("raw_z")
        reason = _source_z_reason(source_z)
        if reason:
            return {"ok": False, "reason": reason, "source_id": source_id}
        if source is not None:
            origin = self.nearby._wgs84_point(source.geometry(), survey.crs())
        else:
            try:
                origin = QgsPointXY(float(point["longitude"]), float(point["latitude"]))
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "reason": "no_nearby_survey"}
        if origin is None:
            return {"ok": False, "reason": "no_nearby_survey"}
        radius = float(self.radius_m)
        latitude = max(-89.9, min(89.9, float(origin.y())))
        lat_delta = (radius * 1.01 + 1e-6) / 110574.0
        lon_delta = (radius * 1.01 + 1e-6) / max(1.0, 111320.0 * abs(math.cos(math.radians(latitude))))
        rectangle = QgsRectangle(
            origin.x() - lon_delta, origin.y() - lat_delta,
            origin.x() + lon_delta, origin.y() + lat_delta,
        )
        candidate_ids = self._batch_index.intersects(rectangle)
        candidates = []
        for feature_id in candidate_ids:
            metres = float(self._batch_distance.measureLine(
                origin, self._batch_h_wgs84[feature_id]
            ))
            if within_radius(metres, radius):
                candidates.append((metres, self._batch_h[feature_id]))
        candidates.sort(key=lambda row: (row[0], row[1].id()))
        self._h_candidate_count = len(candidates)
        if not candidates:
            reason = "no_height_candidate"
            return {"ok": False, "reason": reason,
                    "source_id": source_id, "source_z": float(source_z)}
        reference = next((row for row in candidates
                          if _clean(row[1][self.strategy.survey_z_field]) is not None), None)
        if reference is None:
            return {"ok": False, "reason": "h_z_missing",
                    "source_id": source_id, "source_z": float(source_z)}
        distance_m, reference_feature = reference
        reference_z = _clean(reference_feature[self.strategy.survey_z_field])
        depth, reason = self.strategy.calculate(source_z, reference_z)
        if reason:
            return {"ok": False, "reason": reason}
        return {
            "ok": True, "source_id": source_id,
            "reference_survey_id": str(reference_feature["id"]),
            "source_z": float(source_z), "reference_z": float(reference_z),
            "distance_m": distance_m, "depth": depth,
            "requires_review": depth < 0,
        }

    def target_supported(self, layer):
        return self.support_status(layer)["supported"]

    def support_status(self, layer):
        vector = isinstance(layer, QgsVectorLayer)
        standard = str(layer.customProperty(
            "geoflow/standard_name", ""
        )).upper() if vector else ""
        depth_field = bool(
            vector and layer.fields().indexFromName(self.strategy.depth_field) >= 0
        )
        survey = self._survey_layer() if (
            vector and standard == self.strategy.standard_name and depth_field
        ) else None
        reasons = []
        if not vector:
            reasons.append("not_vector")
        if standard != self.strategy.standard_name:
            reasons.append("unsupported_layer")
        if not depth_field:
            reasons.append("missing_pip_dep")
        return {
            "supported": not reasons,
            "standard": standard,
            "depth_field": depth_field,
            "survey_layer": survey is not None,
            "reasons": reasons,
        }

    @staticmethod
    def _feature_by_uuid(layer, object_id):
        if layer is None or not object_id:
            return None
        safe = str(object_id).strip("{}")
        request = QgsFeatureRequest().setFilterExpression(
            "replace(replace(\"id\", '{', ''), '}', '') = '" + safe + "'"
        )
        rows = list(layer.getFeatures(request))
        return rows[0] if len(rows) == 1 else None

    def _active(self, feature):
        project_id = (getattr(self.plugin, 'active_context', None) or {}).get("project_id", "")
        return active_feature(feature, project_id) and feature.geometry().type().name == "Point"

    def _source_candidate(self, feature):
        code = str(value(feature, self.strategy.survey_code_field) or "").strip()
        return self._active(feature) and bool(code) and standard_code_role(code) in {"FACILITY", "DEPTH"}

    def find_source(self, feature):
        survey = self._survey_layer()
        target = self._layer(self.strategy.standard_name)
        if feature is None or survey is None or target is None or not self._active(feature):
            return None
        number = str(value(feature, "survey_no") or "").strip()
        # Management-number lookup is an ordinary attribute comparison. Resolve
        # repeated numbers by distance, never by a stored relationship UUID.
        if number:
            matches = self.nearby.find_nearest(
                feature.geometry(), survey, self.radius_m, target_crs=target.crs(),
                filter_fn=lambda row: self._source_candidate(row)
                and str(value(row, "survey_no") or "").strip() == number,
                function="depth_source_number", candidate_limit=max(1, int(survey.featureCount())),
            )
            if matches:
                self._survey_candidate_count = len(matches)
                return matches[0]["feature"]
        matches = self.nearby.find_nearest(
            feature.geometry(), survey, self.radius_m, target_crs=target.crs(),
            filter_fn=self._source_candidate, function="depth_source_spatial",
            candidate_limit=max(1, int(survey.featureCount())),
        )
        self._survey_candidate_count = len(matches)
        return matches[0]["feature"] if matches else None

    def _calculate(self, source_feature):
        survey = self._survey_layer()
        if source_feature is None:
            self._log("depth_calculate_failed", stage="source_lookup", reason="no_nearby_survey")
            return {"ok": False, "reason": "no_nearby_survey"}
        source_z = _clean(source_feature[self.strategy.survey_z_field])
        source_id = str(source_feature["id"])
        self._log(
            "depth_source_lookup_result", found=True,
            source_id=source_id, source_z=source_z,
            source_code=_clean(source_feature[self.strategy.survey_code_field]),
        )
        reason = _source_z_reason(source_z)
        if reason:
            self._log(
                "depth_calculate_failed", stage="source_lookup",
                reason=reason, source_id=source_id,
            )
            return {"ok": False, "reason": reason,
                    "source_id": source_id}
        self._log(
            "depth_nearby_search_start", radius_m=self.radius_m,
            source_id=source_id,
        )
        candidates = self.nearby.find_nearest(
            source_feature.geometry(), survey, self.radius_m,
            filter_fn=lambda row: self._active(row) and self._is_h(
                row[self.strategy.survey_code_field]
            ),
            target_crs=survey.crs(),
            candidate_limit=max(1, int(survey.featureCount())),
            nearest_first=self.settings_service.get_nearest_first(),
            function="depth",
        )
        self._h_candidate_count = len(candidates)
        if not candidates:
            reason = "no_height_candidate"
            self._log(
                "depth_nearby_search_result", candidate_count=0,
                selected_h_survey_id="", reason=reason,
            )
            self._log("depth_calculate_failed", stage="nearby_search", reason=reason)
            return {"ok": False,
                    "reason": reason,
                    "source_id": source_id,
                    "source_z": float(source_z)}
        reference = next((row for row in candidates
                          if _clean(row["feature"][self.strategy.survey_z_field])
                          is not None), None)
        if reference is None:
            self._log(
                "depth_nearby_search_result", candidate_count=len(candidates),
                selected_h_survey_id="", reason="h_z_missing",
            )
            self._log("depth_calculate_failed", stage="nearby_search", reason="h_z_missing")
            return {"ok": False, "reason": "h_z_missing",
                    "source_id": source_id,
                    "source_z": float(source_z)}
        reference_feature = reference["feature"]
        reference_z = _clean(reference_feature[self.strategy.survey_z_field])
        self._log(
            "depth_nearby_search_result", candidate_count=len(candidates),
            selected_h_survey_id=str(reference_feature["id"]),
            selected_h_z=reference_z,
            distance_m=float(reference["distance_m"]),
        )
        depth, reason = self.strategy.calculate(source_z, reference_z)
        if reason:
            self._log("depth_calculate_failed", stage="calculate", reason=reason)
            return {"ok": False, "reason": reason}
        self._log(
            "depth_calculate_result", depth=depth,
            source_z=float(source_z), selected_h_z=float(reference_z),
        )
        return {
            "ok": True,
            "source_id": str(source_feature["id"]),
            "reference_survey_id": str(reference_feature["id"]),
            "source_z": float(source_z),
            "reference_z": float(reference_z),
            "distance_m": float(reference["distance_m"]),
            "depth": depth,
            "requires_review": depth < 0,
        }

    def calculate_feature(self, feature):
        feature_id = ""
        if feature is not None and "id" in feature.fields().names():
            feature_id = str(_clean(feature["id"]) or "")
        self._log(
            "depth_calculate_start", feature_id=feature_id,
            layer=self.strategy.standard_name,
        )
        self._survey_candidate_count = 0
        self._h_candidate_count = 0
        result = self._calculate(self.find_source(feature))
        return self._record_search_result(result)

    def _record_search_result(self, result):
        self._log("[DEPTH_SEARCH]", radius_m=self.radius_m,
                  survey_candidate_count=self._survey_candidate_count,
                  h_candidate_count=self._h_candidate_count,
                  source_id=result.get("source_id", ""),
                  result="success" if result.get("ok") else "failed",
                  reason=result.get("reason", ""))
        return result

    def calculate_survey_point(self, point):
        """Calculate before a facility exists during Survey generation."""
        self._survey_candidate_count = int(isinstance(point, dict))
        self._h_candidate_count = 0
        return self._record_search_result(self._calculate_survey_point(point))

    def _calculate_survey_point(self, point):
        if not isinstance(point, dict):
            return {"ok": False, "reason": "no_nearby_survey"}
        if getattr(self, "_batch_ready", False):
            return self._calculate_batch_point(point)
        survey = self._survey_layer()
        if survey is None:
            return {"ok": False, "reason": "no_nearby_survey"}
        source_id = str(point.get("id") or "")
        source_feature = self._feature_by_uuid(survey, source_id)
        if source_feature is not None:
            return self._calculate(source_feature)
        try:
            lon, lat = float(point["longitude"]), float(point["latitude"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "reason": "no_nearby_survey"}
        from qgis.core import QgsFeature
        source_feature = QgsFeature(survey.fields())
        source_feature["id"] = source_id
        source_feature[self.strategy.survey_z_field] = point.get("raw_z")
        source_feature[self.strategy.survey_code_field] = (
            point.get("code") or self._normalized_code(point.get("raw_code"))
        )
        coordinate = QgsPointXY(lon, lat)
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if survey.crs() != wgs84:
            coordinate = QgsCoordinateTransform(
                wgs84, survey.crs(), self.project.transformContext()
            ).transform(coordinate)
        source_feature.setGeometry(QgsGeometry.fromPointXY(coordinate))
        return self._calculate(source_feature)

    def form_field_id(self, page):
        matches = [field["id"] for field in page.form.fields
                   if str((field.get("storage") or {}).get("key") or "").casefold()
                   == self.strategy.depth_field]
        return matches[0] if len(matches) == 1 else None

    def apply_to_form(self, page, feature, *, overwrite):
        state = self.plugin.integration_state()
        layer = next((l for l in self.plugin._managed_layers() if l.id() == page.layer_id),None)
        if not state.get('can_write') or layer is None or layer.readOnly():
            return {'ok':False,'reason':'편집 권한이 없습니다.'}
        field_id = self.form_field_id(page)
        if not field_id:
            return {"ok": False, "reason": "invalid_result"}
        values = page.form.values()
        if not overwrite and _clean(values.get(field_id)) is not None:
            return {"ok": True, "skipped": True}
        result = self.calculate_feature(feature)
        if result.get("ok"):
            values[field_id] = result["depth"]
            page.form.load_values(values)
            dirty = bool(page.binding.has_actual_changes())
            displayed = page.form.values().get(field_id)
            self._log(
                "depth_apply_result", target="dynamic_form",
                feature_id=str(_clean(feature["id"]) or ""),
                field=self.strategy.depth_field, value=result["depth"],
                applied=True, widget_updated=displayed == result["depth"],
                dirty=dirty,
            )
        return result

    def apply_to_features(self, layer, features, *, overwrite, page=None):
        """Calculate existing rules, stage changed values only, and report every row."""
        features = list(features)
        summary = dict(total=len(features), success=0, changed=0, unchanged=0,
                       failed=0, skipped=0, review=0, failures=[], results=[])
        state = self.plugin.integration_state()
        writable = (state.get('ready') and state.get('can_write') and not layer.readOnly()
                    and any(item is layer for item in self.plugin._managed_layers())
                    and self.target_supported(layer))
        index = layer.fields().indexFromName(self.strategy.depth_field)
        command = False
        form_id = self.form_field_id(page) if page is not None else None
        try:
            for feature in features:
                old = _clean(feature[index]) if index >= 0 else None
                is_form = page is not None and page.layer_id == layer.id() and page.feature_id == feature.id() and form_id
                if is_form: old = _clean(page.form.values().get(form_id))
                row = dict(fid=feature.id(), identity=self._identity(feature), old=old,
                           depth=None, ok=False, status='failed', reason='')
                if not writable:
                    row['reason'] = '프로젝트 범위 또는 편집 권한이 없습니다.'
                elif not overwrite and old is not None:
                    row.update(status='skipped', skipped=True)
                else:
                    try:
                        row.update(self.calculate_feature(feature))
                        if row.get('ok'):
                            summary['success'] += 1
                            summary['review'] += int(bool(row.get('requires_review')))
                            if old == row['depth']:
                                row['status'] = 'unchanged'
                            else:
                                if not layer.isEditable() and not layer.startEditing():
                                    raise ValueError('레이어 편집을 시작할 수 없습니다.')
                                if not command:
                                    layer.undoStack().beginMacro('GeoFlow 심도 일괄계산')
                                    command = True
                                layer.beginEditCommand('GeoFlow 심도값')
                                if not layer.changeAttributeValue(feature.id(), index, row['depth']):
                                    layer.destroyEditCommand()
                                    raise ValueError('심도값 적용 실패')
                                layer.endEditCommand()
                                if is_form:
                                    from .direction import FormAngleCommand
                                    cmd = FormAngleCommand(page,form_id,row['depth'])
                                    retained = getattr(layer,'_geoflow_form_commands',[])
                                    retained.append(cmd); layer._geoflow_form_commands = retained
                                    layer.undoStack().push(cmd)
                                row['status'] = 'changed'
                    except Exception as exc:
                        row.update(status='failed', reason=str(exc))
                summary[row['status']] += 1
                if row['status'] == 'failed':
                    row['reason'] = FAILURE_REASONS.get(row.get('reason'), row.get('reason') or '계산 실패')
                    summary['failures'].append(row['reason'])
                summary['results'].append(row)
        finally:
            if command:
                layer.undoStack().endMacro()
        return summary

    @staticmethod
    def _identity(feature):
        return str(feature['id']) if 'id' in feature.fields().names() else str(feature.id())
