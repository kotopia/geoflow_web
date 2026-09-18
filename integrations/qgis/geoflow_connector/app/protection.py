# 제목: app/protection.py
# 기능: 폼 입력·편집 버퍼·미전송 큐 검사와 명시적 전환 시 입력 보존
"""Read-only transition inspection and durable, explicitly identified form drafts."""
import json
import os
import sqlite3
import uuid
from pathlib import Path
from qgis.PyQt.QtWidgets import QLineEdit, QComboBox, QAbstractSpinBox, QAbstractButton, QTextEdit, QPlainTextEdit
from qgis.core import QgsProject


# ============================================================
# 현재 프로젝트 소유 레이어와 미전송 상태 조사
# ============================================================
def owned_layers(context):
    context = context or {}
    result = []
    for lid in context.get('layer_ids', []):
        layer = QgsProject.instance().mapLayer(lid)
        if (layer is not None and layer.customProperty('geoflow/managed', False)
                and str(layer.customProperty('geoflow/project_id', '')) == str(context.get('project_id', ''))
                and str(layer.customProperty('geoflow/package_path', '')) == str(context.get('package_path', ''))):
            result.append(layer)
    return result


def queue_status(context):
    context = context or {}
    path = context.get('package_path')
    if not path:
        return {'pending': 0, 'outbox': 0}
    # Do not create a database or queue table merely to inspect it.
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {label: db.execute('SELECT count(*) FROM ' + table).fetchone()[0] if table in tables else 0
                for label, table in [('pending', '_geoflow_pending_change'), ('outbox', '_geoflow_outbox')]}


def inspect(engine):
    main = engine.work
    drafts = ([p for p in main.pages.values() if p.dirty] + list(main.archives)) if main is not None else []
    return {'drafts': drafts, 'buffers': [l for l in owned_layers(engine.active_context) if l.isModified()],
            'queue': queue_status(engine.active_context)}


# ============================================================
# 미저장 폼 입력의 원자적 복구 JSON 저장
# ============================================================
def checkpoint(engine):
    """Atomic JSON export, never automatic replay onto another object/project."""
    main = engine.work
    if main is None:
        return None
    pages = [p for p in main.pages.values() if p.dirty] + list(main.archives)
    if not pages:
        return None
    rows = []
    for page in pages:
        values = {}
        for widget in page.form.input_widgets((QLineEdit, QComboBox, QAbstractSpinBox, QAbstractButton, QTextEdit, QPlainTextEdit)):
            name = widget.objectName()
            if not name or name.startswith('qt_'):
                continue
            if isinstance(widget, QComboBox):
                value = {'value': widget.currentData(), 'label': widget.currentText()}
            elif isinstance(widget, QAbstractButton):
                value = widget.isChecked()
            elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
                value = widget.toPlainText()
            else:
                value = widget.text()
            values[name] = value
        rows.append({'project_id': getattr(page, 'project_id', ''), 'project_name': page.project_name,
                     'layer_id': page.layer_id, 'standard': page.standard, 'feature_id': page.feature_id,
                     'widgets': values})
    directory = Path(engine._app_data_location()) / 'GeoFlowConnector' / 'form-drafts'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (str(uuid.uuid4()) + '.json')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'format': 1, 'automatic_replay': False, 'drafts': rows}, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    os.replace(temporary, target)
    return target


# ============================================================
# 프로젝트 전환 시 플러그인 소유 레이어만 제거
# ============================================================
def remove_owned(context):
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    # Remove only exact IDs with matching ownership, never group contents.
    project.removeMapLayers([l.id() for l in owned_layers(context)])
    for group in list(root.findGroups()):
        if group.customProperty('geoflow/context_owner', '') != str((context or {}).get('project_id', '')):
            continue
        for child in reversed(group.findGroups()):
            if not child.children():
                child.parent().removeChildNode(child)
        if not group.children():
            group.parent().removeChildNode(group)
