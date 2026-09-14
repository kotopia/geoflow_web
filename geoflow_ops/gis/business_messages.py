"""Offline cross-check of original pgAdmin notices against an approval candidate."""
import hashlib
import json
import re
from .business_fields import TABLES, COMMON
from .business_approval import ApprovalRejected, SQL


def verify_messages(raw, approval):
    text=raw.decode('utf-8-sig');decoder=json.JSONDecoder();reports={}
    for match in re.finditer(r'(?m)^\s*(?:NOTICE:\s*)?(\d{2}_[\w.]+):\s*',text):
        key=match.group(1)
        if key in reports:raise ApprovalRejected('Duplicate notice section')
        reports[key]=decoder.raw_decode(text[match.end():])[0]
    if ('98_stopped' in reports or not reports.get('99_completed',{}).get('readonly_queries_finished')
            or not reports.get('01_project_identity',{}).get('verified')):
        raise ApprovalRejected('Original messages are incomplete or target verification failed')
    context=approval['context'];project=reports['01_project_identity']
    if (reports['00_database']['database']!=context['database'] or project['cached_uuid']!=context['project_id']
            or project['expected_code']!=context['project_code']
            or reports['04_effective_profile']['profile_id']!=approval['invariants']['profile']):
        raise ApprovalRejected('Messages database/project/profile differs from approval')
    old={r['id']:r for r in approval['before']['fields']}
    target_ids=set();disabled_ids=set()
    for op in approval['operations']:
        sql,p=op['sql'],op['parameters']
        if sql==SQL['disable']:disabled_ids.add(p[1]);target_ids.add(p[1])
        elif sql==SQL['field_update']:target_ids.add(p[-1])
        elif sql==SQL['bind'] and not p[1].startswith('new-field:'):target_ids.add(p[1])
    seen=set();stale=[];sys_tables=[]
    for table in TABLES:
        ft=reports['10_table_state.'+table]['feature_metadata']
        active=[r['id'] for r in ft if r['active']]
        if active!=[approval['invariants']['physical'][table]['feature_id']]:
            raise ApprovalRejected('Feature ID mismatch')
        for row in reports['14_metadata_and_shared_links.'+table]:
            fid=row['field_id']
            if row['field']=='sys_chk':sys_tables.append(table)
            selected=[p for p in row['profile_links'] if p['profile_id']==approval['invariants']['profile']]
            if row['physical_missing'] and row['field'] not in set(COMMON)|{'ist_ymd','sys_chk'} and any(p['enabled'] for p in selected):
                stale.append({'table':table,'field':row['field'],'field_id':fid})
            if fid not in target_ids:continue
            expected=old.get(fid)
            if not expected or expected['feature_type_id']!=active[0]:raise ApprovalRejected('Field ID mismatch')
            for source,column in (('field','physical_name'),('type','data_type'),('group_key','code_group_key'),('widget','widget_type')):
                if row[source]!=expected[column]:raise ApprovalRejected('Messages field before-value mismatch')
            actual_links={(p['profile_id'],p['enabled'],p['required'],p['editable'],p['visible'],p['sort_order']) for p in row['profile_links']}
            expected_links={(p['profile_id'],p['enabled'],p['required'],p['editable'],p['visible'],p['sort_order']) for p in approval['before']['links'] if p['field_def_id']==fid}
            if actual_links!=expected_links:raise ApprovalRejected('Messages profile settings mismatch')
            seen.add(fid)
    if (seen!=target_ids or len(target_ids)!=51 or len(stale)!=31
            or {r['field_id'] for r in stale}!=disabled_ids or sorted(sys_tables)!=['wtl_pipe_lm','wtl_valv_ps']):
        raise ApprovalRejected('Messages target set differs from reviewed 31/51-row sets')
    return dict(verified=True,messages_sha256=hashlib.sha256(raw).hexdigest(),matched_existing_fields=51,
                selected_profile_id=approval['invariants']['profile'],disabled_fields=stale,
                sys_chk_tables=sorted(sys_tables),
                coverage='IDs, exposed field values and profile settings. Full before/after values and profile_field row IDs are separately bound by approval snapshot.')
