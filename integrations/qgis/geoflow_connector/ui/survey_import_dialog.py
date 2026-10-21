"""Survey file validation UI; upload is delegated to the contract-aware caller."""
import json
import re
from pathlib import Path

from qgis.PyQt.uic import loadUi
from qgis.PyQt.QtCore import Qt, QDate, QSettings
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.PyQt.QtWidgets import (QDialog, QFileDialog, QTableWidgetItem,
                                 QApplication, QInputDialog, QMessageBox)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsPointXY, QgsProject)

from ..survey.import_file import (CSV_ENCODINGS, build_import, detect_csv_encoding,
                                  read_table, sheet_names, suggest_columns)
from ..survey.import_selection import (local_date, review_rows, metadata_candidates,
                                       point_metadata)
from ..api.references import worker_reference_codes
from ..survey.code_normalizer import normalize_raw_code


class ImportDialog(QDialog):
    PROFILE_KEY = "GeoFlowConnector/survey_import_profiles/v1"

    def __init__(self, parent=None, *, submit=None, plugin=None, duplicate_lookup=None):
        super().__init__(parent)
        loadUi(str(Path(__file__).parent / "designer" / "survey_import.ui"), self)
        self.submit_callback = submit
        self.rows, self.headers, self.payload, self.path = [], [], None, None
        self._validated_signature = None
        self._completed_signature = None
        self._busy = False
        self.plugin = plugin or getattr(parent, 'plugin', None)
        self._import_scope = self._current_scope()
        self.duplicate_lookup = duplicate_lookup
        self.existing_points = []
        self._duplicates_loaded = False
        self.review = []
        self._user_checks = {}
        self._code_overrides = {}
        self._reviewed = False
        self._duplicate_note = '중복 미조회 · 신규 표시는 조회 범위 내 판정입니다.'
        self._pending_profile = None
        self._load_workers()
        self.workerCombo.currentIndexChanged.connect(self.invalidate_validation)
        self.selectAllButton.clicked.connect(lambda: self.select_rows('all'))
        self.selectNoneButton.clicked.connect(lambda: self.select_rows('none'))
        self.selectNewButton.clicked.connect(lambda: self.select_rows('new'))
        self.duplicatesButton.clicked.connect(self.lookup_duplicates)
        self.previewTable.itemChanged.connect(self._row_checked)
        encoding_labels = {
            "utf-8": "UTF-8", "cp949": "CP949", "euc-kr": "EUC-KR",
            "utf-8-sig": "UTF-8-SIG",
        }
        for encoding in ("utf-8", "cp949", "euc-kr", "utf-8-sig"):
            if encoding in CSV_ENCODINGS:
                self.encodingCombo.addItem(encoding_labels[encoding], encoding)
        for label, value in (("쉼표 (,)", ","), ("세미콜론 (;)", ";"), ("탭", "\t")):
            self.delimiterCombo.addItem(label, value)
        self.sourceTypeCombo.addItem("GNSS", "GNSS")
        self.sourceTypeCombo.addItem("TotalStation", "TOTAL")
        self.coordinateModeCombo.addItems([
            "평면좌표 Easting / Northing",
            "경위도 Longitude / Latitude",
        ])
        self.crsSelector.setCrs(QgsCoordinateReferenceSystem())
        self._install_format_switch()
        self._install_profiles()
        self.previewTable.setAlternatingRowColors(True)
        self.previewTable.setToolTip(
            "Survey Code 열만 수정할 수 있습니다. 원본 raw_code는 변경되지 않습니다."
        )
        self.advancedGroup.toggled.connect(self._advanced_visibility)
        self._advanced_visibility(False)
        self.chooseFileButton.clicked.connect(self.choose_file)
        self.encodingCombo.currentIndexChanged.connect(self.reload_file)
        self.delimiterCombo.currentIndexChanged.connect(self.reload_file)
        self.sheetCombo.currentIndexChanged.connect(self.reload_file)
        self.coordinateModeCombo.currentIndexChanged.connect(self._mode_changed)
        self.validateButton.clicked.connect(self.validate)
        self.createSurveyButton.clicked.connect(self.create_survey)
        self.closeButton.clicked.connect(self.close)
        for box in self._mapping_boxes():
            box.currentIndexChanged.connect(self.invalidate_validation)
        for box in self._metadata_mapping_boxes():
            box.currentIndexChanged.connect(self.invalidate_validation)
        self.sourceTypeCombo.currentIndexChanged.connect(self.invalidate_validation)
        self.crsSelector.crsChanged.connect(self.invalidate_validation)
        for edit in (self.geoidEdit, self.calibrationEdit, self.sourceGroupEdit, self.supersedesEdit):
            edit.textChanged.connect(self.invalidate_validation)
        self._mode_changed()

    def _install_format_switch(self):
        """Toggle format-specific controls without altering Designer layout."""
        self._update_file_option_visibility("")

    def _install_profiles(self):
        self.profileCombo = self.importProfileCombo
        self.saveProfileButton = self.saveImportProfileButton
        self.manageProfileButton = self.manageImportProfileButton
        self.saveProfileButton.clicked.connect(self.save_profile)
        self.manageProfileButton.clicked.connect(self.manage_profiles)
        self.profileCombo.currentIndexChanged.connect(self._profile_selected)
        self._reload_profile_combo()

    def _profiles(self):
        raw = QSettings().value(self.PROFILE_KEY, "{}")
        try:
            value = json.loads(str(raw or "{}"))
        except (TypeError, ValueError):
            value = {}
        return {str(name): dict(profile) for name, profile in value.items()
                if isinstance(profile, dict)}

    def _write_profiles(self, profiles):
        QSettings().setValue(
            self.PROFILE_KEY,
            json.dumps(profiles, ensure_ascii=False, sort_keys=True),
        )

    def _reload_profile_combo(self, selected=None):
        self.profileCombo.blockSignals(True)
        self.profileCombo.clear()
        self.profileCombo.addItem("설정 선택", None)
        for name in sorted(self._profiles(), key=str.casefold):
            self.profileCombo.addItem(name, name)
        index = self.profileCombo.findData(selected)
        self.profileCombo.setCurrentIndex(index if index >= 0 else 0)
        self.profileCombo.blockSignals(False)

    def _profile_mapping(self):
        return {
            "point_name": self.rowIdCombo.currentData(),
            "code": self.rawCodeCombo.currentData(),
            "easting": self.xCombo.currentData(),
            "northing": self.yCombo.currentData(),
            "z": self.zCombo.currentData(),
            "survey_date": self.surveyDateColumnCombo.currentData(),
            "pdop": self.pdopCombo.currentData(),
            "antenna_height": self.surveyHeightCombo.currentData(),
            "solution_info": self.solutionInfoCombo.currentData(),
        }

    def _current_profile(self, name):
        source_type = self.sourceTypeCombo.currentData()
        return {
            "name": name,
            "source_type": source_type,
            "survey_type": (
                "TOTAL_STATION" if source_type == "TOTAL" else "GNSS"
            ),
            "coordinate_input_mode": (
                "geographic" if self.coordinateModeCombo.currentIndex() == 1
                else "planar"
            ),
            "source_crs": self.crsSelector.crs().authid(),
            "encoding": self.encodingCombo.currentData(),
            "delimiter": self.delimiterCombo.currentData(),
            "mapping": self._profile_mapping(),
        }

    def save_profile(self):
        name, accepted = QInputDialog.getText(
            self, "가져오기 설정 저장", "설정 이름"
        )
        name = str(name).strip()
        if not accepted or not name:
            return
        profiles = self._profiles()
        if name in profiles and QMessageBox.question(
                self, "설정 덮어쓰기",
                "이미 존재하는 설정입니다. 덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        profiles[name] = self._current_profile(name)
        self._write_profiles(profiles)
        self._reload_profile_combo(name)
        self.errorLabel.setText(f"가져오기 설정 '{name}'을 저장했습니다.")

    def manage_profiles(self):
        profiles = self._profiles()
        if not profiles:
            self.errorLabel.setText("저장된 가져오기 설정이 없습니다.")
            return
        name, accepted = QInputDialog.getItem(
            self, "가져오기 설정 관리", "설정", sorted(profiles), 0, False
        )
        if not accepted:
            return
        action, accepted = QInputDialog.getItem(
            self, "가져오기 설정 관리", "작업", ["이름 변경", "삭제"], 0, False
        )
        if not accepted:
            return
        if action == "삭제":
            if QMessageBox.question(
                    self, "설정 삭제", f"'{name}' 설정을 삭제할까요?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            profiles.pop(name, None)
            self._write_profiles(profiles)
            self._reload_profile_combo()
            return
        renamed, accepted = QInputDialog.getText(
            self, "설정 이름 변경", "새 이름", text=str(name)
        )
        renamed = str(renamed).strip()
        if not accepted or not renamed or renamed == name:
            return
        if renamed in profiles:
            self.errorLabel.setText("이미 존재하는 설정 이름입니다.")
            return
        profile = profiles.pop(name)
        profile["name"] = renamed
        profiles[renamed] = profile
        self._write_profiles(profiles)
        self._reload_profile_combo(renamed)

    @staticmethod
    def _set_combo_data(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _profile_selected(self, _index=None):
        name = self.profileCombo.currentData()
        profile = self._profiles().get(str(name)) if name else None
        if not profile:
            return
        self._pending_profile = profile
        # Profiles written before the explicit survey_type contract stored the
        # legacy source_type value under survey_type.
        stored_source_type = profile.get("source_type")
        if stored_source_type is None:
            legacy = profile.get("survey_type")
            stored_source_type = "TOTAL" if legacy in {
                "TOTAL", "TOTAL_STATION"
            } else legacy
        survey_index = self.sourceTypeCombo.findData(stored_source_type)
        if survey_index >= 0:
            self.sourceTypeCombo.setCurrentIndex(survey_index)
        self.coordinateModeCombo.setCurrentIndex(
            1 if profile.get("coordinate_input_mode") == "geographic" else 0
        )
        authid = str(profile.get("source_crs") or "")
        crs = QgsCoordinateReferenceSystem(authid)
        if crs.isValid():
            self.crsSelector.setCrs(crs)
        for combo, value in (
            (self.encodingCombo, profile.get("encoding")),
            (self.delimiterCombo, profile.get("delimiter")),
        ):
            combo.blockSignals(True)
            self._set_combo_data(combo, value)
            combo.blockSignals(False)
        is_csv = bool(self.path and Path(self.path).suffix.lower() == ".csv")
        if is_csv:
            self.reload_file()
        else:
            self._apply_profile_mapping(profile)
        self.invalidate_validation()

    def _apply_profile_mapping(self, profile=None):
        profile = profile or self._pending_profile
        if not profile or not self.headers:
            return
        mapping = profile.get("mapping") or {}
        boxes = {
            "point_name": self.rowIdCombo, "code": self.rawCodeCombo,
            "easting": self.xCombo, "northing": self.yCombo, "z": self.zCombo,
            "survey_date": self.surveyDateColumnCombo, "pdop": self.pdopCombo,
            "antenna_height": self.surveyHeightCombo,
            "solution_info": self.solutionInfoCombo,
        }
        for key, box in boxes.items():
            self._set_combo_data(box, mapping.get(key))

    def _update_file_option_visibility(self, suffix):
        csv_file = suffix == ".csv"
        excel_file = suffix in {".xls", ".xlsx"}
        supported_file = csv_file or excel_file
        self.encodingLabel.setVisible(csv_file)
        self.encodingCombo.setVisible(csv_file)
        self.delimiterLabel.setVisible(csv_file)
        self.delimiterCombo.setVisible(csv_file)
        self.sheetLabel.setVisible(excel_file)
        self.sheetCombo.setVisible(excel_file)
        self.sourceTypeLabel.setVisible(supported_file)
        self.sourceTypeCombo.setVisible(supported_file)

    def _load_workers(self):
        self.workerCombo.addItem('선택 안 함 / 연결된 작업자 없음', None)
        service = getattr(self.plugin, '_reference_service', None)
        catalog = getattr(service, 'catalog', {}) or {}
        current = (getattr(getattr(self.plugin, 'active_client', None), 'session_user', {}) or {})
        context = getattr(self.plugin, 'current_user_context', None)
        if callable(context):
            current = {**current, **context()}
        # A login user UUID is NOT a worker UUID.
        worker_id = str(current.get('worker_id') or '')
        for row in worker_reference_codes(catalog):
            if row['resolved']:
                self.workerCombo.addItem(row['label'], row['id'])
        if worker_id and self.workerCombo.findData(worker_id) < 0:
            label = current.get('worker_name') or current.get('display_name') or worker_id
            self.workerCombo.addItem(str(label), worker_id)
        index = self.workerCombo.findData(worker_id)
        if index >= 0:
            self.workerCombo.setCurrentIndex(index)

    def _current_scope(self):
        if self.plugin is None:
            return None
        return (id(self.plugin.active_client), self.plugin.integration_state().get('project_id'))

    @staticmethod
    def _business_type(value):
        value = value if isinstance(value, dict) else {}
        for key in (
            "business_type", "business_code", "work_type_code",
            "survey_work_code", "업무유형", "업무코드",
        ):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""

    def _survey_code(self, raw_code, business_type=""):
        if self.plugin is None:
            return str(raw_code or '').strip().upper() or None
        state = self.plugin.integration_state()
        return normalize_raw_code(
            state.get('project_id', ''), raw_code, settings=QSettings(),
            origin=getattr(self.plugin.active_client, 'base_url', ''),
            business_type=business_type,
        )

    def lookup_duplicates(self):
        if self._busy:
            return
        try:
            if self.duplicate_lookup is None:
                raise ValueError('프로젝트의 기존 측량점 조회 실행기가 없습니다.')
            self.existing_points, self._duplicate_note = self.duplicate_lookup()
            self._duplicates_loaded = True
            self.invalidate_validation(); self.validate()
        except Exception as exc:
            self._duplicate_note = '중복 조회 실패 · 자동 제외하지 않습니다.'
            self.existing_points = []
            self.invalidate_validation()
            self.errorLabel.setText(self._duplicate_note)

    def select_rows(self, mode):
        if not self._reviewed:
            self.validate()
        self.previewTable.blockSignals(True)
        for index, record in enumerate(self.review):
            checked = record['state'] != 'ERROR' and (mode == 'all' or (mode == 'new' and record['state'] == 'NEW'))
            record['checked'] = checked
            self._user_checks[index] = checked
            self.previewTable.item(index, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.previewTable.blockSignals(False)
        self._row_checked()

    def _row_checked(self, item=None):
        if item is not None and item.column() == 5:
            if 0 <= item.row() < len(self.review):
                normalized = item.text().strip().upper()
                if item.text() != normalized:
                    self.previewTable.blockSignals(True)
                    item.setText(normalized)
                    self.previewTable.blockSignals(False)
                row = self.review[item.row()]["row"]
                self._code_overrides[getattr(row, "number", item.row())] = (
                    normalized
                )
                point = self.review[item.row()].get("point")
                if isinstance(point, dict):
                    point["code"] = normalized
                item.setBackground(QBrush(QColor("#FFF1C7")))
                item.setToolTip(
                    "사용자가 수정한 최종 Survey Code · 저장 시 code로 전송됩니다."
                )
            self.payload = None
            self._validated_signature = None
            self._completed_signature = None
            self.createSurveyButton.setEnabled(bool(self.path and self.rows))
            return
        if item is not None and item.column() != 0:
            return
        if item is not None:
            self._user_checks[item.row()] = item.checkState() == Qt.CheckState.Checked
        for index, record in enumerate(self.review):
            record['checked'] = record['state'] != 'ERROR' and self.previewTable.item(index, 0).checkState() == Qt.CheckState.Checked
        self.payload = None; self._validated_signature = None
        self.createSurveyButton.setEnabled(bool(self.path and self.rows))
        self._summary()

    def _summary(self):
        self.previewCountLabel.setText(
            f"대상 {sum(r['checked'] for r in self.review)} · "
            f"원시 {len(self.rows)} · 조회 {len(self.existing_points)}"
        )

    def _advanced_visibility(self, visible):
        layout = self.advancedGroup.layout()
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                widget.setVisible(visible)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "측량 원본 선택", "",
            "CSV (*.csv);;Excel 97-2003 (*.xls);;Excel Workbook (*.xlsx)")
        if path:
            self.load_file(path)

    def load_file(self, path):
        self.path = str(path)
        self.invalidate_validation()
        suffix = Path(path).suffix.lower()
        try:
            if suffix not in {".csv", ".xls", ".xlsx"}:
                raise ValueError("CSV, XLS 또는 XLSX 파일을 선택하세요.")
            self.sheetCombo.blockSignals(True); self.sheetCombo.clear()
            if suffix in {".xls", ".xlsx"}:
                self.sheetCombo.addItems(sheet_names(path))
            self._update_file_option_visibility(suffix)
            if suffix == ".csv":
                detected = detect_csv_encoding(path)
                configured = (self._pending_profile or {}).get("encoding")
                self.encodingCombo.blockSignals(True)
                self._set_combo_data(self.encodingCombo, configured or detected)
                self.encodingCombo.blockSignals(False)
            self.errorLabel.clear()
        except Exception as exc:
            self.path = None
            self._update_file_option_visibility("")
            self.errorLabel.setText(str(exc))
            return
        finally:
            self.sheetCombo.blockSignals(False)
        self.reload_file()

    def reload_file(self, *_):
        if not self.path:
            return
        self.invalidate_validation(); self._user_checks = {}; self._code_overrides = {}
        previous = {box.objectName(): box.currentData() for box in self._all_mapping_boxes()}
        try:
            headers, rows, metadata = read_table(
                self.path, encoding=self.encodingCombo.currentData() or "utf-8",
                delimiter=self.delimiterCombo.currentData() or ",",
                sheet=self.sheetCombo.currentText() or None, return_metadata=True)
            self.headers, self.rows = headers, rows
            self.sourceTypeLabel.setVisible(True)
            self.sourceTypeCombo.setVisible(True)
            for box in self._all_mapping_boxes():
                box.blockSignals(True); box.clear(); box.addItem("선택 안 함", None)
                for header in headers:
                    box.addItem(header, header)
                box.blockSignals(False)
            self._apply_suggestions(previous)
            self._apply_profile_mapping()
            self._render_preview()
            self.errorLabel.setText(f"{len(rows)}행을 읽었습니다. 검증 전에는 서버로 전송하지 않습니다.")
            self.invalidate_validation()
        except Exception as exc:
            self.rows, self.headers, self.payload = [], [], None
            self.sourceTypeLabel.setVisible(False)
            self.sourceTypeCombo.setVisible(False)
            self.previewTable.clear()
            self.previewTable.setRowCount(0)
            self.errorLabel.setText(str(exc))

    def _mapping_boxes(self):
        return self.rowIdCombo, self.rawCodeCombo, self.xCombo, self.yCombo, self.zCombo

    def _metadata_mapping_boxes(self):
        return (self.surveyDateColumnCombo, self.pdopCombo,
                self.surveyHeightCombo, self.solutionInfoCombo)

    def _all_mapping_boxes(self):
        return self._mapping_boxes() + self._metadata_mapping_boxes()

    def _apply_suggestions(self, previous=None):
        geographic = self.coordinateModeCombo.currentIndex() == 1
        suggestions = suggest_columns(self.headers, geographic=geographic)
        keys = ("source_row_id", "raw_code", "longitude" if geographic else "raw_x",
                "latitude" if geographic else "raw_y", "raw_z")
        for box, key in zip(self._mapping_boxes(), keys):
            requested = (previous or {}).get(box.objectName()) or suggestions.get(key)
            index = box.findData(requested); box.setCurrentIndex(index if index >= 0 else 0)
        candidates = metadata_candidates(self.headers)
        for box, key in ((self.surveyDateColumnCombo, 'survey_date'),
                         (self.pdopCombo, 'pdop'),
                         (self.surveyHeightCombo, 'antenna_height'),
                         (self.solutionInfoCombo, 'solution_info')):
            requested = (previous or {}).get(box.objectName()) or candidates.get(key)
            index = box.findData(requested); box.setCurrentIndex(index if index >= 0 else 0)

    def _mode_changed(self):
        geographic = self.coordinateModeCombo.currentIndex() == 1
        self.crsSelector.setEnabled(not geographic)
        self.firstCoordinateLabel.setText(
            "Longitude (필수)" if geographic else "Easting (필수)")
        self.secondCoordinateLabel.setText(
            "Latitude (필수)" if geographic else "Northing (필수)")
        if self.headers:
            self._apply_suggestions()
        self.invalidate_validation()

    def _mapped_metadata_columns(self):
        return {
            "survey_date": self.surveyDateColumnCombo.currentData(),
            "pdop": self.pdopCombo.currentData(),
            "antenna_height": self.surveyHeightCombo.currentData(),
            "solution_info": self.solutionInfoCombo.currentData(),
        }

    def _expected_survey_numbers(self):
        """Return preview-only numbers; the server must allocate final values."""
        highest = {}
        for point in self.existing_points:
            value = str(point.get("survey_no") or "")
            match = re.fullmatch(r"(\d{6})-(\d{3,})", value)
            if match:
                highest[match.group(1)] = max(
                    highest.get(match.group(1), 0), int(match.group(2))
                )
        result = []
        date_column = self.surveyDateColumnCombo.currentData()
        for record in self.review:
            if record.get("state") == "ERROR" or not record.get("checked"):
                result.append("")
                continue
            row = record["row"]
            try:
                survey_date = local_date(
                    row.get(date_column) if date_column else None, None
                )
            except ValueError:
                result.append("")
                continue
            if not survey_date:
                result.append("")
                continue
            prefix = QDate.fromString(survey_date, "yyyy-MM-dd").toString("yyMMdd")
            highest[prefix] = highest.get(prefix, 0) + 1
            result.append(f"{prefix}-{highest[prefix]:03d}")
        return result

    def _assign_geometry_fields(self, points, *, geographic, source_crs):
        """Send accepted EPSG:4326 geometry fields while preserving raw values."""
        transform = None
        if not geographic:
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem(source_crs),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance().transformContext(),
            )
        for point in points:
            if geographic:
                point["longitude"] = point["raw_x"]
                point["latitude"] = point["raw_y"]
            else:
                wgs84 = transform.transform(QgsPointXY(
                    float(point["raw_x"]), float(point["raw_y"])
                ))
                point["longitude"] = wgs84.x()
                point["latitude"] = wgs84.y()

    def _render_preview(self):
        self.previewTable.blockSignals(True)
        self.previewTable.clear(); self.previewTable.setColumnCount(len(self.headers) + 6)
        self.previewTable.setHorizontalHeaderLabels(
            ["생성", "상태", "예상 측량번호", "원본 행", "raw_code",
             "Survey Code ✎", *self.headers]
        )
        self.previewTable.horizontalHeaderItem(5).setToolTip(
            "수정 가능한 최종 코드 · 입력 확정 시 대문자로 변환됩니다."
        )
        if not self._reviewed:
            self.review = [dict(row=row, state='NEW', checked=True, error='검증 전') for row in self.rows]
        self.previewTable.setRowCount(len(self.rows))
        expected_numbers = self._expected_survey_numbers()
        state_style = {
            'NEW': ('●', '신규', QColor('#239B56'), None),
            'DUPLICATE': ('●', '중복 · 기존 Survey와 정확히 일치', QColor('#C62828'), None),
            'POSSIBLE_DUPLICATE': (
                '●', '중복 의심 · 같은 행 식별자가 있으나 확정 조건 부족',
                QColor('#EF6C00'), QColor('#FFF3E0')
            ),
            'ERROR': (
                '●', '오류 · 가져오기 입력 또는 검증 실패',
                QColor('#7B1FA2'), QColor('#F3E5F5')
            ),
        }
        for r, record in enumerate(self.review):
            row = record['row']
            raw_code = ((record.get('point') or {}).get('raw_code')
                        if record.get('point') else
                        row.get(self.rawCodeCombo.currentData()))
            row_key = getattr(row, "number", r)
            survey_code = (
                self._code_overrides[row_key]
                if row_key in self._code_overrides
                else self._survey_code(raw_code, self._business_type(row))
            )
            symbol, state_tip, state_color, row_tint = state_style[record['state']]
            values = ['', symbol, expected_numbers[r], row.number, raw_code,
                      survey_code,
                      *[row.get(header) for header in self.headers]]
            for c, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if c != 5:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setBackground(QBrush(row_tint or QColor('#F2F2F2')))
                else:
                    item.setBackground(QBrush(
                        QColor('#FFF1C7') if row_key in self._code_overrides
                        else QColor('#FFFFFF')
                    ))
                    item.setToolTip(
                        "수정 가능한 최종 Survey Code · 저장 시 code로 전송됩니다."
                    )
                if c == 0:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    if record['state'] == 'ERROR':
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setCheckState(Qt.CheckState.Checked if record['checked'] else Qt.CheckState.Unchecked)
                if c == 1:
                    item.setForeground(QBrush(state_color))
                    item.setToolTip(state_tip + (
                        f"\n{record['error']}" if record['error'] else ""
                    ))
                elif c != 5:
                    item.setToolTip(record['error'])
                if record['state'] == 'DUPLICATE' and c > 0:
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
                    item.setForeground(QBrush(QColor('#C62828')))
                self.previewTable.setItem(r, c, item)
        self.previewTable.blockSignals(False)
        self._summary()
        self.previewTable.resizeColumnsToContents()

    def _state_signature(self):
        if not self.path:
            return None
        try:
            stat = Path(self.path).stat()
            file_state = (str(Path(self.path).resolve()), stat.st_size, stat.st_mtime_ns)
        except OSError:
            file_state = (self.path, None, None)
        return (file_state, self.encodingCombo.currentData(), self.delimiterCombo.currentData(),
                self.sheetCombo.currentText(), self.sourceTypeCombo.currentData(),
                self.coordinateModeCombo.currentIndex(), self.crsSelector.crs().authid(),
                QgsProject.instance().crs().authid(),
                tuple(box.currentData() for box in self._mapping_boxes()),
                tuple(box.currentData() for box in self._metadata_mapping_boxes()),
                self.geoidEdit.text(), self.calibrationEdit.text(),
                self.sourceGroupEdit.text(), self.supersedesEdit.text(),
                tuple(r['checked'] for r in self.review),
                tuple(sorted(self._code_overrides.items())),
                self.workerCombo.currentData())

    def invalidate_validation(self, *_):
        if self._busy:
            return
        self.payload = None
        self._reviewed = False
        self._validated_signature = None
        self._completed_signature = None
        self.createSurveyButton.setEnabled(bool(self.path and self.rows))

    def _build_payload(self):
        if not self.path or not self.rows:
            raise ValueError("먼저 유효한 측량 파일을 선택하세요.")
        geographic = self.coordinateModeCombo.currentIndex() == 1
        crs = self.crsSelector.crs()
        # Geographic input is explicit EPSG:4326 evidence.  Do not inherit a
        # stale/disabled CRS selector value from a previous planar import.
        authid = "EPSG:4326" if geographic else (
            crs.authid() if crs.isValid() else ""
        )
        if not geographic and not crs.isValid():
            raise ValueError("원본 파일 Easting/Northing의 좌표계를 선택하세요.")
        if not geographic and (not authid.startswith("EPSG:") or crs.isGeographic()):
            raise ValueError("평면좌표에는 EPSG 코드가 있는 투영 좌표계를 선택하세요.")
        coordinates = ("longitude", "latitude") if geographic else ("raw_x", "raw_y")
        mapping = {"source_row_id": self.rowIdCombo.currentData(),
                   coordinates[0]: self.xCombo.currentData(), coordinates[1]: self.yCombo.currentData()}
        if self.rawCodeCombo.currentData(): mapping["raw_code"] = self.rawCodeCombo.currentData()
        if self.zCombo.currentData(): mapping["raw_z"] = self.zCombo.currentData()
        if not self.surveyDateColumnCombo.currentData():
            raise ValueError("측량일 파일 컬럼을 선택하세요.")
        try:
            calibration = json.loads(self.calibrationEdit.text() or "{}")
        except ValueError:
            raise ValueError("보정 정보는 JSON 객체로 입력하세요.") from None
        source_type = self.sourceTypeCombo.currentData()
        survey_type = "TOTAL_STATION" if source_type == "TOTAL" else "GNSS"
        target_crs = ""
        project_crs = QgsProject.instance().crs()
        if (geographic and project_crs.isValid()
                and not project_crs.isGeographic()
                and project_crs.authid().startswith("EPSG:")):
            target_crs = project_crs.authid()
        options = dict(original_file_name=Path(self.path).name,
            source_type=source_type, survey_type=survey_type,
            source_crs=authid, target_crs=target_crs,
            geoid_model=self.geoidEdit.text(), calibration_info=calibration,
            geographic=geographic, source_group_id=self.sourceGroupEdit.text().strip() or None,
            supersedes_id=self.supersedesEdit.text().strip() or None)
        if not self._reviewed:
            self.review = review_rows(
                self.rows, mapping, options, self.existing_points,
                worker_id=self.workerCombo.currentData(), default_date=None,
                mapped_columns=self._mapped_metadata_columns())
            for index, checked in self._user_checks.items():
                if index < len(self.review) and self.review[index]['state'] != 'ERROR':
                    self.review[index]['checked'] = checked
            self._reviewed = True
            self._render_preview()
        selected = [r['row'] for r in self.review if r['checked'] and r['state'] != 'ERROR']
        if not selected:
            raise ValueError('생성할 유효한 행을 하나 이상 체크하세요. 오류 내용은 행의 도움말을 확인하세요.')
        payload = build_import(selected, mapping, **options)
        consumed = {column for column in mapping.values() if column}
        metadata_rows = []
        for point, row in zip(payload['points'], selected):
            metadata = point_metadata(
                row, worker_id=self.workerCombo.currentData(),
                default_date=None, consumed_columns=consumed,
                mapped_columns=self._mapped_metadata_columns())
            point.update(metadata)
            if not point.get('survey_date'):
                raise ValueError(
                    f"{getattr(row, 'number', '?')}행 · survey_date · "
                    "측량일 값이 비어 있습니다."
                )
            # Existing `code` is the deployed Survey business-code field. The
            # original file value remains in raw_code; no duplicate DB field is
            # introduced.
            row_key = getattr(row, "number", None)
            point['code'] = (
                self._code_overrides[row_key]
                if row_key in self._code_overrides
                else self._survey_code(
                    point.get('raw_code'), self._business_type({
                        **point,
                        **(point.get('raw_data')
                           if isinstance(point.get('raw_data'), dict) else {}),
                    })
                )
            )
            if point.get('raw_code') not in (None, '') and not point['code']:
                raise ValueError(
                    f"{getattr(row, 'number', '?')}행 · Survey Code를 입력하세요."
                )
            metadata_rows.append(metadata)
        self._assign_geometry_fields(
            payload['points'], geographic=geographic, source_crs=authid
        )
        self.local_metadata = {
            'worker_id': self.workerCombo.currentData(), 'rows': metadata_rows}
        return payload

    def validate(self):
        try:
            if self._current_scope() != self._import_scope:
                raise ValueError('프로젝트 또는 로그인 세션이 변경되었습니다. 가져오기 창을 다시 여세요.')
            if self.duplicate_lookup is not None and not self._duplicates_loaded:
                try:
                    self.existing_points, self._duplicate_note = self.duplicate_lookup()
                    self._duplicates_loaded = True
                except Exception:
                    self.existing_points = []
                    self._duplicate_note = '중복 조회 실패 · 이번 검증에서는 자동 제외하지 않습니다.'
            self.payload = self._build_payload()
            self._validated_signature = self._state_signature()
            self.errorLabel.setText(f"검증 완료 · {len(self.payload['points'])}개 측량점 · 현재 파일/매핑/CRS 상태를 유지합니다.")
            self.createSurveyButton.setEnabled(True); return self.payload
        except Exception as exc:
            self.payload = None; self._validated_signature = None
            self.createSurveyButton.setEnabled(False)
            self.errorLabel.setText(str(exc)); return None

    build = validate

    def create_survey(self):
        if self._current_scope() != self._import_scope:
            self.errorLabel.setText('프로젝트 또는 로그인 세션이 변경되었습니다. 가져오기 창을 다시 여세요.')
            return
        if self.payload is None or self._validated_signature != self._state_signature():
            if self.validate() is None:
                return
        payload = self.payload
        if self._completed_signature == self._validated_signature:
            self.errorLabel.setText("현재 검증 결과로 이미 Survey를 생성했습니다.")
            return
        if self.submit_callback is None:
            self.errorLabel.setText("Survey 생성 실행기가 연결되지 않았습니다. 검증 결과는 유지됩니다.")
            return
        self._busy = True
        self.setEnabled(False)
        self.createSurveyButton.setEnabled(False)
        self.validateButton.setEnabled(False)
        try:
            result = self.submit_callback(payload, self.path, self.set_progress)
            if result is None: return
            self._completed_signature = self._validated_signature
            warning = result.get("warning") or ""
            self.errorLabel.setText(
                f"측량자료 가져오기 완료\n{result['local_count']}개 측량점 생성\n"
                f"파일 {Path(self.path).name} · 생성 {result['created']}개 · "
                f"갱신 {result['updated']}개 · 확인 {result['readback_count']}개"
                + (f"\n경고: {warning}" if warning else ""))
        except Exception as exc:
            self.errorLabel.setText(str(exc))
        finally:
            self._busy = False
            self.setEnabled(True)
            self.validateButton.setEnabled(True)
            # Failure can be retried explicitly; success is locked against duplicates.
            self.createSurveyButton.setEnabled(
                self._completed_signature != self._validated_signature and self.payload is not None)

    def set_progress(self, text):
        self.errorLabel.setText(str(text))
        QApplication.processEvents()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self):
        if not self._busy:
            super().reject()
