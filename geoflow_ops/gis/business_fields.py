"""Targeted, idempotent GIS business-field reconciliation. No seed execution."""
from uuid import UUID, uuid4
import re

TABLES = ('wtl_etc_ps', 'wtl_fire_ps', 'wtl_flow_ps', 'wtl_pipe_lm', 'wtl_valv_ps')
REFERENCES = {
 'wtl_etc_ps': {'ftr_cde': 'WTL_ETC_PS.FTR_CDE'},
 'wtl_fire_ps': {'cst_cde': 'WTL_FIRE_PS.CST_CDE'},
 'wtl_flow_ps': {'cst_cde': 'WTL_FLOW_PS.CST_CDE'},
 'wtl_pipe_lm': {'saa_cde': 'WTL_PIPE_LM.SAA_CDE', 'mop_cde': 'WTL_PIPE_LM.MOP_CDE'},
 'wtl_valv_ps': {n: 'WTL_VALV_PS.' + n.upper() for n in ('ftr_cde','val_mof','val_mop','sae_cde','mth_cde','cst_cde','off_cde','sbc_cde')},
}
COMMON = {'date': ('ist_ymd', 'date', '작업일', 'date'),
          'status': ('sys_chk', 'text', '작업상태', 'select'),
          'worker_id': (None, 'uuid', '작업자', 'relation')}


class ContractConflict(RuntimeError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('Business field preflight conflicts; no changes applied')


def inspect_contract(cur, project_id):
    project_id = str(UUID(str(project_id)))
    cur.execute('SELECT id::text FROM prj.projects WHERE id=%s', [project_id])
    if not cur.fetchone():
        raise ContractConflict(['project_not_found'])
    cur.execute("SELECT p.id::text FROM gis.project_profile pp JOIN gis.profile p ON p.id=pp.profile_id AND p.active WHERE pp.project_id=%s AND pp.status='active'", [project_id])
    profiles = cur.fetchall()
    if len(profiles) > 1:
        raise ContractConflict(['multiple_active_project_profiles'])
    if not profiles:
        cur.execute("SELECT id::text FROM gis.profile WHERE active AND code IN ('GEOFLOW_BASE_V1','GEOFLOW_DEV_BASE') ORDER BY CASE code WHEN 'GEOFLOW_BASE_V1' THEN 0 ELSE 1 END LIMIT 1")
        profiles = cur.fetchall()
    if not profiles:
        raise ContractConflict(['active_profile_missing'])
    profile = profiles[0][0]
    state = {'profile': profile, 'tables': {}, 'groups': {}}
    cur.execute("""WITH fallback AS (
        SELECT id FROM gis.profile WHERE active AND code IN ('GEOFLOW_BASE_V1','GEOFLOW_DEV_BASE')
        ORDER BY CASE code WHEN 'GEOFLOW_BASE_V1' THEN 0 ELSE 1 END LIMIT 1
    ), usage AS (
        SELECT p.id,
          EXISTS(SELECT 1 FROM gis.project_profile pp JOIN gis.profile gp ON gp.id=pp.profile_id AND gp.active
                 WHERE pp.project_id=p.id AND pp.status='active' AND pp.profile_id=%s) AS explicit_use,
          NOT EXISTS(SELECT 1 FROM gis.project_profile pp JOIN gis.profile gp ON gp.id=pp.profile_id AND gp.active
                     WHERE pp.project_id=p.id AND pp.status='active')
          AND EXISTS(SELECT 1 FROM fallback WHERE id=%s) AS fallback_use
        FROM prj.projects p
    ) SELECT count(*) FILTER(WHERE explicit_use),count(*) FILTER(WHERE fallback_use),
             count(*) FILTER(WHERE (explicit_use OR fallback_use) AND id<>%s)
      FROM usage""", [profile, profile, project_id])
    state['profile_impact'] = dict(zip(('explicit_projects','fallback_projects','other_effective_projects'),cur.fetchone()))
    for table in TABLES:
        cur.execute("SELECT column_name, format_type(a.atttypid,a.atttypmod) FROM information_schema.columns c JOIN pg_attribute a ON a.attrelid=(quote_ident(c.table_schema)||'.'||quote_ident(c.table_name))::regclass AND a.attname=c.column_name WHERE c.table_schema='gis' AND c.table_name=%s", [table])
        columns = dict(cur.fetchall())
        cur.execute("SELECT column_name,column_default,is_nullable,is_generated,generation_expression FROM information_schema.columns WHERE table_schema='gis' AND table_name=%s", [table])
        details = {r[0]:dict(zip(('default','nullable','generated','generation_expression'),r[1:])) for r in cur.fetchall()}
        cur.execute("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=to_regclass(%s) ORDER BY conname", ['gis.'+table])
        constraints = cur.fetchall()
        cur.execute("SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid=to_regclass(%s) AND NOT tgisinternal ORDER BY tgname", ['gis.'+table])
        triggers = cur.fetchall()
        cur.execute('SELECT id::text FROM gis.meta_feature_type WHERE physical_name=%s AND active', [table])
        ft = cur.fetchone()
        fields = {}
        if ft:
            cur.execute('SELECT id::text, physical_name, data_type, code_group_key, label, standard_name, widget_type FROM gis.meta_field_def WHERE feature_type_id=%s', [ft[0]])
            fields = {r[1]: dict(zip(('id','name','type','group','label','standard','widget'), r)) for r in cur.fetchall()}
        links = {}
        for field in fields.values():
            cur.execute('SELECT profile_id::text, enabled, required, editable, visible, sort_order FROM gis.profile_field WHERE field_def_id=%s ORDER BY profile_id', [field['id']])
            links[field['id']] = cur.fetchall()
        counts = {}
        for old, new in (('ist_ymd','date'), ('sys_chk','status')):
            for name in (old,new):
                if name in columns:
                    cur.execute(f'SELECT count(*) FILTER (WHERE "{name}" IS NOT NULL),bit_xor(hashtextextended("{name}"::text,0)) FROM gis."{table}"')
                    count, fingerprint = cur.fetchone()
                    counts[name] = count
                    counts[name+'_fingerprint'] = fingerprint
        if 'worker_id' in columns:
            # Aggregate only; never print employee IDs or names.
            cur.execute(f'SELECT count(*), count(*) FILTER (WHERE t.worker_id IS NOT NULL), count(*) FILTER (WHERE t.worker_id IS NOT NULL AND e.id IS NULL), count(*) FILTER (WHERE t.worker_id::text=t.project_id::text) FROM gis."{table}" t LEFT JOIN hr.employee_profile e ON e.id::text=t.worker_id::text AND e.is_deleted=false WHERE t.project_id=%s', [project_id])
            counts['workers_total_assigned_unresolved_project_id'] = cur.fetchone()
        state['tables'][table] = dict(columns=columns, column_details=details, constraints=constraints, triggers=triggers, feature_id=ft[0] if ft else None, fields=fields, links=links, counts=counts)
    keys = {v for m in REFERENCES.values() for v in m.values()} | {'GEOFLOW.WORK_STATUS'}
    cur.execute('SELECT group_key, active FROM gis.ref_code_group WHERE group_key=ANY(%s)', [sorted(keys)])
    state['groups'] = dict(cur.fetchall())
    cur.execute("SELECT v.code,v.label FROM gis.ref_code_value v JOIN gis.ref_code_group g ON g.id=v.group_id WHERE g.group_key='GEOFLOW.WORK_STATUS' AND g.active AND v.active AND (v.valid_from IS NULL OR v.valid_from<=CURRENT_DATE) AND (v.valid_to IS NULL OR v.valid_to>=CURRENT_DATE)")
    state['status_values'] = cur.fetchall()
    return state


def plan_contract(state):
    operations, conflicts = [], []
    def add(sql, params=()): operations.append((sql, list(params)))
    for table in TABLES:
        row = state['tables'][table]; cols = row['columns']; fields = row['fields']
        if not cols or not row['feature_id']:
            conflicts.append(dict(table=table, reason='table_or_feature_metadata_missing')); continue
        for name, field in fields.items():
            if name in cols or name in COMMON or name in {'ist_ymd', 'sys_chk'}:
                continue
            # Keep evidence/IDs and every other profile. A removed physical
            # column must not remain enabled in this project's Snapshot.
            if any(link[0] == state['profile'] and link[1] for link in row['links'].get(field['id'], [])):
                add('UPDATE gis.profile_field SET enabled=false WHERE profile_id=%s AND field_def_id=%s', [state['profile'],field['id']])
        for name, (old, dtype, label, widget) in COMMON.items():
            if old and old in cols and name in cols:
                conflicts.append(dict(table=table, field=name, reason='both_physical_columns', counts=row['counts'])); continue
            if old and old in fields and name in fields:
                conflicts.append(dict(table=table, field=name, reason='both_metadata_definitions', links={n:row['links'][fields[n]['id']] for n in (old,name)}, counts=row['counts'])); continue
            physical = name if name in cols else old if old in cols else None
            detail = row.get('column_details', {}).get(physical, {})
            default = detail.get('default')
            if detail.get('generated', 'NEVER') != 'NEVER':
                conflicts.append(dict(table=table,field=name,reason='generated_business_column_requires_review')); continue
            if name in ('date', 'worker_id') and default is not None:
                conflicts.append(dict(table=table,field=name,reason='automatic_business_default_requires_review',existing=default)); continue
            if name == 'status' and default is not None:
                literal = re.fullmatch(r"'((?:[^']|'')*)'(?:\s*::\s*(?:text|varchar|character varying)(?:\(\d+\))?)?", default.strip())
                codes = [code for code,label in state['status_values'] if label == '미완료']
                if not literal or codes != [literal.group(1).replace("''", "'")]:
                    conflicts.append(dict(table=table,field=name,reason='status_default_requires_review',existing=default)); continue
            actual_type = cols[physical] if physical else dtype
            compatible = actual_type == dtype or (dtype == 'text' and actual_type.startswith(('character varying','varchar','text')))
            if not compatible:
                conflicts.append(dict(table=table, field=name, reason='physical_type_mismatch', actual=actual_type)); continue
            if physical == old and old:
                add(f'ALTER TABLE gis."{table}" RENAME COLUMN "{old}" TO "{name}"')
            elif physical is None:
                add(f'ALTER TABLE gis."{table}" ADD COLUMN "{name}" {dtype} NULL')
            field = fields.get(name) or fields.get(old)
            if field:
                fid = field['id']
                desired = (name, actual_type, label, name.upper(), widget)
                if (field['name'],field['type'],field['label'],field['standard'],field['widget']) != desired:
                    add('UPDATE gis.meta_field_def SET physical_name=%s,data_type=%s,label=%s,standard_name=%s,widget_type=%s WHERE id=%s', [*desired,fid])
            else:
                fid = str(uuid4())
                add('INSERT INTO gis.meta_field_def(id,feature_type_id,physical_name,standard_name,label,data_type,widget_type) VALUES(%s,%s,%s,%s,%s,%s,%s)', [fid,row['feature_id'],name,name.upper(),label,actual_type,widget])
            if not any(link[0] == state['profile'] for link in row['links'].get(fid, [])):
                # Add only missing bindings to this project's effective profile.
                add('INSERT INTO gis.profile_field(id,profile_id,field_def_id,enabled,required,editable,visible,sort_order) VALUES(%s,%s,%s,true,false,true,true,%s)', [str(uuid4()),state['profile'],fid,{'date':900,'status':901,'worker_id':902}[name]])
            if name == 'status':
                old_group = field['group'] if field else None
                if old_group and old_group != 'GEOFLOW.WORK_STATUS':
                    conflicts.append(dict(table=table,field=name,reason='code_group_conflict',existing=old_group))
                elif old_group != 'GEOFLOW.WORK_STATUS':
                    add('UPDATE gis.meta_field_def SET code_group_key=%s WHERE id=%s', ['GEOFLOW.WORK_STATUS',fid])
        for name, key in REFERENCES[table].items():
            field = fields.get(name)
            if name not in cols or not field:
                conflicts.append(dict(table=table,field=name,reason='reference_field_missing')); continue
            if field['group'] and field['group'] != key:
                conflicts.append(dict(table=table,field=name,reason='code_group_conflict',existing=field['group'])); continue
            if field['group'] != key:
                add('UPDATE gis.meta_field_def SET code_group_key=%s WHERE id=%s', [key,field['id']])
        for key in set(REFERENCES[table].values()) | {'GEOFLOW.WORK_STATUS'}:
            if state['groups'].get(key) is not True:
                conflicts.append(dict(table=table,group=key,reason='active_group_missing'))
    labels = [r[1] for r in state['status_values']]
    if sorted(labels) != sorted(['미완료','완료','보완필요']):
        conflicts.append(dict(reason='work_status_values_require_review'))
    if conflicts:
        raise ContractConflict(conflicts)
    return operations


def lock_contract(cur):
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:business-form-contract:v1'))")
    # Recheck under locks; no partially applied plan or concurrent profile edit.
    cur.execute('LOCK TABLE gis.meta_feature_type,gis.meta_field_def,gis.profile_field,gis.ref_code_group,gis.ref_code_value,gis.project_profile,gis.profile IN SHARE ROW EXCLUSIVE MODE')
    for table in TABLES:
        cur.execute(f'LOCK TABLE gis."{table}" IN ACCESS EXCLUSIVE MODE')


def reconcile(cur, project_id):
    lock_contract(cur)
    state = inspect_contract(cur, project_id)
    operations = plan_contract(state)
    for sql, params in operations:
        cur.execute(sql, params)
    if plan_contract(inspect_contract(cur, project_id)):
        raise RuntimeError('Post-apply contract validation failed')
    return len(operations)
