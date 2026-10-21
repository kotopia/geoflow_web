# 제목: app/protection.py
# 기능: 폼 입력·편집 버퍼·미전송 큐 검사와 명시적 전환 시 입력 보존
"""Read-only transition inspection for QGIS-owned edit state."""
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


def inspect(engine):
    main = engine.work
    drafts = ([p for p in main.pages.values() if p.dirty] + list(main.archives)) if main is not None else []
    return {'drafts': drafts,
            'buffers': [l for l in owned_layers(engine.active_context) if l.isModified()]}


# ============================================================
# 미저장 폼 입력의 원자적 복구 JSON 저장
# ============================================================
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
