"""Exact reviewed metadata transition. No live-state auto-approval on apply."""
import copy
import hashlib
import json
from collections import Counter

from .business_fields import TABLES, REFERENCES, inspect_contract, plan_contract, lock_contract


class ApprovalRejected(RuntimeError):
    pass


SQL = {
 'disable': 'UPDATE gis.profile_field SET enabled=false WHERE profile_id=%s AND field_def_id=%s',
 'field_update': 'UPDATE gis.meta_field_def SET physical_name=%s,data_type=%s,label=%s,standard_name=%s,widget_type=%s WHERE id=%s',
 'field_insert': 'INSERT INTO gis.meta_field_def(id,feature_type_id,physical_name,standard_name,label,data_type,widget_type) VALUES(%s,%s,%s,%s,%s,%s,%s)',
 'link_insert': 'INSERT INTO gis.profile_field(id,profile_id,field_def_id,enabled,required,editable,visible,sort_order) VALUES(%s,%s,%s,true,false,true,true,%s)',
 'bind': 'UPDATE gis.meta_field_def SET code_group_key=%s WHERE id=%s',
}
COUNTS = {'disable':31, 'field_update':7, 'field_insert':8, 'link_insert':8, 'bind':18}
FIELD_COLS = ('id','feature_type_id','physical_name','standard_name','label','data_type','code_group_key','widget_type')
LINK_COLS = ('id','profile_id','field_def_id','enabled','required','editable','visible','sort_order')


def stable(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def load_approval(path, expected_sha256):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ApprovalRejected('Approval file hash differs from reviewed digest')
    result = json.loads(data)
    if result.get('version') != 1:
        raise ApprovalRejected('Unsupported approval version')
    return result


def snapshot(cur, state):
    ids = [state['tables'][t]['feature_id'] for t in TABLES]
    cur.execute('SELECT '+','.join(FIELD_COLS)+' FROM gis.meta_field_def WHERE feature_type_id=ANY(%s::uuid[]) ORDER BY id', [ids])
    fields = [dict(zip(FIELD_COLS,r)) for r in cur.fetchall()]
    cur.execute('SELECT '+','.join('pf.'+c for c in LINK_COLS)+''' FROM gis.profile_field pf
      JOIN gis.meta_field_def fd ON fd.id=pf.field_def_id
      WHERE fd.feature_type_id=ANY(%s::uuid[]) ORDER BY pf.id''', [ids])
    links = [dict(zip(LINK_COLS,r)) for r in cur.fetchall()]
    return stable({'fields':fields,'links':links})


def invariants(cur, state, existing_field_ids):
    keys = sorted({k for m in REFERENCES.values() for k in m.values()} | {'GEOFLOW.WORK_STATUS'})
    cur.execute('SELECT g.id,g.group_key,g.active,v.id,v.code,v.label,v.active,v.valid_from,v.valid_to FROM gis.ref_code_group g LEFT JOIN gis.ref_code_value v ON v.group_id=g.id WHERE g.group_key=ANY(%s) ORDER BY g.group_key,v.id', [keys])
    refs = cur.fetchall()
    cur.execute('SELECT fd.id,to_jsonb(fd)-%s::text[] FROM gis.meta_field_def fd WHERE fd.id=ANY(%s::uuid[]) ORDER BY fd.id', [list(FIELD_COLS),existing_field_ids])
    untouched_field_columns = cur.fetchall()
    return stable({'profile':state['profile'], 'profile_impact':state['profile_impact'],
      'physical':{t:{k:state['tables'][t][k] for k in ('feature_id','columns','column_details','constraints','triggers')} for t in TABLES},
      'references':refs,'untouched_existing_field_columns':untouched_field_columns})


def ordered(rows):
    return sorted(rows, key=lambda r:r['id'])


def compile_transition(before, operations):
    """Interpret only five exact DML templates; compare columns/values, not counts alone."""
    fields = {r['id']:copy.deepcopy(r) for r in before['fields']}
    links = {r['id']:copy.deepcopy(r) for r in before['links']}
    aliases, normalized, kinds = {}, [], []
    reverse = {v:k for k,v in SQL.items()}
    for sql, values in operations:
        if sql not in reverse:
            raise ApprovalRejected('Unapproved SQL template or mutation target')
        kind = reverse[sql]; kinds.append(kind)
        p = [aliases.get(str(v),v) for v in stable(values)]
        if kind == 'field_insert':
            token = 'new-field:'+str(p[1])+':'+str(p[2])
            if p[0] in fields or str(values[0]) in aliases or token in fields:
                raise ApprovalRejected('Inserted field identifier collision')
            aliases[str(values[0])] = token; p[0] = token
            fields[token] = dict(zip(('id','feature_type_id','physical_name','standard_name','label','data_type','widget_type'),p),code_group_key=None)
        elif kind == 'link_insert':
            token = 'new-link:'+str(p[1])+':'+str(p[2])
            if p[0] in links or token in links or p[2] not in fields:
                raise ApprovalRejected('Inserted link identifier collision or missing field')
            aliases[str(values[0])] = token; p[0] = token
            links[token] = dict(id=p[0],profile_id=p[1],field_def_id=p[2],enabled=True,required=False,editable=True,visible=True,sort_order=p[3])
        elif kind == 'field_update':
            if p[5] not in fields: raise ApprovalRejected('Unknown existing field ID')
            fields[p[5]].update(zip(('physical_name','data_type','label','standard_name','widget_type'),p[:5]))
        elif kind == 'bind':
            if p[1] not in fields: raise ApprovalRejected('Unknown reference field ID')
            fields[p[1]]['code_group_key'] = p[0]
        elif kind == 'disable':
            found = [r for r in links.values() if (r['profile_id'],r['field_def_id']) == tuple(p)]
            if len(found)!=1: raise ApprovalRejected('Profile link must resolve exactly once')
            found[0]['enabled'] = False
        normalized.append({'sql':sql,'parameters':p})
    if Counter(kinds) != Counter(COUNTS):
        raise ApprovalRejected('Plan is not the reviewed 72-statement transition')
    after = {'fields':ordered(list(fields.values())),'links':ordered(list(links.values()))}
    old = {r['id']:r for entity in before.values() for r in entity}
    changed = sum(old.get(r['id']) != r for entity in after.values() for r in entity)
    if changed != 67: raise ApprovalRejected('Plan does not affect exactly 67 distinct metadata rows')
    return after, sorted(normalized, key=lambda x:json.dumps(x,sort_keys=True))


def normalize_inserted_ids(current, approval):
    result = copy.deepcopy(current)
    baseline_ids = {r['id'] for entity in approval['before'].values() for r in entity}
    new_fields = {(r['feature_type_id'],r['physical_name']):r['id'] for r in approval['after']['fields'] if r['id'].startswith('new-field:')}
    aliases = {}
    for row in result['fields']:
        token = new_fields.get((row['feature_type_id'],row['physical_name']))
        if token and row['id'] not in baseline_ids:
            aliases[row['id']] = token; row['id'] = token
    new_links = {(r['profile_id'],r['field_def_id']):r['id'] for r in approval['after']['links'] if r['id'].startswith('new-link:')}
    for row in result['links']:
        row['field_def_id'] = aliases.get(row['field_def_id'],row['field_def_id'])
        token = new_links.get((row['profile_id'],row['field_def_id']))
        if token and row['id'] not in baseline_ids: row['id'] = token
    return {k:ordered(v) for k,v in result.items()}


def build_approval(cur, project_id, context):
    """Read-only candidate export; its independent reviewed hash is mandatory on apply."""
    state = inspect_contract(cur,project_id)
    before = snapshot(cur,state)
    after, ops = compile_transition(before,plan_contract(state))
    return {'version':1,'context':stable(context),'before':before,'after':after,
            'operations':ops,'invariants':invariants(cur,state,[r['id'] for r in before['fields']])}


def guarded_reconcile(cur, project_id, approval, context, *, allow_changes=True):
    if approval.get('version')!=1 or approval['context'] != stable(context):
        raise ApprovalRejected('Approval context mismatch')
    # Same locks as the existing reconciler, before reading or executing the plan.
    lock_contract(cur)
    cur.execute('SELECT current_database()')
    if cur.fetchone()[0] != context['database']: raise ApprovalRejected('Database mismatch')
    cur.execute('SELECT code::text FROM prj.projects WHERE id=%s FOR SHARE',[str(project_id)])
    row = cur.fetchone()
    if not row or row[0] != context['project_code'] or str(project_id)!=context['project_id']:
        raise ApprovalRejected('Project identity mismatch')
    state = inspect_contract(cur,project_id)
    existing_ids = [r['id'] for r in approval['before']['fields']]
    if invariants(cur,state,existing_ids) != approval['invariants']:
        raise ApprovalRejected('Physical schema, references or profile scope drift')
    current = snapshot(cur,state)
    operations = plan_contract(state)
    if normalize_inserted_ids(current,approval) == approval['after']:
        if operations: raise ApprovalRejected('Post-state still requires changes')
        return 0
    if current != approval['before']:
        raise ApprovalRejected('Partial application or metadata ID/value drift')
    if not allow_changes:
        raise ApprovalRejected('Zero-plan precheck changed before lock acquisition')
    after, canonical = compile_transition(current,operations)
    if canonical != approval['operations'] or after != approval['after']:
        raise ApprovalRejected('Locked plan differs from approved targets/columns/values')
    # All comparison and whitelist checks above finish before the first mutation.
    for sql, parameters in operations:
        cur.execute(sql,parameters)
        if cur.rowcount != 1: raise ApprovalRejected('Unexpected affected-row count; transaction must roll back')
    final_state = inspect_contract(cur,project_id)
    if (normalize_inserted_ids(snapshot(cur,final_state),approval) != approval['after']
            or invariants(cur,final_state,existing_ids) != approval['invariants'] or plan_contract(final_state)):
        raise ApprovalRejected('Post-apply verification failed; transaction must roll back')
    return len(operations)
