"""Modeless Survey work window backed by Designer UI and deployed Survey APIs."""
import json
import re
import traceback
from decimal import Decimal, InvalidOperation
from time import perf_counter
from pathlib import Path
from uuid import UUID, uuid4

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.uic import loadUi
from qgis.PyQt.QtWidgets import (
    QDialog, QTableWidgetItem, QComboBox, QGroupBox, QListWidget,
    QListWidgetItem, QMessageBox, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLabel,
)
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayerUtils,
                       QgsWkbTypes, QgsMessageLog, QgsFeatureRequest)

from ..survey.controller import SurveyController
from ..survey.response_view import display_rows
from ..survey.code_mapping import (
    depth_create_key, facility_identity, ftr_catalog, mapping_key,
    read_depth_create_targets, read_mappings, read_storage_codes,
    resolve_facility, standard_mapping_key, storage_code_key, write_depth_create_targets,
    write_mappings, write_storage_codes,
)
from ..survey.code_normalizer import (
    normalize_raw_code, normalization_key, read_code_aliases, read_code_rule_rows,
    standard_code_role, write_code_aliases, write_code_rule_rows,
)
from .survey_import_dialog import ImportDialog

from ..survey.creation import apply_target_inheritance
from ..services.survey_spatial import nearby_targets, overlap_distance_m
from ..services.settings import GeoFlowSettingsService

class SurveyValidationError(ValueError):
    """Actionable Survey validation failure with structured log context."""

    def __init__(self, reason, message, **context):
        super().__init__(message)
        self.reason = str(reason)
        self.context = dict(context)


def inventory_rows(payload, kind):
    if not isinstance(payload, dict) or payload.get('ok') is False:
        raise ValueError(f'{kind} 조회 실패: 이전 이력은 유지됩니다.')
    rows = payload.get(kind, payload.get('results'))
    if not isinstance(rows, list):
        raise ValueError(f'{kind} 목록 응답이 없어 0건으로 처리할 수 없습니다.')
    parsed = display_rows({kind: rows}, kind)
    if len(parsed) != len(rows):
        raise ValueError(f'{kind} 응답의 행 식별자가 유효하지 않습니다.')
    return parsed


def _import_readback_verification(submitted_points, readback_points,
                                  survey_type=None):
    """Compare source evidence and server-derived final coordinates by row id."""
    returned = {
        str(point.get("source_row_id") or ""): point
        for point in readback_points if point.get("source_row_id") is not None
    }
    issues = []
    checked = []
    for submitted in submitted_points:
        row_id = str(submitted.get("source_row_id") or "")
        actual = returned.get(row_id)
        if actual is None:
            issues.append(f"{row_id}: server readback row missing")
            continue
        numeric_fields = {
            "raw_x", "raw_y", "raw_z", "x", "y", "z",
            "longitude", "latitude", "antenna_height",
        }
        exact_fields = ["raw_x", "raw_y", "raw_z", "longitude", "latitude",
                        "antenna_height", "survey_date", "code", "raw_code"]
        for field in exact_fields:
            expected = submitted.get(field)
            received = actual.get(field)
            equal = received == expected
            if field in numeric_fields and received is not None:
                try:
                    equal = Decimal(str(received)) == Decimal(str(expected))
                except (InvalidOperation, ValueError):
                    equal = False
            if field in submitted and not equal:
                issues.append(
                    f"{row_id}.{field}: sent={submitted.get(field)!r}, "
                    f"readback={actual.get(field)!r}"
                )
        derived = ["x", "y", "longitude", "latitude"]
        if "raw_z" in submitted:
            derived.append("z")
        for field in derived:
            if actual.get(field) is None:
                issues.append(f"{row_id}.{field}: server-derived value missing")
        survey_no = str(actual.get("survey_no") or "")
        if not re.fullmatch(r"\d{6}-\d{3,}", survey_no):
            issues.append(f"{row_id}.survey_no: authoritative value missing or invalid")
        if survey_type and actual.get("type") != survey_type:
            issues.append(
                f"{row_id}.type: expected={survey_type!r}, "
                f"readback={actual.get('type')!r}"
            )
        checked.append({
            "source_row_id": row_id,
            **{field: actual.get(field) for field in (
                "survey_no", "type", "raw_x", "raw_y", "raw_z", "x",
                "y", "z", "latitude", "longitude", "antenna_height",
            )},
        })
    return {
        "ok": not issues,
        "checked_count": len(checked),
        "contract": {
            "survey_no": "server_authoritative",
            "type": "server_authoritative_from_source_survey_type",
            "x_y_z": "server_authoritative_from_raw_coordinates",
            "latitude_longitude": "server_normalized_from_geometry_input",
        },
        "issues": issues,
        "sample": checked[:3],
    }


class SurveyPanel(QDialog):
    """Compatibility name retained; this is no longer a dock page."""
    SOURCE_PLACEHOLDER_TEXT = "측량원시 선택"
    RETAINED_POINTS = "__geoflow_retained_survey_points__"
    POINT_COLUMNS = (
        "선택", "측량번호", "Code", "확정시설물", "X", "Y", "Z", "생성상태",
    )
    CREATE_FACILITY_ONLY = "FACILITY_ONLY"
    CREATE_FACILITY_WITH_DEPTH = "FACILITY_WITH_DEPTH"
    EXPOSED_PIPE_SURVEY_CODE = "L3"  # legacy metadata reader; not a create gate

    def __init__(self, plugin, parent=None):
        super().__init__(parent or plugin.iface.mainWindow())
        loadUi(str(Path(__file__).parent / "designer" / "survey_main.ui"), self)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.plugin, self.controller = plugin, SurveyController(plugin)
        self.source_rows, self.point_rows = [], []
        self._project_point_rows = []
        self._imports = []
        self.debugText.setVisible(False)
        self.debugGroup.hide()
        self.debugGroup.toggled.connect(self.debugText.setVisible)
        self.creationModeCombo.clear()
        self.creationModeCombo.addItem(
            "시설물만 생성", self.CREATE_FACILITY_ONLY
        )
        self.creationModeCombo.addItem(
            "시설물 + 심도 동시 생성", self.CREATE_FACILITY_WITH_DEPTH
        )
        self.creationModeCombo.setCurrentIndex(0)
        self.creationModeCombo.setToolTip(
            "시설물 + 심도 동시 생성은 저장코드 탭에서 체크한 시설물에만 적용됩니다."
        )
        self.createBatchButton.setEnabled(True)
        self.createBatchButton.setToolTip("체크한 모든 측량점을 속성폼 없이 로컬 시설물로 저장합니다.")
        self.stopQueueButton.hide()
        self._selection = {}
        self._overrides = {}
        self._source_scope = None
        self._session_scope = None
        self._filling = False
        self._applying_same_code = False
        self.pages.removeWidget(self.featurePage)
        self.mappingTabs.insertTab(0, self.featurePage, "시설물 생성")
        self.mappingTabs.setTabText(
            self.mappingTabs.indexOf(self.normalizationTab), "코드 정규화"
        )
        self.mappingTabs.setTabText(
            self.mappingTabs.indexOf(self.facilityMappingTab), "코드/시설물 매핑"
        )
        self.mappingTabs.setTabText(
            self.mappingTabs.indexOf(self.storageCodeTab), "저장코드"
        )
        for obsolete_name in (
                "mappingButton", "featureButton", "pointsButton"):
            obsolete = getattr(self, obsolete_name, None)
            if obsolete is not None:
                obsolete.hide()
        self._install_depth_create_options()
        depth_tab_index = self.mappingTabs.indexOf(self.depthCreateTab)
        if depth_tab_index >= 0:
            self.mappingTabs.removeTab(depth_tab_index)
        self._install_storage_actions()
        self._install_normalization_actions()
        self._wire()
        from .survey_inspection import SurveyInspection
        self.inspection = SurveyInspection(self)
        references = getattr(self.plugin, "_reference_service", None)
        if references is not None and hasattr(references, "changed"):
            references.changed.connect(self._reference_catalog_changed)
        self.reset_scope()
        self.pages.setCurrentWidget(self.mappingPage)
        self.mappingTabs.setCurrentWidget(self.featurePage)

    def _wire(self):
        self.importButton.clicked.connect(self.import_file)
        obsolete_actions = {
            "pointsButton": (self.pointsPage, self.points),
            "mappingButton": (self.mappingPage, self.render_mapping),
            "featureButton": (self.featurePage, self.render_features),
        }
        for name, (page, callback) in obsolete_actions.items():
            button = getattr(self, name, None)
            if button is not None:
                button.clicked.connect(
                    lambda _checked=False, target=page, action=callback:
                    self._show_page(target, action)
                )
        self.sourceRefreshButton.clicked.connect(lambda: self.run(self.sources))
        self.sourceDeleteButton.clicked.connect(lambda: self.run(self.delete_source))
        self.pointsRefreshButton.clicked.connect(lambda: self.run(self.points))
        self.sourceCombo.currentIndexChanged.connect(self._source_changed)
        self.applyCodeButton.clicked.connect(self.apply_same_code)
        self.saveNormalizationButton.clicked.connect(self.save_normalization)
        self.addNormalizationButton.clicked.connect(self.add_normalization_rule)
        self.deleteNormalizationButton.clicked.connect(self.delete_normalization_rule)
        self.saveMappingButton.clicked.connect(self.save_mappings)
        self.saveStorageCodeButton.clicked.connect(
            lambda: self.run(self._save_storage_clicked))
        self.saveDepthCreateButton.clicked.connect(
            lambda: self.run(self._save_depth_clicked))
        self.createOneButton.clicked.connect(lambda: self.run(self.create_draft))
        self.createBatchButton.clicked.connect(lambda: self.run(self.start_selected))
        self.creationModeCombo.currentIndexChanged.connect(
            self._creation_mode_changed
        )
        for table in (self.pointsTable, self.featureTable):
            table.itemChanged.connect(lambda item, target=table: self._point_item_changed(target, item))

    def _show_page(self, page, callback=None):
        self.pages.setCurrentWidget(page)
        if callback:
            self.run(callback)

    def _install_normalization_actions(self):
        actions = QHBoxLayout()
        self.addNormalizationButton = QPushButton("규칙 추가", self.normalizationTab)
        self.deleteNormalizationButton = QPushButton("선택 규칙 삭제", self.normalizationTab)
        actions.addWidget(self.addNormalizationButton)
        actions.addWidget(self.deleteNormalizationButton)
        self.normalizationTab.layout().insertLayout(1, actions)

    def _install_storage_actions(self):
        actions = QHBoxLayout()
        self.saveStorageCodeButton = QPushButton("저장", self.storageCodeTab)
        self.storageSaveStatus = QLabel("저장된 프로젝트 설정을 사용합니다.", self.storageCodeTab)
        actions.addWidget(self.saveStorageCodeButton)
        actions.addWidget(self.storageSaveStatus)
        self.storageCodeTab.layout().addLayout(actions)

    def reset_scope(self):
        state = self.plugin.integration_state()
        scope = (id(self.plugin.active_client), state.get('project_id'), state.get('epoch'))
        if scope != self._session_scope:
            self.stop_creation_queue()
            self._selection.clear(); self._overrides.clear()
            self.point_rows = []; self._project_point_rows = []
            self.pointsTable.setRowCount(0); self.featureTable.setRowCount(0)
            self._session_scope = scope
        ready = bool(state.get("ready"))
        self.setEnabled(ready)
        if ready:
            self.run(lambda: self.sources(refresh_settings=False))
            self.run(self.load_project_settings)
        else:
            self.sourceCombo.clear(); self.statusLabel.setText("로그인 후 GeoFlow 프로젝트를 여세요.")

    def load_project_settings(self, *, refresh_codes=True):
        """Populate project-scoped settings independently of Source selection."""
        normalization_settings, normalization_store = self._normalization_settings()
        mapping_settings, mapping_store = self._standard_mapping_settings()
        storage_settings, storage_store = self._storage_settings()
        depth_settings, depth_store = self._depth_settings()
        stores = {
            "normalization": {
                "file": normalization_settings.fileName(),
                "key": normalization_store,
            },
            "mapping": {
                "file": mapping_settings.fileName(), "key": mapping_store,
            },
            "storage_code": {
                "file": storage_settings.fileName(), "key": storage_store,
            },
            "depth_policy": {
                "file": depth_settings.fileName(), "key": depth_store,
            },
        }
        try:
            if refresh_codes:
                self._load_project_point_rows()
            normalization = read_code_rule_rows(
                normalization_settings, normalization_store
            )
            mappings = self._migrate_saved_mappings()
            storage = read_storage_codes(storage_settings, storage_store)
            depth_policy = read_depth_create_targets(
                depth_settings, depth_store
            )
            self.render_mapping(
                normalization_rules=normalization,
                saved_mappings=mappings,
                saved_storage=storage,
                saved_depth_policy=depth_policy,
            )
            self._code_refresh_log(normalization, mappings, storage)
            self._operation_log(
                "SURVEY_SETTINGS_LOAD",
                normalization_count=len(normalization),
                mapping_count=len(mappings),
                storage_code_count=len(storage),
                depth_policy_count=len(depth_policy),
                source="QSettings",
                stores=stores,
            )
            self._log_l2_options()
            return {
                "normalization_count": len(normalization),
                "mapping_count": len(mappings),
                "storage_code_count": len(storage),
                "depth_policy_count": len(depth_policy),
            }
        except Exception as exc:
            self._operation_log(
                "SURVEY_SETTINGS_LOAD", status="error",
                error_type=type(exc).__name__, error_message=str(exc),
                source="QSettings", stores=stores,
            )
            QgsMessageLog.logMessage(
                "[SURVEY_SETTINGS_LOAD] error=" + json.dumps({
                    "error_type": type(exc).__name__,
                    "error_message": str(exc), "stores": stores,
                }, ensure_ascii=False, sort_keys=True, default=str),
                "GeoFlow", Qgis.MessageLevel.Critical,
            )
            raise

    def _load_project_point_rows(self):
        """Read the authoritative project-wide Survey set used by settings tabs."""
        state = self.plugin.integration_state()
        try:
            _, api = self.controller.context()
            payload = api.points(source_id=None)
            rows = display_rows(payload, "points")
        except Exception as exc:
            self._operation_log(
                "SURVEY_CODE_REFRESH", project_id=state.get("project_id", ""),
                error_type=type(exc).__name__, error_message=str(exc),
            )
            return False
        self._project_point_rows = rows
        return True

    def _code_refresh_log(self, normalization, mappings, storage):
        state = self.plugin.integration_state()
        distinct = {
            self._survey_code(row) for row in self._project_point_rows
            if self._survey_code(row)
        }
        self._operation_log(
            "SURVEY_CODE_REFRESH",
            project_id=state.get("project_id", ""),
            survey_count=len(self._project_point_rows),
            distinct_code_count=len(distinct),
            normalization_rule_count=len(normalization),
            mapping_count=len(mappings),
            storage_code_count=len(storage),
        )

    def _reference_catalog_changed(self):
        """Re-render L2 choices when the asynchronous project catalog arrives."""
        service = getattr(self.plugin, "_reference_service", None)
        if service is None or getattr(service, "state", "") != "ready":
            return
        state = self.plugin.integration_state()
        scope = getattr(service, "scope", None)
        if (not state.get("ready") or
                scope and len(scope) > 2 and str(scope[2]) != str(state.get("project_id"))):
            return
        self.run(lambda: self.load_project_settings(refresh_codes=False))

    def run(self, callback):
        try:
            return callback()
        except Exception as exc:
            status = getattr(exc, "http_status", None)
            message = {403: "이 프로젝트의 Survey 작업 권한이 없습니다.",
                       409: "서버의 Survey 상태가 변경되었습니다. 목록과 Preview를 새로고침하세요.",
                       503: "Survey 서버 작업을 사용할 수 없습니다."}.get(status, str(exc))
            self.statusLabel.setText(message)
            detail = {
                "operation": getattr(callback, '__name__', 'action'),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "error_reason": getattr(exc, "reason", ""),
                "http_status": status,
                "traceback": traceback.format_exc(),
                **getattr(exc, "context", {}),
            }
            QgsMessageLog.logMessage(
                "survey operation failure " + json.dumps(
                    detail, ensure_ascii=False, sort_keys=True, default=str
                ),
                "GeoFlow", Qgis.MessageLevel.Warning)
            return None

    def _debug(self, kind, payload):
        self.debugText.setPlainText(json.dumps({kind: payload}, ensure_ascii=False, indent=2, default=str))

    def sources(self, *, refresh_settings=True):
        _, api = self.controller.context()
        payload = api.sources(include_inactive=True, include_deleted=True)
        all_sources = inventory_rows(payload, "sources")
        rows = [row for row in all_sources if not row.get('deleted_at') and not row.get('is_deleted')]
        point_payload = api.points(source_state='retained')
        if not isinstance(point_payload, dict) or point_payload.get('ok') is False:
            raise ValueError('보존 측점 조회 실패: 이전 이력은 유지됩니다.')
        all_points = inventory_rows(point_payload, 'points')
        self._inventory_incomplete = point_payload.get('truncated', len(all_points) >= 5000)
        known = {str(row['id']) for row in rows}
        self._retained_rows = [row for row in all_points
                              if str(row.get('source_id') or '') not in known]
        self._source_history = [row for row in all_sources if row.get('deleted_at')]
        self._history_supported = payload.get('source_inventory_version') == 1
        selected = self.sourceCombo.currentData()
        self.sourceCombo.blockSignals(True); self.sourceCombo.clear()
        self.sourceCombo.addItem(self.SOURCE_PLACEHOLDER_TEXT, None)
        for row in rows:
            label = f"{row.get('original_file_name', '측량자료')} · 활성 측점 {row.get('point_count', '미확인')}점"
            if not row.get("is_active", True): label += " · 비활성"
            self.sourceCombo.addItem(label, str(row["id"]))
        if self._retained_rows:
            suffix = ' 이상 · 조회 불완전' if self._inventory_incomplete else ''
            self.sourceCombo.addItem(
                f'원본 삭제/출처 미확인 보존 측점 · {len(self._retained_rows)}점{suffix}', self.RETAINED_POINTS)
        self.source_rows = rows
        index = self.sourceCombo.findData(selected)
        self.sourceCombo.setCurrentIndex(index if index > 0 else 0)
        self.sourceCombo.blockSignals(False)
        selectable = self.sourceCombo.count() > 1
        self.sourceCombo.setEnabled(selectable)
        self.sourceCombo.setToolTip(
            "" if selectable else "등록된 측량원시가 없습니다."
        )
        # Refresh always reloads the selected Source. Initial/open state stays
        # on the non-source placeholder and clears all point-derived UI.
        self._source_changed()
        self.statusLabel.setText(f"Source {len(rows)}건" + (" · 5,000점 상한: 보존 목록 조회 불완전" if self._inventory_incomplete else ""))
        self._debug("sources", payload)
        if refresh_settings:
            self.load_project_settings(refresh_codes=True)
        return payload

    def _deleted_sources_key(self):
        _settings, key = self._settings()
        return key + "/source_only_deleted_ids"

    def _deleted_source_ids(self):
        try:
            value = json.loads(str(QSettings().value(
                self._deleted_sources_key(), "[]"
            ) or "[]"))
        except (TypeError, ValueError):
            return set()
        return {str(item) for item in value if item}

    def _source_changed(self):
        if hasattr(self, 'inspection'):
            self.inspection.clear()
            for box in self.inspection.details.values():
                box.clear()
        self.stop_creation_queue()
        retained = self.sourceCombo.currentData() == self.RETAINED_POINTS
        self.sourceDeleteButton.setEnabled(not retained and bool(self.sourceCombo.currentData()))
        self.recentSourceLabel.setText(self.sourceCombo.currentText() or "Source를 선택하세요.")
        self.point_rows = []; self.pointsTable.setRowCount(0); self.featureTable.setRowCount(0)
        self._selection.clear()
        self._overrides.clear()
        has_source = bool(self.sourceCombo.currentData())
        self.createBatchButton.setEnabled(has_source)
        self.createOneButton.setEnabled(has_source)
        if not has_source:
            self.recentSourceLabel.setText(
                "측량원시를 선택하면 측점 목록이 표시됩니다."
            )
            self.statusLabel.setText("측량원시를 선택하세요.")
            return
        self.run(self.points)

    def current_source_id(self):
        value = self.sourceCombo.currentData()
        if value == self.RETAINED_POINTS:
            raise ValueError("보존된 Survey Point 모음은 Source 삭제 대상이 아닙니다.")
        if not value: raise ValueError("먼저 Source를 선택하세요.")
        return str(UUID(str(value)))

    @staticmethod
    def _delete_reason(reason):
        return {
            'version_lineage': '다른 Source 버전과 계보로 연결되어 있습니다.',
            'inactive_source': '비활성 Source는 삭제할 수 없습니다.',
            'shared_object': '원본 파일을 다른 Source가 함께 사용하고 있습니다.',
            'invalid_object_key': '원본 파일 저장 키가 유효하지 않습니다.',
        }.get(str(reason or ''), str(reason or '서버 정책상 삭제할 수 없습니다.'))

    @staticmethod
    def _operation_log(prefix, **fields):
        for name, value in fields.items():
            QgsMessageLog.logMessage(
                f"[{prefix}] {name}={value}", "GeoFlow", Qgis.MessageLevel.Info
            )

    def _confirm_source_delete(self, message):
        return QMessageBox.question(self, 'Source·측점 논리 삭제', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def delete_source(self):
        source_id = self.current_source_id()
        payload, check = self.controller.source_delete_precheck(source_id)
        if not check['can_delete']:
            raise ValueError(self._delete_reason(check.get('blocked_reason')))
        if not self._confirm_source_delete(
            f"원본 Source와 소속 활성 측점 {check['point_count']}점을 논리 삭제합니다.\n"
            "측점은 활성 목록에서 사라집니다. GIS 시설물은 유지됩니다. 계속하시겠습니까?"):
            return
        result = self.controller.delete_source(source_id)
        # Never register deleted observations as retained, even after refresh failure.
        self.point_rows = []
        self.pointsTable.setRowCount(0)
        self.featureTable.setRowCount(0)
        self.sourceCombo.setCurrentIndex(0)
        _, api = self.controller.context()
        readback = api.points(source_id=source_id)
        if not isinstance(readback, dict) or readback.get('ok') is not True:
            raise RuntimeError('삭제 응답 수신 후 재조회 실패. 자동 재시도하지 마세요.')
        remaining = inventory_rows(readback, 'points')
        self.sources(refresh_settings=False)
        self.statusLabel.setText(
            f"Source 논리 삭제 · 응답상 측점 {result['survey_points_deleted']}점 삭제 · 재조회 활성 {len(remaining)}점"
            + (' · 원본 파일 정리 대기' if result.get('cleanup_pending') else '')
            + (' · Delta 갱신 대기' if result.get('revision_refresh_pending') else ''))

    def points(self):
        if not self.sourceCombo.currentData():
            self.point_rows = []
            self.pointsTable.setRowCount(0)
            self.featureTable.setRowCount(0)
            self.createBatchButton.setEnabled(False)
            return {"results": []}
        _, api = self.controller.context()
        retained = self.sourceCombo.currentData() == self.RETAINED_POINTS
        payload = api.points(source_id=None if retained else self.current_source_id(),
                             source_state='retained' if retained else None)
        self.point_rows = inventory_rows(payload, "points")
        if not isinstance(payload, dict) or payload.get('ok') is False:
            raise ValueError('측점 조회 실패')
        incomplete = payload.get('truncated', len(self.point_rows) >= 5000)
        if retained:
            known = {str(row['id']) for row in self.source_rows}
            self.point_rows = [row for row in self.point_rows if str(row.get('source_id') or '') not in known]
        self._inventory_incomplete = incomplete
        self._fill_points(self.pointsTable, self.point_rows)
        self._fill_points(self.featureTable, self.point_rows)
        self.createBatchButton.setEnabled(bool(self.point_rows))
        dates = sorted({str(row['survey_date'])[:10] for row in self.point_rows if row.get('survey_date')})
        workers = {str(row['worker_id']) for row in self.point_rows if row.get('worker_id')}
        self.recentSourceLabel.setText(self.sourceCombo.currentText() + '\n측량기간: ' +
            (f'{dates[0]} ~ {dates[-1]}' if dates else '응답에 날짜 없음') +
            f" · 작업자 {len(workers)}명 (조회된 {len(self.point_rows)}점 기준)")
        self.statusLabel.setText(f"측량점 {len(self.point_rows)}건" + (" · 5,000점 상한: 조회 불완전, 전체 범위 확인 불가" if incomplete else ""))
        self._debug("points", payload)
        return payload

    def _creation_state(self, point):
        recommendation = self._point_mapping(point)
        standard = str(recommendation.get("layer") or "").upper()
        code = self._display_storage_code(recommendation)
        layer = next((item for item in self.plugin._managed_layers()
                      if str(item.customProperty("geoflow/standard_name", "")).upper() == standard), None)
        if layer is None or not code or not self._valid_point_coordinates(point):
            # Detailed mapping validation runs before any edits in preflight.
            return '대상/좌표 설정 필요', True
        matches = nearby_targets(self.plugin, point, layer, code)
        if matches:
            return ('생성대기' if matches[0]['feature'].id() < 0 else '생성완료'), False
        return '미생성', True

    def _point_item_changed(self, table, item):
        if self._filling or item.column() != 0:
            return
        row = table.item(item.row(), 1).data(Qt.ItemDataRole.UserRole)
        self._selection[str(row['id'])] = item.checkState() == Qt.CheckState.Checked
        other = self.featureTable if table is self.pointsTable else self.pointsTable
        self._filling = True
        for index in range(other.rowCount()):
            source = other.item(index, 1).data(Qt.ItemDataRole.UserRole)
            if str(source['id']) == str(row['id']):
                other.item(index, 0).setCheckState(item.checkState())
        self._filling = False

    def _settings(self):
        state = self.plugin.integration_state()
        return QSettings(), mapping_key(self.plugin.active_client.base_url, state["project_id"])

    def _saved_mappings(self):
        state = self.plugin.integration_state()
        settings = QSettings()
        key = standard_mapping_key(
            self.plugin.active_client.base_url, state["project_id"]
        )
        return read_mappings(settings, key)

    def _standard_mapping_settings(self):
        state = self.plugin.integration_state()
        return QSettings(), standard_mapping_key(
            self.plugin.active_client.base_url, state["project_id"]
        )

    def _normalization_settings(self):
        state = self.plugin.integration_state()
        return QSettings(), normalization_key(
            self.plugin.active_client.base_url, state["project_id"]
        )

    def _code_aliases(self):
        settings, key = self._normalization_settings()
        return read_code_aliases(settings, key)

    def _standard_code(self, raw_code, business_type=""):
        state = self.plugin.integration_state()
        return normalize_raw_code(
            state["project_id"], raw_code, settings=QSettings(),
            origin=self.plugin.active_client.base_url,
            business_type=business_type,
        )

    def _survey_code(self, point):
        persisted = str((point or {}).get("code") or "").strip()
        if persisted:
            return persisted
        business_type = self._business_type_for_point(point)
        try:
            return self._standard_code(
                (point or {}).get("raw_code"), business_type
            )
        except TypeError:
            # Compatibility for installed extensions/tests overriding the old
            # one-argument helper during the transition to L2-aware rules.
            return self._standard_code((point or {}).get("raw_code"))

    def _business_type_for_point(self, point):
        point = point if isinstance(point, dict) else {}
        raw_data = self._metadata_object(point.get("raw_data"))
        for source in (point, raw_data):
            for key in (
                "business_type", "business_code", "work_type_code",
                "survey_work_code", "업무유형", "업무코드",
            ):
                value = str(source.get(key) or "").strip()
                if value:
                    return value
        return ""

    def _storage_settings(self):
        state = self.plugin.integration_state()
        return QSettings(), storage_code_key(
            self.plugin.active_client.base_url, state["project_id"]
        )

    def _storage_codes(self):
        settings, key = self._storage_settings()
        return read_storage_codes(settings, key)

    def _normalize_mapping(self, value):
        value = value if isinstance(value, dict) else {}
        standard = str(value.get("layer") or value.get("standard_name") or "").upper()
        label = str(value.get("facility_label") or "")
        identity = str(value.get("facility_id") or "")
        if standard and label:
            return {
                "facility_id": identity or facility_identity(standard, label),
                "facility_label": label,
                "layer": standard,
            }
        legacy = str(value.get("legacy_ftr_cde") or value.get("ftr_cde") or "")
        resolved = resolve_facility(self._mapping_options(), standard, legacy)
        if resolved:
            return {key: resolved[key] for key in (
                "facility_id", "facility_label", "layer"
            )}
        return {
            "facility_id": identity,
            "facility_label": label or legacy,
            "layer": standard,
            "migration_unresolved": bool(legacy),
        }

    def _migrate_saved_mappings(self):
        """Retain legacy raw mappings and copy unambiguous rows to standard codes."""
        legacy_settings, legacy_key = self._settings()
        legacy = read_mappings(legacy_settings, legacy_key)
        settings, key = self._standard_mapping_settings()
        saved = read_mappings(settings, key)
        alias_settings, alias_key = self._normalization_settings()
        aliases = read_code_aliases(alias_settings, alias_key)
        storage_settings, storage_key = self._storage_settings()
        storage = read_storage_codes(storage_settings, storage_key)
        migrated, changed, aliases_changed = dict(saved), False, False
        candidates = {}
        for raw, value in legacy.items():
            normalized = self._normalize_mapping(value)
            code = aliases.get(str(raw).strip().upper())
            if not code and normalized.get("facility_id"):
                # This is an explicit migration of a known legacy mapping,
                # not a generic raw_code.upper() normalization rule.
                code = str(raw).strip().upper()
                if code:
                    aliases[str(raw).strip().upper()] = code
                    aliases_changed = True
            if code:
                candidates.setdefault(code, []).append(normalized)
            legacy_hint = str(value.get("legacy_ftr_cde") or "")
            resolved = resolve_facility(
                self._mapping_options(), normalized.get("layer"), legacy_hint
            ) if legacy_hint else None
            if resolved:
                identity = resolved["facility_id"]
                if identity not in storage:
                    storage[identity] = {
                        **resolved,
                        "standard_name": resolved["layer"],
                        "storage_field": "ftr_cde",
                    }
                    changed = True
            if (normalized.get("facility_id") and
                    not normalized.get("migration_unresolved")):
                changed = changed or bool(legacy_hint)
        for code, rows in candidates.items():
            signatures = {
                (str(row.get("facility_id") or ""),
                 str(row.get("facility_label") or ""),
                 str(row.get("layer") or ""))
                for row in rows
                if row.get("facility_id") and not row.get("migration_unresolved")
            }
            if code not in migrated and len(signatures) == 1:
                migrated[code] = next(
                    row for row in rows
                    if (str(row.get("facility_id") or ""),
                        str(row.get("facility_label") or ""),
                        str(row.get("layer") or "")) in signatures
                )
                changed = True
        if changed:
            write_mappings(settings, key, migrated)
        if aliases_changed:
            write_code_aliases(alias_settings, alias_key, aliases)
        if changed:
            write_storage_codes(storage_settings, storage_key, storage)
        return migrated

    def _point_mapping(self, row):
        code = self._survey_code(row)
        if standard_code_role(code) in {"ELEVATION_REFERENCE", "ROAD"}:
            return {
                "facility_id": "", "facility_label": "", "layer": "",
                "standard_code": code,
                "normalization_unresolved": not bool(code),
            }
        if str(row['id']) in self._overrides:
            result = self._normalize_mapping(self._overrides[str(row['id'])])
            result["standard_code"] = code
            return result
        result = self._normalize_mapping(
            self._saved_mappings().get(code, {}) if code else {}
        )
        result["standard_code"] = code
        result["normalization_unresolved"] = not bool(code)
        return result

    def _display_storage_code(self, recommendation):
        identity = str(recommendation.get("facility_id") or "")
        return str(self._storage_codes().get(identity, {}).get("storage_code") or "")

    def _fill_points(self, table, rows):
        self._filling = True
        sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)
        table.clear(); table.setColumnCount(len(self.POINT_COLUMNS)); table.setHorizontalHeaderLabels(self.POINT_COLUMNS)
        decorated = []
        for row in rows:
            recommendation = self._point_mapping(row)
            facility = str(recommendation.get("facility_label") or "").strip()
            code = str(self._survey_code(row) or "").strip()
            survey_no = str(row.get("survey_no") or row.get("source_row_id") or "")
            confirmed = bool(
                facility and recommendation.get("layer")
                and not recommendation.get("migration_unresolved")
            )
            key = ((0, facility.casefold(), survey_no.casefold()) if confirmed
                   else (1, code.casefold(), survey_no.casefold()))
            decorated.append((key, row, recommendation))
        decorated.sort(key=lambda value: value[0])
        table.setRowCount(len(decorated))
        for r, (_key, row, recommendation) in enumerate(decorated):
            state, eligible = self._creation_state(row)
            mapped = resolve_facility(
                self._mapping_options(), recommendation.get("layer"),
                recommendation.get("facility_label"),
            ) is not None and not recommendation.get("migration_unresolved")
            target_layer = next((l for l in self.plugin._managed_layers()
                if l.customProperty('geoflow/standard_name') == recommendation.get('layer')), None)
            mapped = mapped and target_layer is not None and QgsWkbTypes.flatType(target_layer.wkbType()) == QgsWkbTypes.Type.Point
            mapped = mapped and self._valid_point_coordinates(row)
            checked = eligible and mapped and self._selection.get(str(row['id']), True)
            values = (
                "", row.get("survey_no") or "번호 없음",
                self._survey_code(row) or "",
                recommendation.get("facility_label", ""),
                row.get("x") if row.get("x") is not None else "좌표 없음",
                row.get("y") if row.get("y") is not None else "좌표 없음",
                row.get("z") if row.get("z") is not None else "좌표 없음",
                "●",
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if c == 0:
                    item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
                    if not eligible: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 1: item.setData(Qt.ItemDataRole.UserRole, row)
                if c == 7:
                    created = state == "생성완료"
                    item.setForeground(QColor("#16823b" if created else "#8a8f98"))
                    item.setToolTip("생성됨" if created else "미생성")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(sorting)
        self._filling = False

    def _mapping_options(self):
        service = getattr(self.plugin, "_reference_service", None)
        return ftr_catalog(getattr(service, "catalog", {}) or {})

    def _layer_display_name(self, standard):
        standard = str(standard or "").upper()
        manifest = (getattr(self.plugin, "active_context", None) or {}).get(
            "manifest", {}
        ) or {}
        layers = manifest.get("layers") or manifest.get("layer_definitions") or []
        label = next((
            row.get("label") or row.get("display_name") or row.get("name")
            for row in layers if isinstance(row, dict)
            and str(row.get("standard_name") or "").upper() == standard
        ), None)
        if label:
            return str(label)
        layer = next((
            item for item in self.plugin._managed_layers()
            if str(item.customProperty("geoflow/standard_name", "")).upper()
            == standard
        ), None)
        return layer.name() if layer is not None else standard

    def _business_type_catalog(self):
        """Return the explicit project-active L2 list and its central source."""
        service = getattr(self.plugin, "_reference_service", None)
        catalog = getattr(service, "catalog", {}) or {}
        manifest = (getattr(self.plugin, "active_context", None) or {}).get(
            "manifest", {}
        ) or {}
        project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
        rows, source = [], ""
        for container_name, container in (
                ("reference_catalog", catalog),
                ("project_definition", project),
                ("manifest", manifest)):
            for key in (
                    "business_types", "project_l2", "active_l2",
                    "business_scopes", "l2"):
                value = container.get(key)
                if isinstance(value, list):
                    rows, source = value, f"{container_name}.{key}"
                    break
            if source:
                break
        if not source:
            for group in catalog.get("groups") or []:
                if not isinstance(group, dict):
                    continue
                group_key = str(group.get("code_group_key") or "").upper()
                if ("L2" in group_key or
                        group_key in {"BUSINESS_TYPE", "WORK_TYPE"}):
                    rows = group.get("values") or []
                    source = f"reference_catalog.groups.{group_key}"
                    break
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or row.get("id") or row.get("value") or "").strip()
            label = str(row.get("label") or row.get("name") or code).strip()
            if code and (code, label) not in result:
                result.append((code, label))
        error = "" if result else (
            str(getattr(service, "error", "") or "project_active_l2_missing")
        )
        return result, source or "unavailable", error

    def _business_type_options(self):
        return self._business_type_catalog()[0]

    def _log_l2_options(self):
        options, source, error = self._business_type_catalog()
        state = self.plugin.integration_state()
        fields = {
            "project_id": state.get("project_id", ""),
            "l2_count": len(options),
            "l2_labels": [label for _code, label in options],
            "source": source,
        }
        if error:
            fields["error"] = error
        self._operation_log("SURVEY_L2_LOAD", **fields)

    def _depth_settings(self):
        state = self.plugin.integration_state()
        return QSettings(), depth_create_key(
            self.plugin.active_client.base_url, state["project_id"]
        )

    def _depth_create_targets(self):
        settings, key = self._depth_settings()
        stored = read_depth_create_targets(settings, key)
        valid, unresolved, changed = set(), set(), False
        for standard, value in stored:
            resolved = resolve_facility(self._mapping_options(), standard, value)
            if resolved:
                valid.add((standard, resolved["storage_code"]))
                changed = changed or resolved["storage_code"] != value
            else:
                unresolved.add((standard, value))
        self._unresolved_depth_targets = unresolved
        if changed:
            write_depth_create_targets(settings, key, valid | unresolved)
        return valid

    def _install_depth_create_options(self):
        self.depthCreateGroup = QGroupBox(
            "시설물 생성 시 심도 동시생성 대상", self.depthCreateTab
        )
        layout = QVBoxLayout(self.depthCreateGroup)
        self.depthCreateList = QListWidget(self.depthCreateGroup)
        self.depthCreateList.setToolTip(
            "선택한 레이어/FTR_CDE로 시설물을 만들 때 WTL_PIPE_PS 심도도 함께 생성합니다."
        )
        layout.addWidget(self.depthCreateList)
        actions = QHBoxLayout()
        self.saveDepthCreateButton = QPushButton("저장", self.depthCreateGroup)
        self.depthSaveStatus = QLabel("저장된 프로젝트 설정을 사용합니다.", self.depthCreateGroup)
        actions.addWidget(self.saveDepthCreateButton)
        actions.addWidget(self.depthSaveStatus)
        layout.addLayout(actions)
        self.depthCreateLayout.addWidget(self.depthCreateGroup)
        self.depthCreateList.itemChanged.connect(self._depth_option_changed)

    def _depth_option_changed(self, _item):
        self.depthSaveStatus.setText("저장되지 않은 변경 사항")

    def _render_depth_create_options(self, options=None):
        options = options if options is not None else self._mapping_options()
        selected = self._depth_create_targets()
        storage = self._storage_codes()
        self.depthCreateList.blockSignals(True)
        self.depthCreateList.clear()
        try:
            configured_rows = []
            for identity, row in storage.items():
                code = str(row.get("storage_code") or "")
                label = str(row.get("facility_label") or identity)
                standard = str(row.get("standard_name") or "").upper()
                if code and standard:
                    configured_rows.append((code, label, standard))
            for code, label, standard in sorted(configured_rows, key=lambda value: (value[2], value[1])):
                if str(standard).upper() == "WTL_PIPE_PS":
                    continue
                item = QListWidgetItem(
                    f"{label or code} · {code} · {standard}", self.depthCreateList
                )
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    (str(standard).upper(), str(code)),
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if (str(standard).upper(), str(code)) in selected
                    else Qt.CheckState.Unchecked
                )
            configured_keys = {(standard, code) for code, _label, standard in configured_rows}
            for standard, value in sorted(getattr(self, "_unresolved_depth_targets", set())):
                if (standard, value) in configured_keys:
                    continue
                item = QListWidgetItem(
                    f"{value} · {standard} · 재선택 필요", self.depthCreateList
                )
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        finally:
            self.depthCreateList.blockSignals(False)
        self.depthSaveStatus.setText("저장된 설정 로드 완료")

    def _save_depth_create_options(self):
        targets = set()
        for row in range(self.depthCreateList.count()):
            item = self.depthCreateList.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                targets.add(tuple(item.data(Qt.ItemDataRole.UserRole)))
        settings, key = self._depth_settings()
        write_depth_create_targets(settings, key, targets)
        return targets

    def save_depth_create_options(self):
        targets = self._save_depth_create_options()
        state = self.plugin.integration_state()
        for standard, code in sorted(targets):
            self._operation_log(
                "SURVEY_DEPTH_CONFIG", project_id=state.get("project_id", ""),
                target_layer=standard, ftr_cde=code, enabled=True, saved=True,
            )
        self.depthSaveStatus.setText("저장 완료")
        self.statusLabel.setText("심도 생성 설정을 현재 프로젝트에 저장했습니다.")
        return targets

    def _save_depth_clicked(self):
        try:
            return self.save_depth_create_options()
        except Exception:
            self.depthSaveStatus.setText("저장 실패")
            raise

    def render_mapping(self, *, normalization_rules=None, saved_mappings=None,
                       saved_storage=None, saved_depth_policy=None):
        options = self._mapping_options()
        saved = (saved_mappings if saved_mappings is not None
                 else self._migrate_saved_mappings())
        self._render_normalization(normalization_rules)
        standard_codes = sorted({
            self._survey_code(row)
            for row in self._project_point_rows
            if self._survey_code(row)
        } | set(saved))
        self.mappingTable.clear(); self.mappingTable.setColumnCount(3)
        self.mappingTable.setHorizontalHeaderLabels(
            ["Survey Code", "시설물", "대상 레이어"]
        )
        self.mappingTable.setRowCount(len(standard_codes))
        for r, code_value in enumerate(standard_codes):
            role = standard_code_role(code_value)
            code_item = QTableWidgetItem(code_value)
            code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mappingTable.setItem(r, 0, code_item)
            combo = QComboBox(self.mappingTable); combo.addItem("선택 안 함", ("", "", ""))
            seen = set()
            for code, label, layer in options:
                identity = facility_identity(layer, label or code)
                if identity in seen:
                    continue
                seen.add(identity)
                combo.addItem(
                    f"{label or code} · {self._layer_display_name(layer)}",
                    (identity, label or code, layer),
                )
            wanted = self._normalize_mapping(
                saved.get(code_value, {})
                if role not in {"ELEVATION_REFERENCE", "ROAD"} else {}
            )
            wanted_data = (
                wanted.get("facility_id", ""), wanted.get("facility_label", ""),
                wanted.get("layer", ""),
            )
            index = combo.findData(wanted_data)
            if index < 0 and all(wanted_data):
                combo.addItem(
                    f"{wanted_data[1]} · {self._layer_display_name(wanted_data[2])}"
                    " · 저장값",
                    wanted_data,
                )
                index = combo.count() - 1
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setEnabled(role not in {"ELEVATION_REFERENCE", "ROAD"})
            self.mappingTable.setCellWidget(r, 1, combo)
            layer_item = QTableWidgetItem(
                self._layer_display_name(wanted.get("layer", ""))
                if wanted.get("layer") else ""
            )
            layer_item.setData(
                Qt.ItemDataRole.UserRole, wanted.get("layer", "")
            )
            layer_item.setFlags(
                layer_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            self.mappingTable.setItem(r, 2, layer_item)
            combo.currentIndexChanged.connect(
                lambda _i, row=r, box=combo:
                self._mapping_layer_changed(row, box)
            )
        self.mappingTable.resizeColumnsToContents()
        self._render_storage_codes(
            options, saved=saved_storage, depth_targets=saved_depth_policy
        )
        self._render_depth_create_options(options)
        if not options: self.statusLabel.setText("중앙 참조코드에서 FTR_CDE 바인딩을 찾지 못했습니다. 임의 코드를 만들지 않습니다.")

    def _mapping_layer_changed(self, row, combo):
        data = combo.currentData()
        standard = data[2] if isinstance(data, (tuple, list)) and len(data) >= 3 else ""
        item = self.mappingTable.item(row, 2)
        item.setText(self._layer_display_name(standard) if standard else "")
        item.setData(Qt.ItemDataRole.UserRole, standard)

    def _render_normalization(self, rules=None):
        if rules is None:
            settings, key = self._normalization_settings()
            rules = read_code_rule_rows(settings, key)
        else:
            rules = [dict(row) for row in rules]
        observed = {
            (self._business_type_for_point(row),
             str(row.get("raw_code") or row.get("code") or "").strip().upper())
            for row in self._project_point_rows
            if str(row.get("raw_code") or row.get("code") or "").strip()
        }
        configured = {(row["business_type"], row["raw_code"]) for row in rules}
        rules.extend({
            "business_type": business, "raw_code": raw,
            "survey_code": raw, "enabled": False,
        } for business, raw in sorted(observed)
                     if (business, raw) not in configured)
        self.normalizationTable.clear()
        self.normalizationTable.setColumnCount(4)
        self.normalizationTable.setHorizontalHeaderLabels(
            ["업무유형", "원시코드", "Survey Code", "사용"]
        )
        self.normalizationTable.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            business = QComboBox(self.normalizationTable)
            business.addItem("공통", "")
            for code, label in self._business_type_options():
                business.addItem(f"{label} · {code}", code)
            saved_business = str(rule.get("business_type") or "")
            index = business.findData(saved_business)
            if index < 0 and saved_business:
                business.addItem(
                    f"{saved_business} · 저장값/현재 프로젝트 비활성",
                    saved_business,
                )
                index = business.count() - 1
            business.setCurrentIndex(index if index >= 0 else 0)
            self.normalizationTable.setCellWidget(row, 0, business)
            self.normalizationTable.setItem(
                row, 1, QTableWidgetItem(rule["raw_code"])
            )
            self.normalizationTable.setItem(
                row, 2, QTableWidgetItem(rule["survey_code"])
            )
            enabled = QCheckBox(self.normalizationTable)
            enabled.setChecked(bool(rule.get("enabled", False)))
            self.normalizationTable.setCellWidget(row, 3, enabled)
        self.normalizationTable.resizeColumnsToContents()

    def save_normalization(self):
        rules = []
        seen = set()
        for row in range(self.normalizationTable.rowCount()):
            business = str(
                self.normalizationTable.cellWidget(row, 0).currentData() or ""
            )
            raw = self.normalizationTable.item(row, 1).text().strip().upper()
            code = self.normalizationTable.item(row, 2).text().strip().upper()
            if code:
                identity = (business, raw)
                if identity in seen:
                    raise ValueError(f"업무유형={business}, raw_code={raw} 규칙이 중복되었습니다.")
                seen.add(identity)
                rules.append({
                    "business_type": business, "raw_code": raw,
                    "survey_code": code,
                    "enabled": self.normalizationTable.cellWidget(row, 3).isChecked(),
                })
        settings, key = self._normalization_settings()
        write_code_rule_rows(settings, key, rules)
        self.statusLabel.setText("프로젝트 코드 정규화 설정을 저장했습니다.")
        self.render_mapping()
        self._fill_points(self.pointsTable, self.point_rows)
        self._fill_points(self.featureTable, self.point_rows)

    def add_normalization_rule(self):
        row = self.normalizationTable.rowCount()
        self.normalizationTable.insertRow(row)
        business = QComboBox(self.normalizationTable)
        business.addItem("공통", "")
        for code, label in self._business_type_options():
            business.addItem(f"{label} · {code}", code)
        self.normalizationTable.setCellWidget(row, 0, business)
        self.normalizationTable.setItem(row, 1, QTableWidgetItem(""))
        self.normalizationTable.setItem(row, 2, QTableWidgetItem(""))
        enabled = QCheckBox(self.normalizationTable); enabled.setChecked(True)
        self.normalizationTable.setCellWidget(row, 3, enabled)
        self.normalizationTable.setCurrentCell(row, 1)
        self.normalizationTable.editItem(self.normalizationTable.item(row, 1))

    def delete_normalization_rule(self):
        rows = sorted({item.row() for item in self.normalizationTable.selectedItems()}, reverse=True)
        for row in rows:
            self.normalizationTable.removeRow(row)

    def _render_storage_codes(self, options=None, *, saved=None,
                              depth_targets=None):
        options = options if options is not None else self._mapping_options()
        saved = self._storage_codes() if saved is None else dict(saved)
        depth_targets = (
            self._depth_create_targets()
            if depth_targets is None else set(depth_targets)
        )
        facilities = {}
        for code, label, standard in options:
            identity = facility_identity(standard, label or code)
            facilities.setdefault(identity, {
                "facility_id": identity,
                "facility_label": str(label or code),
                "standard_name": str(standard).upper(),
            })
        for identity, configured in saved.items():
            standard = str(configured.get("standard_name") or "").upper()
            label = str(configured.get("facility_label") or identity)
            if standard:
                facilities.setdefault(identity, {
                    "facility_id": identity,
                    "facility_label": label,
                    "standard_name": standard,
                })
        self.storageCodeTable.clear()
        self.storageCodeTable.setColumnCount(4)
        self.storageCodeTable.setHorizontalHeaderLabels([
            "시설물", "대상 레이어", "저장 FTR_CDE", "심도 동시생성",
        ])
        self.storageCodeTable.setRowCount(len(facilities))
        for row, (identity, facility) in enumerate(sorted(
                facilities.items(), key=lambda item: (
                    item[1]["standard_name"], item[1]["facility_label"]
                ))):
            standard = facility["standard_name"]
            self.storageCodeTable.setItem(row, 0, QTableWidgetItem(facility["facility_label"]))
            self.storageCodeTable.item(row, 0).setData(Qt.ItemDataRole.UserRole, identity)
            layer_item = QTableWidgetItem(self._layer_display_name(standard))
            layer_item.setData(Qt.ItemDataRole.UserRole, standard)
            layer_item.setFlags(layer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.storageCodeTable.setItem(row, 1, layer_item)
            combo = QComboBox(self.storageCodeTable)
            combo.addItem("선택 안 함", ("", ""))
            for code, label, layer in options:
                if str(layer).upper() == standard:
                    combo.addItem(f"{code} · {label or code}", (str(code), str(label or code)))
            configured = saved.get(identity, {})
            index = combo.findData((
                configured.get("storage_code", ""), configured.get("code_label", "")
            ))
            if index < 0 and configured.get("storage_code"):
                index = next((i for i in range(combo.count())
                              if combo.itemData(i)[0] == configured["storage_code"]), -1)
            if index < 0 and configured.get("storage_code"):
                stored_code = str(configured["storage_code"])
                stored_label = str(configured.get("code_label") or stored_code)
                combo.addItem(
                    f"{stored_code} · {stored_label} · 저장값/중앙 미확인",
                    (stored_code, stored_label),
                )
                index = combo.count() - 1
            combo.setCurrentIndex(index if index >= 0 else 0)
            self.storageCodeTable.setCellWidget(row, 2, combo)
            depth_enabled = QCheckBox(self.storageCodeTable)
            depth_enabled.setChecked(
                standard != "WTL_PIPE_PS"
                and (standard, str(configured.get("storage_code") or ""))
                in depth_targets
            )
            depth_enabled.setEnabled(standard != "WTL_PIPE_PS")
            depth_enabled.setToolTip(
                "시설물 + 심도 동시 생성 모드에서만 WTL_PIPE_PS를 함께 생성합니다."
            )
            depth_enabled.stateChanged.connect(
                lambda _state: self.storageSaveStatus.setText("저장되지 않은 변경 사항")
            )
            self.storageCodeTable.setCellWidget(row, 3, depth_enabled)
            combo.currentIndexChanged.connect(
                lambda _i, table_row=row, box=combo:
                self._storage_combo_changed(table_row, box)
            )
        self.storageCodeTable.resizeColumnsToContents()
        self.storageSaveStatus.setText("저장된 설정 로드 완료")

    def _storage_combo_changed(self, row, combo):
        del row, combo
        self.storageSaveStatus.setText("저장되지 않은 변경 사항")

    def save_storage_codes(self):
        storage_settings, storage_key = self._storage_settings()
        storage = read_storage_codes(storage_settings, storage_key)
        depth_targets = set()
        state = self.plugin.integration_state()
        for row in range(self.storageCodeTable.rowCount()):
            identity = str(self.storageCodeTable.item(row, 0).data(Qt.ItemDataRole.UserRole) or "")
            standard = str(
                self.storageCodeTable.item(row, 1).data(Qt.ItemDataRole.UserRole)
                or ""
            ).upper()
            label = self.storageCodeTable.item(row, 0).text().strip()
            code, code_label = self.storageCodeTable.cellWidget(row, 2).currentData()
            if code:
                storage[identity] = {
                    "facility_id": identity, "facility_label": label,
                    "standard_name": standard, "storage_field": "ftr_cde",
                    "storage_code": code, "code_label": code_label,
                }
            else:
                storage.pop(identity, None)
            self._operation_log(
                "SURVEY_STORAGE_CONFIG", project_id=state.get("project_id", ""),
                facility_identity=identity, target_layer=standard,
                field="ftr_cde", code=code, saved=True,
            )
            if (code and standard != "WTL_PIPE_PS"
                    and self.storageCodeTable.cellWidget(row, 3).isChecked()):
                depth_targets.add((standard, str(code)))
        write_storage_codes(storage_settings, storage_key, storage)
        depth_settings, depth_key = self._depth_settings()
        write_depth_create_targets(depth_settings, depth_key, depth_targets)
        self.storageSaveStatus.setText("저장 완료")
        self.statusLabel.setText("저장 코드를 현재 프로젝트에 저장했습니다.")
        self._render_depth_create_options(self._mapping_options())
        self._fill_points(self.pointsTable, self.point_rows)
        self._fill_points(self.featureTable, self.point_rows)
        return storage

    def _save_storage_clicked(self):
        try:
            return self.save_storage_codes()
        except Exception:
            self.storageSaveStatus.setText("저장 실패")
            raise

    def apply_same_code(self):
        # The basis is the current mapping row, never the checked point rows.
        # Missing/invalid input is ordinary UI validation and must not escape
        # into QGIS' Python error dialog.
        if self._applying_same_code:
            return
        self._applying_same_code = True
        self.applyCodeButton.setEnabled(False)
        try:
            current = self.mappingTable.currentIndex()
            row = current.row() if current.isValid() else -1
            code_item = self.mappingTable.item(row, 0) if row >= 0 else None
            if code_item is None:
                self.statusLabel.setText("먼저 적용 기준이 될 측량점 행을 선택하세요.")
                return

            code_value = code_item.text().strip()
            if not code_value:
                self.statusLabel.setText("선택한 행에는 표준 code가 없습니다.")
                return
            if standard_code_role(code_value) in {
                    "ELEVATION_REFERENCE", "ROAD"}:
                self.statusLabel.setText(
                    f"표준 code={code_value}는 시설물 생성 대상이 아닙니다."
                )
                return

            matching_points = [
                point for point in self.point_rows
                if self._survey_code(point) == code_value
            ]
            if not matching_points:
                self.statusLabel.setText("같은 코드에 적용할 다른 측량점이 없습니다.")
                return

            combo = self.mappingTable.cellWidget(row, 1)
            data = combo.currentData() if combo is not None else None
            if not isinstance(data, (tuple, list)) or len(data) < 3:
                self.statusLabel.setText("먼저 시설물과 대상 레이어를 선택하세요.")
                return
            identity, label, layer = data[:3]
            if not identity or not label or not layer:
                self.statusLabel.setText("먼저 시설물과 대상 레이어를 선택하세요.")
                return

            settings, key = self._standard_mapping_settings()
            values = read_mappings(settings, key)
            values[code_value] = {
                "facility_id": identity, "facility_label": label, "layer": layer,
            }
            write_mappings(settings, key, values)
            self.statusLabel.setText(f"표준 code={code_value}인 모든 측량점에 {label} 추천을 적용했습니다.")
            self._fill_points(self.pointsTable, self.point_rows)
            self._fill_points(self.featureTable, self.point_rows)
            self._restore_mapping_selection(code_value)
        finally:
            self._applying_same_code = False
            self.applyCodeButton.setEnabled(True)

    def _restore_mapping_selection(self, standard_code):
        """Keep the mapping basis stable across dependent table refreshes."""
        for row in range(self.mappingTable.rowCount()):
            item = self.mappingTable.item(row, 0)
            if item is not None and item.text().strip() == standard_code:
                self.mappingTable.setCurrentCell(row, 0)
                self.mappingTable.selectRow(row)
                self.mappingTable.scrollToItem(item)
                return

    def save_mappings(self):
        settings, key = self._standard_mapping_settings()
        values = read_mappings(settings, key)
        for row in range(self.mappingTable.rowCount()):
            code_value = self.mappingTable.item(row, 0).text()
            identity, label, layer = self.mappingTable.cellWidget(row, 1).currentData()
            if identity and label and layer:
                values[code_value] = {
                    "facility_id": identity, "facility_label": label, "layer": layer,
                }
        write_mappings(settings, key, values)
        self._fill_points(self.pointsTable, self.point_rows)
        self._fill_points(self.featureTable, self.point_rows)
        self.statusLabel.setText("프로젝트 범위 로컬 추천 매핑을 저장했습니다. 자동 확정값이 아닙니다.")

    def render_features(self):
        if not self.point_rows and self.sourceCombo.currentData():
            self.points()
        self._fill_points(self.featureTable, self.point_rows)

    def _creation_mode(self):
        return str(
            self.creationModeCombo.currentData() or self.CREATE_FACILITY_ONLY
        )

    def _creation_mode_changed(self, _index=None):
        if self._creation_mode() == self.CREATE_FACILITY_WITH_DEPTH:
            self.featureNotice.setText(
                "시설물 + 심도 동시 생성 · 저장코드 탭에서 체크한 시설물만 "
                "WTL_PIPE_PS를 함께 생성합니다."
            )
        else:
            self.featureNotice.setText(
                "시설물만 생성 · 확정시설물과 생성상태를 확인하세요."
            )

    @staticmethod
    def _metadata_object(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _is_exposed_pipe_survey(self, point):
        """Resolve the stable L3 workflow code without comparing UI labels."""
        point = point if isinstance(point, dict) else {}
        sources = [point, self._metadata_object(point.get("raw_data"))]
        source_id = str(point.get("source_id") or "")
        source = next((
            row for row in self.source_rows
            if str(row.get("id") or "") == source_id
        ), None)
        if source is None and self.sourceCombo.currentData() != self.RETAINED_POINTS:
            selected_id = str(self.sourceCombo.currentData() or "")
            source = next((
                row for row in self.source_rows
                if str(row.get("id") or "") == selected_id
            ), None)
        if isinstance(source, dict):
            sources.extend([
                source,
                self._metadata_object(source.get("calibration_info")),
                self._metadata_object(source.get("metadata")),
            ])
        keys = (
            "survey_work_code", "survey_type_code", "work_type_code",
            "business_code", "survey_category_code", "survey_kind",
            "survey_category", "측량종류코드", "측량종류", "업무코드",
        )
        return any(
            str(container.get(key) or "").strip().upper()
            == self.EXPOSED_PIPE_SURVEY_CODE
            for container in sources for key in keys
        )

    def _selected_point(self, table=None):
        table = table or self.pointsTable; row = table.currentRow()
        if row < 0 or table.item(row, 1) is None: raise ValueError("측량점 행을 선택하세요.")
        return table.item(row, 1).data(Qt.ItemDataRole.UserRole)

    def create_draft(self):
        try:
            return self._create_draft()
        except Exception:
            index = self.featureTable.currentRow()
            if index >= 0 and self.featureTable.item(index, 7) is not None:
                self.featureTable.item(index, 7).setToolTip('오류')
            raise

    def _new_target_feature(self, layer, point, ftr_cde, *, null_status=False):
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), layer.crs(),
            QgsProject.instance(),
        )
        projected = transform.transform(QgsPointXY(
            float(point['longitude']), float(point['latitude'])
        ))
        feature = QgsVectorLayerUtils.createFeature(
            layer, QgsGeometry.fromPointXY(projected)
        )
        id_index = layer.fields().indexOf('id')
        if id_index < 0:
            raise ValueError('시설물 UUID 필드가 없습니다.')
        try:
            target_id = str(UUID(str(feature['id'])))
        except (ValueError, TypeError):
            target_id = str(uuid4())
            feature.setAttribute(id_index, target_id)
        ftr_index = next((
            i for i, field in enumerate(layer.fields())
            if field.name().casefold() == "ftr_cde"
        ), -1)
        if ftr_index < 0:
            raise ValueError("대상 레이어에 FTR_CDE 물리 필드가 없습니다.")
        feature.setAttribute(ftr_index, ftr_cde)
        inherited = apply_target_inheritance(
            feature,
            layer,
            point,
            project_id=str((self.plugin.active_context or {}).get("project_id") or ""),
        )
        QgsMessageLog.logMessage(
            "survey_target_inheritance "
            + json.dumps(inherited, ensure_ascii=False, sort_keys=True, default=str),
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        standard = str(layer.customProperty(
            "geoflow/standard_name", ""
        )).upper()
        if null_status or standard == "WTL_PIPE_PS":
            status_index = next((
                i for i, field in enumerate(layer.fields())
                if field.name().casefold() == "status"
            ), -1)
            if status_index >= 0:
                feature.setAttribute(status_index, None)
        return feature, target_id

    def _allowed_storage_codes(self, standard):
        return [
            (str(code), str(label or code))
            for code, label, layer in self._mapping_options()
            if str(layer).upper() == str(standard).upper()
        ]

    def _resolve_storage_code(self, facility_label, standard, batch_context=None):
        batch_context = batch_context or {}
        options = batch_context.get("mapping_options")
        if options is None:
            options = self._mapping_options()
        facility = resolve_facility(
            options, standard, facility_label
        )
        if not facility:
            raise SurveyValidationError(
                "facility_mapping_missing",
                f"{facility_label}/{standard}: 코드/시설물 매핑이 없습니다.",
                project_id=self.plugin.integration_state().get("project_id", ""),
                facility_label=facility_label, target_layer=standard,
                storage_field="ftr_cde",
            )
        storage_map = batch_context.get("storage_map")
        if storage_map is None:
            storage_map = self._storage_codes()
        configured = storage_map.get(facility["facility_id"], {})
        storage_code = str(configured.get("storage_code") or "")
        if not storage_code:
            # Legacy raw mappings mixed display labels/codes in `ftr_cde`.
            # Migrate only an exact, unique central-domain match, including
            # workflows that open the creation page before visiting mapping UI.
            saved_mappings = batch_context.get("facility_map")
            if saved_mappings is None:
                saved_mappings = self._saved_mappings()
            for row in saved_mappings.values():
                legacy = str(row.get("legacy_ftr_cde") or row.get("ftr_cde") or "")
                migrated = resolve_facility(
                    options, row.get("layer"), legacy
                ) if legacy else None
                if migrated and migrated["facility_id"] == facility["facility_id"]:
                    storage_code = migrated["storage_code"]
                    settings, key = self._storage_settings()
                    values = read_storage_codes(settings, key)
                    values[facility["facility_id"]] = {
                        **migrated, "standard_name": migrated["layer"],
                        "storage_field": "ftr_cde",
                    }
                    write_storage_codes(settings, key, values)
                    storage_map[facility["facility_id"]] = values[facility["facility_id"]]
                    break
        if not storage_code:
            raise SurveyValidationError(
                "storage_code_missing",
                f"{facility['facility_label']}의 저장 코드가 설정되지 않았습니다. "
                "'저장 코드' 탭에서 먼저 설정해 주세요.",
                project_id=self.plugin.integration_state().get("project_id", ""),
                facility_label=facility["facility_label"],
                facility_identity=facility["facility_id"],
                target_layer=str(standard).upper(), storage_field="ftr_cde",
                resolved_storage_code="",
            )
        domains = batch_context.get("central_code_domains")
        if domains is None:
            allowed = self._allowed_storage_codes(standard)
        else:
            allowed = list(domains.get(str(standard).upper(), ()))
        if storage_code not in {code for code, _label in allowed}:
            raise SurveyValidationError(
                "storage_code_not_in_central_domain",
                f"현재 저장 코드 {storage_code}는 "
                f"{str(standard).upper()}.ftr_cde 중앙 정의에 존재하지 않습니다.",
                project_id=self.plugin.integration_state().get("project_id", ""),
                facility_label=facility["facility_label"],
                facility_identity=facility["facility_id"],
                target_layer=str(standard).upper(), storage_field="ftr_cde",
                resolved_storage_code=storage_code,
                allowed_central_codes=[code for code, _label in allowed],
            )
        return facility, storage_code, allowed

    def _resolve_point_storage(self, point, facility_label, standard,
                               survey_code=None, batch_context=None):
        try:
            return self._resolve_storage_code(
                facility_label, standard, batch_context=batch_context
            )
        except SurveyValidationError as exc:
            exc.context.update({
                "survey_id": str((point or {}).get("id") or ""),
                "raw_code": str((point or {}).get("raw_code") or ""),
                "survey_code": survey_code or self._survey_code(point),
                "depth_enabled": False,
            })
            raise

    def _depth_storage_code(self):
        standard = "WTL_PIPE_PS"
        allowed = self._allowed_storage_codes(standard)
        configured = {
            str(row.get("storage_code") or "")
            for row in self._storage_codes().values()
            if str(row.get("standard_name") or "").upper() == standard
        }
        valid = sorted(configured & {code for code, _label in allowed})
        if len(valid) == 1:
            return valid[0]
        if len(allowed) == 1:
            return allowed[0][0]
        raise ValueError(
            "WTL_PIPE_PS.ftr_cde의 심도 저장 코드를 중앙 정의에서 "
            "유일하게 확정할 수 없습니다."
        )

    def _depth_create_enabled(self, standard, ftr_cde):
        return (
            str(standard).upper() != "WTL_PIPE_PS"
            and (str(standard).upper(), str(ftr_cde))
            in self._depth_create_targets()
        )

    def _new_depth_target(self, point, managed, *, depth_service=None,
                          depth_ftr_cde=None):
        layer = managed.get("WTL_PIPE_PS")
        if layer is None:
            raise ValueError("현재 프로젝트에서 WTL_PIPE_PS 심도 레이어를 찾지 못했습니다.")
        if QgsWkbTypes.flatType(layer.wkbType()) != QgsWkbTypes.Type.Point:
            raise ValueError("WTL_PIPE_PS 심도 레이어가 Point 레이어가 아닙니다.")
        ftr_cde = depth_ftr_cde or self._depth_storage_code()
        feature, target_id = self._new_target_feature(layer, point, ftr_cde, null_status=True)
        depth_index = layer.fields().indexFromName("pip_dep")
        if depth_index < 0:
            raise ValueError("WTL_PIPE_PS에 pip_dep 물리 필드가 없습니다.")
        if depth_service is None:
            from ..services.depth import DepthService
            depth_service = DepthService(self.plugin)
        result = depth_service.calculate_survey_point(point)
        feature.setAttribute(
            depth_index, result.get("depth") if result.get("ok") else None
        )
        QgsMessageLog.logMessage(
            "survey_depth_create " + json.dumps({
                "survey_id": str(point.get("id") or ""),
                "target_id": target_id,
                "ftr_cde": ftr_cde,
                "calculated": bool(result.get("ok")),
                "pip_dep": result.get("depth") if result.get("ok") else None,
                "reason": result.get("reason") if not result.get("ok") else "",
            }, ensure_ascii=False, sort_keys=True, default=str),
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        return layer, feature, target_id, result

    def _create_draft(self):
        selected_row = self.featureTable.currentRow()
        point = self._selected_point(self.featureTable)
        standard_code = self._survey_code(point)
        _, api = self.controller.context(write=True)
        state, eligible = self._creation_state(point)
        if not eligible:
            raise ValueError(f'주변에 동일 시설물이 존재합니다: {state}')
        recommendation = self._point_mapping(point)
        facility_label = str(recommendation.get("facility_label") or "").strip()
        standard = str(recommendation.get("layer") or "").strip()
        if not standard or not facility_label:
            raise ValueError("먼저 raw_code→시설물→레이어 매핑을 확정하세요.")
        _facility, ftr_cde, _allowed = self._resolve_point_storage(
            point, facility_label, standard, standard_code
        )
        layer = next((item for item in self.plugin._managed_layers()
                      if str(item.customProperty("geoflow/standard_name", "")).upper() == standard.upper()), None)
        if layer is None: raise ValueError("현재 프로젝트에서 대상 레이어를 찾지 못했습니다.")
        if QgsWkbTypes.flatType(layer.wkbType()) != QgsWkbTypes.Type.Point:
            raise ValueError("Survey Point 자동 초안은 Point 레이어에만 사용할 수 있습니다.")
        lon, lat = point.get("longitude"), point.get("latitude")
        if lon is None or lat is None:
            raise ValueError("서버 측량점 응답에 EPSG:4326 longitude/latitude가 없습니다.")
        if not self._valid_point_coordinates(point):
            raise ValueError('측량점의 경도/위도 값이 유효하지 않습니다.')
        if any(item.isModified() for item in self.plugin._managed_layers()):
            raise ValueError('기존 시설물 편집을 먼저 저장하거나 취소하세요.')
        self.plugin._ensure_work()
        if self.plugin.work._dirty_page() is not None:
            raise ValueError('기존 Dynamic Form 입력을 먼저 저장하거나 취소하세요.')
        feature, target_id = self._new_target_feature(
            layer, point, ftr_cde, null_status=False
        )
        if standard.upper() == 'WTL_PIPE_PS':
            from ..services.depth import DepthService
            depth_index = layer.fields().indexFromName('pip_dep')
            if depth_index < 0:
                raise ValueError('WTL_PIPE_PS에 pip_dep 물리 필드가 없습니다.')
            result = DepthService(self.plugin).calculate_survey_point(point)
            feature.setAttribute(depth_index, result.get('depth') if result.get('ok') else None)
        if not layer.isEditable() and not layer.startEditing(): raise RuntimeError("대상 레이어 편집을 시작할 수 없습니다.")
        if not layer.addFeature(feature): raise RuntimeError("시설물 초안을 만들지 못했습니다.")
        self._selection[str(point['id'])] = False
        self.featureTable.item(selected_row, 7).setToolTip('생성중')
        self.featureTable.item(selected_row, 0).setCheckState(Qt.CheckState.Unchecked)
        layer.selectByIds([feature.id()])
        self.plugin._ensure_work(); self.plugin.work.on_feature_selected(layer, feature)
        self.plugin.dock.show(); self.plugin.dock.raise_()
        self.statusLabel.setText("Dynamic Form 초안입니다. 속성을 확인하고 저장하세요.")
        return layer, feature

    @staticmethod
    def _valid_point_coordinates(point):
        import math
        try:
            lon, lat = point['longitude'], point['latitude']
            return (not isinstance(lon, bool) and not isinstance(lat, bool)
                    and math.isfinite(float(lon)) and math.isfinite(float(lat))
                    and -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90)
        except (KeyError, TypeError, ValueError):
            return False

    def refresh_creation_states(self):
        self._fill_points(self.pointsTable, self.point_rows)
        self._fill_points(self.featureTable, self.point_rows)

    def start_selected(self):
        """Validate all selected rows, build all creates, then save once."""
        started_at = perf_counter()
        guard_started = perf_counter()
        managed_layers = list(self.plugin._managed_layers())
        if any(layer.isModified() for layer in managed_layers):
            raise ValueError('기존 시설물 편집을 먼저 저장하거나 취소하세요.')
        work = getattr(self.plugin, 'work', None)
        if work is not None and work._dirty_page() is not None:
            raise ValueError('기존 Dynamic Form 입력을 먼저 저장하거나 취소하세요.')
        initial_guard_ms = (perf_counter() - guard_started) * 1000

        selection_started = perf_counter()
        selected_indexes = [
            row for row in range(self.featureTable.rowCount())
            if self.featureTable.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        selection_collect_ms = (perf_counter() - selection_started) * 1000
        if not selected_indexes:
            raise ValueError('생성할 측량점 행을 체크하세요.')
        creation_mode = self._creation_mode()

        context_started = perf_counter()
        _, api = self.controller.context(write=True)
        context_resolve_ms = (perf_counter() - context_started) * 1000
        batch_context_started = perf_counter()
        managed = {
            str(layer.customProperty('geoflow/standard_name', '')).upper(): layer
            for layer in managed_layers
        }
        mapping_options = self._mapping_options()
        central_code_domains = {}
        for code, label, standard in mapping_options:
            central_code_domains.setdefault(str(standard).upper(), []).append(
                (str(code), str(label or code))
            )
        batch_context = {
            "mapping_options": mapping_options,
            "facility_map": self._saved_mappings(),
            "storage_map": self._storage_codes(),
            "central_code_domains": central_code_domains,
        }
        depth_targets = self._depth_create_targets()
        batch_context_build_ms = (perf_counter() - batch_context_started) * 1000
        resolve_cache = {}
        selected, validation_errors = [], []
        preflight_started = perf_counter()
        checked_count = len(selected_indexes)
        for index in selected_indexes:
            point = self.featureTable.item(index, 1).data(Qt.ItemDataRole.UserRole)
            resolve_started = perf_counter()
            self.statusLabel.setText(
                f"시설물 준비 중 {len(selected) + len(validation_errors) + 1} / {checked_count}"
            )
            try:
                state, eligible = self._creation_state(point)
                if not eligible:
                    raise SurveyValidationError(
                        "survey_not_eligible",
                        f"{point.get('source_row_id')}: {state} 상태로 다시 생성할 수 없습니다.",
                        survey_id=point.get("id", ""), raw_code=point.get("raw_code", ""),
                    )
                standard_code = self._survey_code(point)
                recommendation = self._point_mapping(point)
                facility_label = str(
                    recommendation.get("facility_label") or ""
                ).strip()
                standard = str(
                    recommendation.get("layer") or ""
                ).strip().upper()
                cache_key = (standard, facility_label.casefold())
                if cache_key not in resolve_cache:
                    resolve_cache[cache_key] = self._resolve_point_storage(
                        point, facility_label, standard, standard_code,
                        batch_context=batch_context,
                    )
                facility, code, allowed = resolve_cache[cache_key]
                layer = managed.get(standard)
                if layer is None:
                    raise ValueError(f"{point.get('source_row_id')}: 대상 레이어가 없습니다.")
                if QgsWkbTypes.flatType(layer.wkbType()) != QgsWkbTypes.Type.Point:
                    raise ValueError(f"{point.get('source_row_id')}: Point 레이어가 아닙니다.")
                if not self._valid_point_coordinates(point):
                    raise ValueError(f"{point.get('source_row_id')}: 좌표가 유효하지 않습니다.")
                depth_enabled = (
                    creation_mode == self.CREATE_FACILITY_WITH_DEPTH
                    and standard != "WTL_PIPE_PS"
                    and (standard, str(code)) in depth_targets
                )
                planned_targets = [(standard, str(code))]
                if depth_enabled:
                    depth_code = self._depth_storage_code()
                    depth_layer = managed.get('WTL_PIPE_PS')
                    if depth_layer is None:
                        raise ValueError('WTL_PIPE_PS 대상 레이어가 없습니다.')
                    if nearby_targets(self.plugin, point, depth_layer, depth_code):
                        raise ValueError('주변에 동일 심도 객체가 존재합니다.')
                    planned_targets.append(('WTL_PIPE_PS', str(depth_code)))
                for previous in selected:
                    shared_targets = set(planned_targets).intersection(previous['planned_targets'])
                    if not shared_targets:
                        continue
                    metres = overlap_distance_m(self.plugin, point, previous['point'])
                    if metres is not None:
                        other = previous['point']
                        first_label = f"행 {point.get('source_row_id') or '-'} / 관리번호 {point.get('survey_no') or '-'}"
                        other_label = f"행 {other.get('source_row_id') or '-'} / 관리번호 {other.get('survey_no') or '-'}"
                        radius = GeoFlowSettingsService(self.plugin).get_default_nearby_radius()
                        targets_text = ', '.join(f'{layer_name} / {target_code}'
                                                 for layer_name, target_code in sorted(shared_targets))
                        raise SurveyValidationError(
                            'batch_spatial_duplicate',
                            f'{first_label} ↔ {other_label}: 배치 내부 중복 후보 '
                            f'(동일 대상: {targets_text}, 거리: {metres:.3f}m, 반경: {radius:.3f}m). '
                            '측점을 확인하고 제외할 행의 선택을 해제한 뒤 다시 생성하세요.',
                            survey_id=point.get('id', ''),
                            conflicting_survey_id=other.get('id', ''),
                            survey_no=point.get('survey_no', ''),
                            conflicting_survey_no=other.get('survey_no', ''),
                            shared_targets=sorted(shared_targets), distance_m=metres,
                            radius_m=radius, collision_scope='selected_batch',
                        )
                selected.append({
                    "index": index, "point": point, "survey_code": standard_code,
                    "facility": facility, "storage_code": code, "allowed": allowed,
                    "standard": standard, "layer": layer,
                    "depth_enabled": depth_enabled,
                    "planned_targets": planned_targets,
                    "resolve_ms": (perf_counter() - resolve_started) * 1000,
                })
            except Exception as exc:
                validation_errors.append((point, exc))
                self.featureTable.item(index, 7).setToolTip(
                    "검증 오류 · " + str(exc)
                )
        preflight_ms = (perf_counter() - preflight_started) * 1000
        if validation_errors:
            self.inspection.compare(self.featureTable, rows=[point for point, _error in validation_errors])
            first_point, first_error = validation_errors[0]
            if isinstance(first_error, SurveyValidationError):
                first_error.context["preflight_failures"] = [
                    {"survey_id": str(point.get("id") or ""), "message": str(error)}
                    for point, error in validation_errors
                ]
                raise first_error
            raise SurveyValidationError(
                "batch_preflight_failed",
                f"생성할 수 없는 측량점이 {len(validation_errors)}개 있습니다. "
                f"{first_point.get('source_row_id')}: {first_error}",
                survey_id=first_point.get("id", ""),
                raw_code=first_point.get("raw_code", ""),
                preflight_failures=[
                    {"survey_id": str(point.get("id") or ""), "message": str(error)}
                    for point, error in validation_errors
                ],
            )

        from ..services.depth import DepthService
        depth_index_started = perf_counter()
        depth_service = DepthService(self.plugin)
        prepare_batch = getattr(depth_service, "prepare_batch", None)
        if callable(prepare_batch):
            depth_service = prepare_batch()
        depth_index_build_ms = (perf_counter() - depth_index_started) * 1000
        needs_aux_depth = any(row["depth_enabled"] for row in selected)
        depth_ftr_cde = self._depth_storage_code() if needs_aux_depth else None
        layer_features = {}
        created_surveys = []
        depth_prepare_count = 0
        depth_ms = 0.0
        payload_started = perf_counter()
        for number, row in enumerate(selected, 1):
            item_payload_started = perf_counter()
            item_depth_ms = 0.0
            point, layer = row["point"], row["layer"]
            main_depth_result = None
            feature, target_id = self._new_target_feature(
                layer, point, row["storage_code"], null_status=True
            )
            targets = [(layer, feature)]
            if row["standard"] == "WTL_PIPE_PS":
                depth_started = perf_counter()
                result = depth_service.calculate_survey_point(point)
                main_depth_result = result
                item_depth_ms = (perf_counter() - depth_started) * 1000
                depth_ms += item_depth_ms
                depth_prepare_count += 1
                depth_index = layer.fields().indexFromName("pip_dep")
                if depth_index < 0:
                    raise ValueError("WTL_PIPE_PS에 pip_dep 물리 필드가 없습니다.")
                feature.setAttribute(
                    depth_index, result.get("depth") if result.get("ok") else None
                )
            elif row["depth_enabled"]:
                depth_started = perf_counter()
                depth_layer, depth_feature, depth_id, depth_result = self._new_depth_target(
                    point, managed, depth_service=depth_service,
                    depth_ftr_cde=depth_ftr_cde,
                )
                item_depth_ms = (perf_counter() - depth_started) * 1000
                depth_ms += item_depth_ms
                depth_prepare_count += 1
                targets.append((depth_layer, depth_feature))
            survey_id = str(point["id"])
            created_surveys.append(survey_id)
            for target_layer, target_feature in targets:
                layer_features.setdefault(target_layer, []).append(target_feature)
            self._operation_log(
                "SURVEY_CREATE_RESOLVE", survey_id=survey_id,
                raw_code=point.get("raw_code", ""), survey_code=row["survey_code"],
                facility_label=row["facility"].get("facility_label", ""),
                target_layer=row["standard"],
                facility_identity=row["facility"].get("facility_id", ""),
                storage_code=row["storage_code"],
                allowed_central_codes=[value[0] for value in row["allowed"]],
                depth_enabled=row["depth_enabled"],
            )
            self._operation_log(
                "SURVEY_BATCH_ITEM_PERF", survey_id=survey_id,
                resolve_ms=round(row["resolve_ms"], 3),
                depth_ms=round(item_depth_ms, 3),
                payload_ms=round((perf_counter() - item_payload_started) * 1000, 3),
            )
            self.statusLabel.setText(f"시설물 준비 중 {number} / {len(selected)}")
        payload_build_wall_ms = (perf_counter() - payload_started) * 1000
        payload_build_ms = max(0.0, payload_build_wall_ms - depth_ms)

        target_layers = list(layer_features)
        was_editable = {layer.id(): bool(layer.isEditable()) for layer in target_layers}
        commit_result = {}
        qgis_edit_buffer_prepare_ms = 0.0
        local_feature_add_ms = 0.0
        try:
            for layer, features in layer_features.items():
                edit_started = perf_counter()
                if not layer.isEditable() and not layer.startEditing():
                    raise RuntimeError(f"{layer.name()} 레이어 편집을 시작할 수 없습니다.")
                qgis_edit_buffer_prepare_ms += (perf_counter() - edit_started) * 1000
                add_started = perf_counter()
                if not layer.addFeatures(features):
                    raise RuntimeError(f"{layer.name()} 객체를 편집 버퍼에 추가하지 못했습니다.")
                local_feature_add_ms += (perf_counter() - add_started) * 1000
            commit_many = getattr(self.plugin, "commit_layers_online", None)
            if not callable(commit_many):
                raise RuntimeError("Survey batch online-save 경로를 사용할 수 없습니다.")
            online_started = perf_counter()
            commit_result = commit_many(
                target_layers, stop_editing=False, trigger="survey_batch_create"
            ) or {}
            online_save_wall_ms = (perf_counter() - online_started) * 1000
            if not commit_result.get("ok"):
                failure = RuntimeError(
                    "선택 시설물 batch 저장에 실패했습니다. "
                    + str(commit_result.get("server_message") or "")
                )
                failure.code = commit_result.get("error_code")
                failure.server_message = commit_result.get("server_message")
                raise failure
        except Exception:
            for layer in target_layers:
                if layer.isEditable() and layer.isModified():
                    layer.rollBack()
                if was_editable[layer.id()] and not layer.isEditable():
                    layer.startEditing()
            raise
        save_complete_ms = (perf_counter() - started_at) * 1000

        selection_restore_started = perf_counter()
        succeeded = created_surveys
        for survey_id in succeeded:
            self._selection[survey_id] = False
        selection_restore_ms = (perf_counter() - selection_restore_started) * 1000
        ui_refresh_started = perf_counter()
        self.refresh_creation_states()
        self.featureNotice.setText(
            f"시설물 서버 생성 완료 {len(succeeded)}건 · 실패 0건"
        )
        self.statusLabel.setText(
            f"선택 시설물 batch 저장 완료 · Survey {len(selected)}개 · "
            f"객체 {sum(len(features) for features in layer_features.values())}개 · "
            "ONLINE_SAVE 1회"
        )
        ui_refresh_ms = (perf_counter() - ui_refresh_started) * 1000
        total_ms = (perf_counter() - started_at) * 1000
        online_save_ms = float(commit_result.get("server_request_ms", online_save_wall_ms))
        provider_commit_ms = float(commit_result.get("provider_commit_ms", 0.0))
        online_save_overhead_ms = max(
            0.0, online_save_wall_ms - online_save_ms - provider_commit_ms
        )
        measured_values = (
            initial_guard_ms, context_resolve_ms, selection_restore_ms,
            batch_context_build_ms, selection_collect_ms, preflight_ms,
            depth_index_build_ms, depth_ms, payload_build_ms,
            qgis_edit_buffer_prepare_ms, local_feature_add_ms,
            online_save_overhead_ms, online_save_ms, provider_commit_ms,
            ui_refresh_ms,
        )
        measured_sum_ms = sum(measured_values)
        unaccounted_ms = max(0.0, total_ms - measured_sum_ms)
        perf = {
            "selected_count": len(selected),
            "selection_collect_ms": round(selection_collect_ms, 3),
            "initial_guard_ms": round(initial_guard_ms, 3),
            "context_resolve_ms": round(context_resolve_ms, 3),
            "batch_context_build_ms": round(batch_context_build_ms, 3),
            "preflight_ms": round(preflight_ms, 3),
            "depth_index_build_ms": round(depth_index_build_ms, 3),
            "depth_prepare_count": depth_prepare_count,
            "depth_calculation_ms": round(depth_ms, 3),
            "payload_build_ms": round(payload_build_ms, 3),
            "create_count": sum(len(features) for features in layer_features.values()),
            "layer_count": len(target_layers),
            "qgis_edit_buffer_prepare_ms": round(qgis_edit_buffer_prepare_ms, 3),
            "local_feature_add_ms": round(local_feature_add_ms, 3),
            "online_save_overhead_ms": round(online_save_overhead_ms, 3),
            "online_save_ms": round(online_save_ms, 3),
            "provider_commit_ms": round(provider_commit_ms, 3),
            "save_complete_ms": round(save_complete_ms, 3),
            "layer_reload_ms": 0.0, "local_refresh_ms": 0.0,
            "selection_restore_ms": round(selection_restore_ms, 3),
            "form_refresh_ms": 0.0, "ui_refresh_ms": round(ui_refresh_ms, 3),
            "measured_sum_ms": round(measured_sum_ms, 3),
            "unaccounted_ms": round(unaccounted_ms, 3),
            "total_ms": round(total_ms, 3), "online_save_count": 1,
        }
        self._last_batch_performance = dict(perf)
        self._operation_log("SURVEY_BATCH_PERF", **perf)
        return {"created": len(succeeded), "failed": 0, "errors": {}}

    def stop_creation_queue(self):
        self.stopQueueButton.setEnabled(False)

    def closeEvent(self, event):
        self.stop_creation_queue()
        super().closeEvent(event)

    def prepare_selected(self):
        _, api = self.controller.context(write=True)
        groups = {}
        for index in range(self.featureTable.rowCount()):
            if self.featureTable.item(index, 0).checkState() != Qt.CheckState.Checked:
                continue
            point = self.featureTable.item(index, 1).data(Qt.ItemDataRole.UserRole)
            state, eligible = self._creation_state(point)
            if not eligible:
                raise ValueError(f"{point.get('source_row_id')}: {state} 상태로 다시 생성할 수 없습니다.")
            recommendation = self._point_mapping(point)
            facility_label = str(
                recommendation.get("facility_label") or ""
            ).strip()
            layer = str(recommendation.get("layer") or "").strip()
            _facility, code, _allowed = self._resolve_point_storage(
                point, facility_label, layer, self._survey_code(point)
            )
            groups.setdefault((layer, code), []).append(str(point['id']))
        if not groups:
            raise ValueError('생성할 측량점 행을 체크하세요.')
        self.creation_plan = groups
        summary = '\n'.join(f'{layer} / {code}: {len(points)}개' for (layer, code), points in groups.items())
        self.featureNotice.setText(
            '선택 시설물 생성 계획\n' + summary +
            '\n속성폼 없이 로컬 저장하며, 속성은 생성 후 개별 보완합니다.'
        )
        self.statusLabel.setText('시설물/저장 코드 선택 검토 완료 · 시설물 추가/commit은 수행하지 않았습니다.')
        return groups

    def import_file(self):
        dialog = ImportDialog(
            self, submit=self._submit_import,
            duplicate_lookup=self.import_duplicate_points,
        )
        dialog.setModal(False); dialog.show(); dialog.raise_(); self._imports.append(dialog)
        dialog.finished.connect(lambda _code, item=dialog: self._imports.remove(item) if item in self._imports else None)

    def import_duplicate_points(self):
        _, api = self.controller.context()
        sources = display_rows(api.sources(include_inactive=True), 'sources')
        points = []; capped = False
        for source in sources:
            rows = display_rows(api.points(source_id=source['id']), 'points')
            capped = capped or len(rows) >= 5000
            for row in rows:
                points.append({**row, 'source_group_id': source.get('source_group_id'),
                               'source_crs': source.get('source_crs')})
        return points, f'현재 프로젝트 {len(sources)}개 Source / {len(points)}점 조회' + (' · 5,000점 상한으로 일부 중복 미확인' if capped else '')

    def _submit_import(self, payload, file_path, progress):
        try:
            result = self.controller.import_source_file(payload, file_path, progress)
        except Exception as exc:
            cause = exc.__cause__
            self._debug("import_error", {
                "stage": "presign/upload/import",
                "error_type": type(exc).__name__,
                "cause_type": type(cause).__name__ if cause is not None else "",
                "http_status": getattr(cause or exc, "http_status", None),
            })
            raise
        progress("측량점 확인 중")
        self.sources(refresh_settings=False)
        index = self.sourceCombo.findData(result["source_id"])
        source_warning = ""
        if index < 0:
            # The write already succeeded. Keep the exact source id available for
            # readback without pretending the source list refresh contained it.
            self.sourceCombo.addItem(Path(file_path).name + " · 방금 생성", result["source_id"])
            index = self.sourceCombo.count() - 1
            source_warning = "Source 목록 새로고침에서 방금 생성한 Source를 찾지 못했습니다."
        self.sourceCombo.setEnabled(True)
        self.sourceCombo.setToolTip("")
        self.sourceCombo.blockSignals(True)
        self.sourceCombo.setCurrentIndex(index)
        self.sourceCombo.blockSignals(False)
        # Always read back the whole selected Source; never seed the table from
        # the import response's newly-created rows.
        self._source_changed()
        # Re-read the authoritative project-wide Survey set only after the new
        # Source has been selected and its complete point list has loaded.
        self.load_project_settings(refresh_codes=True)
        readback = len(self.point_rows)
        imported = result["created"] + result["updated"]
        warnings = [source_warning] if source_warning else []
        response_points = result.get("response_points") or []
        response_verification = None
        if response_points:
            response_verification = _import_readback_verification(
                payload.get("points", []), response_points,
                payload.get("survey_type"),
            )
            QgsMessageLog.logMessage(
                "[SURVEY_IMPORT_RESPONSE] " + json.dumps(
                    response_verification, ensure_ascii=False,
                    sort_keys=True, default=str,
                ),
                "GeoFlow",
                (Qgis.MessageLevel.Info if response_verification["ok"]
                 else Qgis.MessageLevel.Critical),
            )
            if not response_verification["ok"]:
                warnings.append(
                    "Survey import 응답의 서버 확정 필드가 불완전합니다. "
                    f"{len(response_verification['issues'])}건을 로그에서 확인하세요."
                )
        else:
            response_verification = {
                "ok": False,
                "checked_count": 0,
                "issues": ["import response points missing"],
                "sample": [],
            }
            QgsMessageLog.logMessage(
                "[SURVEY_IMPORT_RESPONSE] " + json.dumps(
                    response_verification, ensure_ascii=False,
                    sort_keys=True, default=str,
                ),
                "GeoFlow", Qgis.MessageLevel.Critical,
            )
            warnings.append(
                "Survey import 응답에 Point 확정값이 없습니다. GET readback 결과를 확인하세요."
            )
        verification = _import_readback_verification(
            payload.get("points", []), self.point_rows,
            payload.get("survey_type"),
        )
        result["field_readback"] = verification
        result["response_field_readback"] = response_verification
        QgsMessageLog.logMessage(
            "[SURVEY_IMPORT_READBACK] " + json.dumps(
                verification, ensure_ascii=False, sort_keys=True, default=str
            ),
            "GeoFlow",
            (Qgis.MessageLevel.Info if verification["ok"]
             else Qgis.MessageLevel.Critical),
        )
        if not verification["ok"]:
            warnings.append(
                "Survey 필드 readback 불일치 "
                f"{len(verification['issues'])}건을 로그에서 확인하세요."
            )
        try:
            if not self.controller.refresh_imported_points():
                warnings.append(
                    "미전송 로컬 변경이 있어 GIS Survey 레이어 갱신을 보류했습니다.")
        except Exception:
            # Import/readback already committed. Never invite a duplicate import
            # merely because the ordinary Delta refresh needs a later retry.
            warnings.append(
                "Survey 생성은 완료됐지만 GIS 레이어 갱신은 다음 동기화에서 재시도합니다.")
        if imported != result["local_count"]:
            warnings.append(
                f"파일 유효 측점 {result['local_count']}개와 서버 생성+갱신 {imported}개가 다릅니다.")
        if readback != result["local_count"]:
            warnings.append(
                f"파일에는 {result['local_count']}개 유효 측점이 있으나 서버에서 {readback}개가 확인되었습니다.")
        result["readback_count"] = readback
        result["warning"] = " ".join(warnings)
        self.pages.setCurrentWidget(self.mappingPage)
        self.mappingTabs.setCurrentWidget(self.featurePage)
        self.render_features()
        self._debug("import_result", {
            "local_count": result["local_count"], "created": result["created"],
            "updated": result["updated"], "readback_count": readback,
            "field_readback_ok": verification["ok"],
            "field_readback_issues": verification["issues"],
            "warning": result["warning"],
        })
        progress("완료" if not warnings else "완료 · 건수 경고 확인")
        return result

    def close_service(self):
        self.stop_creation_queue()
        for dialog in list(self._imports): dialog.close()
        self._imports.clear()
