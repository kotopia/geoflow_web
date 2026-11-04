"""Independent modeless workspace; output is staged and never committed to source."""
import json
from copy import deepcopy
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsRectangle, QgsVectorLayer, QgsWkbTypes
from .catalog import LocalCatalogProvider
from .qc import blocked, run_qc
from .spatial import Spatial
from .structure import plan, post_qc, preview
from .field_editor import FieldEditor, METHODS
from .ui_values import output_value, qgis_field, scalar

TITLE = "GeoFlow QC & Structure"


class Plugin:
    def __init__(self, iface):
        self.iface = iface
        self.window = None

    def initGui(self):
        self.action = QAction(TITLE, self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(TITLE, self.action)

    def show(self):
        if self.window is None:
            path = Path(QgsApplication.qgisSettingsDirPath()) / "geoflow_qc_structure"
            self.window = Workspace(self.iface, LocalCatalogProvider(path))
        self.window.reload_layers()
        self.window.show()
        self.window.raise_()

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu(TITLE, self.action)
        self.action.deleteLater()
        if self.window:
            self.window.close()
            self.window.deleteLater()
            self.window = None


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    return widget


def fill(widget, rows):
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            widget.setItem(i, j, QTableWidgetItem("" if value is None else str(value)))


class Workspace(QDialog):
    def __init__(self, iface, provider):
        super().__init__(iface.mainWindow())
        self.iface, self.provider = iface, provider
        self.settings = QSettings()
        self.project = QgsProject.instance()
        self.findings, self.preview_state, self.finding_layer = [], None, None
        self.setWindowTitle(TITLE)
        self.resize(1060, 660)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        layout = QVBoxLayout(self)
        self.layers, self.profiles = QComboBox(), QComboBox()
        selectors = QHBoxLayout()
        for label, control in (("입력 레이어", self.layers), ("Profile", self.profiles)):
            selectors.addWidget(QLabel(label)); selectors.addWidget(control)
        layout.addLayout(selectors)
        self.status = QLabel("원본을 변경하지 않습니다.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        qc = self.tab("QC")
        self.qc_table = table(["객체", "규칙", "심각도", "필드", "메시지", "측정", "기준", "상태"])
        self.buttons(qc, [("전체 검사", self.scan), ("선택 재검사", lambda: self.scan(True)),
                          ("객체 선택", self.select_finding), ("지도 이동 / Zoom", self.zoom_finding)])
        qc.addWidget(self.qc_table)
        self.qc_table.cellDoubleClicked.connect(lambda *_: self.zoom_finding())
        editor = self.tab("구조화 Profile")
        self.profile_table = table(["기준 의미", "기준필드", "출력필드", "자료형", "방법", "설정", "Override", "필드 설정"])
        editor.addWidget(self.profile_table)
        editor.addWidget(QLabel("각 행 오른쪽의 설정에서 출력 필드와 값 생성 방법을 지정하세요. 변경 후 Preview에 바로 적용됩니다."))
        self.buttons(editor, [("출력 필드 추가", self.add_field), ("Profile 새 리비전 저장", self.save_profile)])
        execute = self.tab("구조화 실행")
        self.preview_table = table(["객체","필드","현재값","새 값","Operation","Rule","상태"])
        self.buttons(execute,[("Preview",self.prepare),("임시 레이어 생성",self.execute)])
        execute.addWidget(self.preview_table)
        self.profiles.currentIndexChanged.connect(self.show_profile)
        self.layers.currentIndexChanged.connect(self.invalidate)
        self.reload_profiles(self.settings.value("geoflow_qc_structure/profile", ""))
        self.reload_layers()

    def tab(self, name):
        widget = QWidget()
        self.tabs.addTab(widget,name)
        return QVBoxLayout(widget)

    def buttons(self, parent, actions):
        bar = QHBoxLayout()
        for label, callback in actions:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, cb=callback: self.call(cb))
            bar.addWidget(button)
        parent.addLayout(bar)

    def call(self, callback):
        try:
            callback()
        except Exception as exc:
            self.status.setText(str(exc))
            QMessageBox.warning(self, TITLE, str(exc))

    def invalidate(self, *_):
        self.preview_state = None
        self.preview_table.setRowCount(0)

    def reload_layers(self):
        current = self.layers.currentData() or getattr(self.iface.activeLayer(), "id", lambda: None)()
        self.layers.blockSignals(True)
        self.layers.clear()
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isSpatial() and layer.isValid():
                self.layers.addItem(layer.name(),layer.id())
        i = self.layers.findData(current)
        if i >= 0:
            self.layers.setCurrentIndex(i)
        self.layers.blockSignals(False)
        self.invalidate()

    def reload_profiles(self, selected=None):
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for key, profile in self.provider.profiles().items():
            self.profiles.addItem(f'{profile["name"]} · r{profile["revision"]}',key)
        i = self.profiles.findData(selected)
        if i >= 0:
            self.profiles.setCurrentIndex(i)
        self.profiles.blockSignals(False)
        self.show_profile()

    def show_profile(self, *_):
        self.invalidate()
        key = self.profiles.currentData()
        if key is None:
            return
        self.raw_profile = deepcopy(self.provider.profiles()[key])
        self.refresh_profile_table()
        self.settings.setValue("geoflow_qc_structure/profile", key)

    def current_profile(self):
        profiles = self.provider.profiles()
        profiles[self.raw_profile["id"]] = self.raw_profile
        return self.provider.resolve(self.raw_profile["id"], profiles)

    def refresh_profile_table(self):
        resolved = self.current_profile()
        catalog = self.provider.get_fields()
        entries = plan(resolved, catalog)
        fill(self.profile_table, [
            (field.get("display_name", key), catalog.get(key, field)["physical_name"],
             field["physical_name"], self.field_type(field), METHODS.get(rule["operation"], rule["operation"]),
             json.dumps(rule.get("params", {}), ensure_ascii=False),
             "●" if self.raw_profile.get("base_profile_id") and key in self.raw_profile.get("field_rules", {}) else "", "")
            for key, rule, field in entries
        ])
        for row, (key, rule, field) in enumerate(entries):
            button = QPushButton("설정…")
            button.clicked.connect(lambda checked=False, key=key: self.call(lambda: self.edit_field(key)))
            self.profile_table.setCellWidget(row, 7, button)
        self.profile_table.resizeColumnsToContents()

    @staticmethod
    def field_type(field):
        kind = field["data_type"]
        if kind in {"NUMERIC", "DECIMAL"}:
            return f'{kind}({field["precision"]},{field["scale"]})'
        if kind in {"CHAR", "VARCHAR"}:
            return f'{kind}({field["length"]})'
        return kind

    def add_field(self):
        self.edit_field(None)

    def edit_field(self, key):
        profile = self.current_profile()
        catalog = self.provider.get_fields()
        if key is None:
            rule = {"operation": "CONSTANT", "params": {"value": ""}}
            field = {"data_type": "VARCHAR", "length": 50, "nullable": True}
        else:
            rule = profile["field_rules"][key]
            field = next(field for candidate, _, field in plan(profile, catalog) if candidate == key)
        layer = self.project.mapLayer(self.layers.currentData() or "")
        names = layer.fields().names() if isinstance(layer, QgsVectorLayer) else []
        dialog = FieldEditor(self, key or "", rule, field, names, self.provider.get_operations())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result_key = dialog.result_key
        if key is None and result_key in profile["field_rules"]:
            raise ValueError("이미 정의된 기준 의미 ID입니다.")
        proposed = deepcopy(self.raw_profile)
        proposed.setdefault("field_rules", {})[result_key] = dialog.result_rule
        profiles = self.provider.profiles()
        profiles[proposed["id"]] = proposed
        plan(self.provider.resolve(proposed["id"], profiles), catalog)
        self.raw_profile = proposed
        self.invalidate()
        self.refresh_profile_table()
        self.status.setText("필드 설정 변경 · Preview에 적용됨 · 보관하려면 새 리비전 저장")

    def save_profile(self):
        saved = self.provider.save(self.raw_profile)
        self.reload_profiles(saved["id"])
        self.status.setText(f'Profile r{saved["revision"]} 저장')

    def context(self):
        layer = self.project.mapLayer(self.layers.currentData() or "")
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise ValueError("입력 레이어를 선택하세요.")
        profile = self.current_profile()
        names = layer.fields().names()
        rows = [(f.id(),dict(zip(names,map(scalar,f.attributes()))),f.geometry()) for f in layer.getFeatures()]
        if not rows:
            raise ValueError("입력 객체가 없습니다.")
        return layer,profile,rows,Spatial(layer)

    def show_findings(self, layer, findings):
        self.findings, self.finding_layer = findings, layer.id()
        fill(self.qc_table, [(r.feature_id,r.rule_name,r.severity,r.field,r.message,r.measured,r.expected,r.status) for r in findings])

    def scan(self, selected=False):
        layer,p,rows,spatial = self.context()
        ids = set(layer.selectedFeatureIds()) if selected else None
        if selected and not ids:
            raise ValueError("재검사할 객체를 선택하세요.")
        findings = run_qc(layer.name(),rows,p.get("qc_rules",{}),spatial,"PRE",ids)
        self.show_findings(layer,findings)
        self.status.setText(f'QC {len(findings)}건 · 구조화 차단 {"예" if blocked(findings) else "아니요"}')

    def finding(self):
        i = self.qc_table.currentRow()
        layer = self.project.mapLayer(self.finding_layer or "")
        if layer is None or not 0 <= i < len(self.findings):
            raise ValueError("결과 행을 선택하세요.")
        return layer,self.findings[i]

    def select_finding(self):
        layer,r = self.finding()
        self.iface.setActiveLayer(layer)
        layer.selectByIds([r.feature_id])

    def zoom_finding(self):
        layer,r = self.finding()
        canvas = self.iface.mapCanvas()
        geom = Spatial.transform(r.geometry,layer.crs(),canvas.mapSettings().destinationCrs(),self.project)
        if geom.isEmpty():
            raise ValueError("오류 객체에 지도 위치가 없습니다.")
        bounds = QgsRectangle(geom.boundingBox())
        bounds.grow(max(canvas.mapUnitsPerPixel()*40,bounds.width()*0.1))
        canvas.setExtent(bounds)
        canvas.refresh()

    def calculate(self):
        layer,p,rows,spatial = self.context()
        catalog = self.provider.get_fields()
        findings,changes,output,fields = preview(layer.name(),rows,p,catalog,spatial)
        # Include every output attribute, input geometry, and resolved profile.
        key = (layer.id(), layer.crs().authid(), p, catalog, changes,
               [(fid,attrs,bytes(g.asWkb())) for fid,attrs,g in rows])
        return layer,p,spatial,findings,changes,output,fields,key

    def prepare(self):
        layer,p,spatial,findings,changes,output,fields,key = self.calculate()
        self.show_findings(layer,findings)
        fill(self.preview_table,changes)
        if blocked(findings):
            self.invalidate()
            self.tabs.setCurrentIndex(0)
            self.status.setText("Pre-QC 차단 오류를 해결하세요.")
            return
        self.preview_state = key
        errors = sum(str(row[-1]).startswith("ERROR") for row in changes)
        self.status.setText(f"Preview · 객체 {len(output)}개 · 필드 결과 {len(changes)}건 · 계산 오류 {errors}건")

    def execute(self):
        if self.preview_state is None:
            raise ValueError("Preview를 먼저 실행하세요.")
        layer,p,spatial,findings,changes,output,fields,key = self.calculate()
        if self.preview_state != key:
            self.invalidate()
            raise ValueError("원본·Profile·계산 결과가 변경됐습니다. Preview를 다시 실행하세요.")
        if blocked(findings) or any(str(row[-1]).startswith("ERROR") for row in changes):
            raise ValueError("차단 오류를 해결하세요.")
        if any(f["data_type"] == "GEOMETRY" for f in fields):
            raise ValueError("도형은 원본 WKB와 CRS를 그대로 복사합니다. 도형 속성 출력은 지원하지 않습니다.")
        result = post_qc(layer.name(),output,p,fields,spatial)
        self.show_findings(layer,result)
        if blocked(result):
            self.tabs.setCurrentIndex(0)
            raise ValueError("Post-QC 차단 오류: 결과 레이어를 생성하지 않았습니다.")
        name = f'{layer.name()} · {p["name"]} r{p["revision"]}'
        target = QgsVectorLayer(QgsWkbTypes.displayString(layer.wkbType()),name,"memory")
        target.setCrs(layer.crs())
        provider = target.dataProvider()
        if not target.isValid() or not provider.addAttributes([qgis_field(f) for f in fields]):
            raise ValueError("임시 출력 필드 생성 실패")
        target.updateFields()
        features = []
        for _, attrs, geom in output:
            feature = QgsFeature(target.fields())
            feature.setGeometry(geom)
            feature.setAttributes([output_value(attrs[f["physical_name"]]) for f in fields])
            features.append(feature)
        ok, inserted = provider.addFeatures(features)
        if not ok or len(inserted) != len(features):
            raise ValueError("임시 출력 실패 · 원본에 변경 없음")
        # Check the staged layer as well: QVariant/provider conversion can lose precision.
        names = target.fields().names()
        staged = [(fid, dict(zip(names,map(scalar,f.attributes()))),f.geometry())
                  for (fid, _, _), f in zip(output, (target.getFeature(item.id()) for item in inserted))]
        for (_, attrs, _), (_, actual, _) in zip(output, staged):
            for field in fields:
                key = field["physical_name"]
                if field["data_type"] in {"NUMERIC","DECIMAL","BIGINT"} and attrs[key] is not None:
                    from decimal import Decimal
                    if actual[key] is None or Decimal(str(actual[key])) != Decimal(str(attrs[key])):
                        raise ValueError(f"{key}: 임시 레이어가 값의 정밀도를 보존하지 못합니다.")
        stored_findings = post_qc(target.name(),staged,p,fields,Spatial(target))
        self.show_findings(layer,stored_findings)
        if blocked(stored_findings):
            self.tabs.setCurrentIndex(0)
            raise ValueError("임시 출력 Post-QC 실패 · 원본에 변경 없음")
        target.setCustomProperty("geoflow_qc_structure/profile",json.dumps(p,ensure_ascii=False))
        target.setCustomProperty("geoflow_qc_structure/output_fields",json.dumps(fields,ensure_ascii=False))
        target.updateExtents()
        self.project.addMapLayer(target)
        self.status.setText(f"임시 출력 {len(features)}개 · Post-QC {len(stored_findings)}건 · 원본 변경 없음")

