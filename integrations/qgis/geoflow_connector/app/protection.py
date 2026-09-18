# 제목: app/protection.py
# 기능: 폼 입력·편집 버퍼·미전송 큐 검사와 명시적 전환 시 입력 보존
"""Read-only transition inspection and durable, explicitly identified form drafts."""
import json
import math
import os
import sqlite3
import uuid
import datetime as dt
from pathlib import Path
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QDate, QDateTime, Qt


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
def json_safe(value):
    """Return strict-JSON data for Python, Qt and QGIS widget values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, QDateTime):
        return value.toString(Qt.DateFormat.ISODate) if value.isValid() else None
    if isinstance(value, QDate):
        return value.toString(Qt.DateFormat.ISODate) if value.isValid() else None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    try:
        if value.isNull():
            return None
    except AttributeError:
        pass
    return str(value)


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
        current = page.form.values()
        values = {}
        for field_id, handle in page.form.handles.items():
            value = current.get(field_id)
            editor = handle.editor
            if hasattr(editor, 'currentData') and hasattr(editor, 'currentText'):
                value = {'value': value, 'label': editor.currentText()}
            values[str(field_id)] = json_safe(value)
        rows.append({'project_id': json_safe(getattr(page, 'project_id', '')),
                     'project_name': json_safe(page.project_name),
                     'layer_id': json_safe(page.layer_id), 'standard': json_safe(page.standard),
                     'feature_id': json_safe(page.feature_id),
                     'widgets': values})
    directory = Path(engine._app_data_location()) / 'GeoFlowConnector' / 'form-drafts'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (str(uuid.uuid4()) + '.json')
    temporary = target.with_suffix('.tmp')
    try:
        payload = json.dumps(
            {'format': 1, 'automatic_replay': False, 'drafts': rows},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        temporary.write_text(payload, encoding='utf8')
        os.replace(temporary, target)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            # Preserve the original checkpoint exception; stale .tmp files are never replayed.
            pass
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
