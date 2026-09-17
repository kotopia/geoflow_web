# 제목: forms/common/diagnostics.py
# 기능: 안전한 상태 요약과 snapshot/대기 큐 필드 계약의 읽기 전용 진단
"""Read-only diagnostics; never upgrade snapshots or discard pending edits."""
import json
import sqlite3
from pathlib import Path

TARGETS = {'WTL_ETC_PS','WTL_FIRE_PS','WTL_FLOW_PS','WTL_PIPE_LM','WTL_VALV_PS'}
REQUIRED = {'date','status','worker_id','project_id'}
OBSOLETE = {'ist_ymd','sys_chk'}


def integration_summary(state):
    """Project only safe scalar state; never serialize layer sources or reprs."""
    result = {key: state.get(key) for key in
              ('available', 'authenticated', 'ready', 'epoch', 'project_id',
               'project_code', 'can_write')}
    result['layers'] = []
    for layer in state.get('layers') or ():
        try:
            result['layers'].append({'id': layer.id(),
                'standard_name': str(layer.customProperty('geoflow/standard_name', '')),
                'valid': layer.isValid(), 'readonly': layer.readOnly()})
        except RuntimeError:
            result['layers'].append({'unavailable': True})
    return result


def diagnose_contract(manifest, package_path):
    result = {'manifest_missing': {}, 'snapshot_missing': {}, 'pending_legacy_fields': [],
              'pending_count': 0, 'outbox_count': 0, 'snapshot_state': 'unavailable'}
    layers = [r for r in manifest.get('layers',[]) if r.get('standard_name') in TARGETS]
    for row in layers:
        missing = REQUIRED - {f['name'] for f in row.get('fields',[])}
        if missing: result['manifest_missing'][row['standard_name']] = sorted(missing)
    path=Path(package_path or '')
    if not path.is_file(): return result
    conn=None
    try:
        conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for row in layers:
            table=row.get('physical_name','')
            if table not in {n.lower() for n in TARGETS}: continue
            fields={r[1] for r in conn.execute('PRAGMA table_info("'+table+'")')} if table in tables else set()
            missing=REQUIRED-fields
            if missing: result['snapshot_missing'][row['standard_name']]=sorted(missing)
        legacy=set()
        if '_geoflow_pending_change' in tables:
            for row in conn.execute('SELECT attributes_json FROM _geoflow_pending_change'):
                result['pending_count']+=1
                legacy.update(set(json.loads(row[0] or '{}')) & OBSOLETE)
        if '_geoflow_outbox' in tables:
            for row in conn.execute('SELECT payload_json FROM _geoflow_outbox'):
                result['outbox_count']+=1
                for change in json.loads(row[0]).get('changes',[]):
                    legacy.update(set(change.get('attributes',{})) & OBSOLETE)
        result['pending_legacy_fields']=sorted(legacy)
        result['snapshot_state']='legacy_contract' if result['snapshot_missing'] else 'current_contract'
    except (sqlite3.Error,ValueError,TypeError,KeyError):
        result['snapshot_state']='diagnostic_failed_preserved'
    finally:
        if conn is not None:conn.close()
    return result
