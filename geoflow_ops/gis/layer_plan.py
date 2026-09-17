"""Central Final Layer Plan; tenant scope rows contain no GIS definition logic."""
from __future__ import annotations

from typing import Any

from django.db import DatabaseError, connections
from django.http import Http404

from . import central_definitions


def _table_exists(alias: str, relation: str) -> bool:
    try:
        with connections[alias].cursor() as cursor:
            cursor.execute('SELECT to_regclass(%s) IS NOT NULL',[relation])
            return bool(cursor.fetchone()[0])
    except DatabaseError:
        return False


def scope_capability_ready(alias: str) -> bool:
    # Name retained for callers. Capability/profile tables are intentionally no
    # longer part of readiness; catalog scope + central definition are enough.
    return _table_exists(alias,'prj.scope_item') and central_definitions.central_snapshot() is not None


def _scope_rows(cursor, *, project_id=None, project_ids=None):
    sql = '''SELECT project_id::text,lv2_id::text,lv3_id::text,lv4_id::text
        FROM prj.scope_item WHERE project_id IS NOT NULL'''
    params = []
    if project_id is not None:
        sql += ' AND project_id=%s'
        params.append(str(project_id))
    elif project_ids is not None:
        sql += ' AND project_id=ANY(%s::uuid[])'
        params.append([str(value) for value in project_ids])
    cursor.execute(sql, params)
    return cursor.fetchall()


def _project_scopes(alias, project_id):
    with connections[alias].cursor() as cursor:
        return [
            {'2':row[1],'3':row[2],'4':row[3]}
            for row in _scope_rows(cursor, project_id=project_id)
        ]


def _scope_keys(scopes):
    return {(level,value) for scope in scopes for level,value in scope.items() if value}


def _resolved_layer_ids(data, scopes, config):
    keys=_scope_keys(scopes)
    selected={binding['layer_id'] for binding in data['layer_catalogs']
              if (str(binding['catalog_level']),binding['catalog_item_id']) in keys}
    group=config.get('group_id')
    if group:
        # Selecting a group explicitly imports every layer linked to that group.
        # Group scope constrains central authoring choices; it does not silently
        # remove part of an already selected group at project runtime.
        selected.update(row['layer_id'] for row in data['group_layers'] if row['group_id']==group)
    for layer_ids in config.get('additions',{}).values():
        selected.update(layer_ids)
    return selected


def project_layer_plan(alias: str, project_id) -> dict[str, Any]:
    data=central_definitions.central_snapshot()
    if data is None or not _table_exists(alias,'prj.scope_item'):
        return {'ready':False,'gis_enabled':False,'project_id':str(project_id),'profile':None,
                'capabilities':[],'layers':[],'reason':'central_definition_not_applied'}
    scopes=_project_scopes(alias,project_id)
    with connections[alias].cursor() as cursor:
        config=central_definitions.project_config(cursor,project_id)
    layer_ids=_resolved_layer_ids(data,scopes,config)
    layers=[]
    for layer in data['layers']:
        if layer['id'] not in layer_ids or not layer['active']:
            continue
        layers.append({'id':layer['id'],'standard_name':layer['standard_name'],
            'physical_name':layer['physical_name'],'label':layer['label'],'domain':layer['domain_code'],
            'geometry_kind':layer['geometry_kind'],'required':False,'sort_order':layer['sort_order']})
    definition=central_definitions.resolve(data,config,layers)
    return {'ready':True,'gis_enabled':bool(layers),'project_id':str(project_id),'profile':None,
            'definition':{'version':definition['version'],'revision':definition['revision'],
                          'group_id':config.get('group_id')},
            'form_definition':definition,
            'capabilities':[{'catalog_level':int(level),'catalog_item_id':item}
                            for level,item in sorted(_scope_keys(scopes))],
            'layers':layers,'reason':'ok' if layers else 'no_central_layer_binding'}


def gis_enabled_project_ids(alias: str) -> set[str] | None:
    data=central_definitions.central_snapshot()
    if data is None or not _table_exists(alias,'prj.scope_item'): return None
    with connections[alias].cursor() as cursor:
        scopes={}
        for project_id,lv2,lv3,lv4 in _scope_rows(cursor):
            scopes.setdefault(project_id,[]).append({'2':lv2,'3':lv3,'4':lv4})
        cursor.execute("SELECT to_regclass('gis.project_definition')")
        configs={}
        if cursor.fetchone()[0]:
            cursor.execute('SELECT project_id::text,group_id::text,additions FROM gis.project_definition')
            import json
            for project_id,group_id,additions in cursor.fetchall():
                if isinstance(additions,str): additions=json.loads(additions)
                configs[project_id]={'group_id':group_id,'additions':additions or {}}
    empty={'group_id':None,'additions':{}}
    return {project_id for project_id,values in scopes.items()
            if _resolved_layer_ids(data,values,configs.get(project_id,empty))}


def allowed_standard_names(plan: dict[str, Any]) -> set[str]:
    return {str(row['standard_name']).upper() for row in plan.get('layers') or []}


def allowed_standard_names_for_projects(alias: str, project_ids) -> set[str]:
    ids=[str(value) for value in project_ids]
    if not ids: return set()
    data=central_definitions.central_snapshot()
    if data is None: return set()
    with connections[alias].cursor() as cursor:
        scopes=[
            {'2':row[1],'3':row[2],'4':row[3]}
            for row in _scope_rows(cursor, project_ids=ids)
        ]
        cursor.execute("SELECT to_regclass('gis.project_definition')")
        configs=[]
        if cursor.fetchone()[0]:
            cursor.execute('SELECT group_id::text,additions FROM gis.project_definition WHERE project_id=ANY(%s::uuid[])',[ids])
            configs=cursor.fetchall()
    keys=_scope_keys(scopes)
    layer_ids={row['layer_id'] for row in data['layer_catalogs']
               if (str(row['catalog_level']),row['catalog_item_id']) in keys}
    import json
    for group_id,additions in configs:
        if group_id:
            layer_ids.update(row['layer_id'] for row in data['group_layers'] if row['group_id']==group_id)
        if isinstance(additions,str): additions=json.loads(additions)
        for values in (additions or {}).values(): layer_ids.update(values if isinstance(values,list) else [])
    return {row['standard_name'].upper() for row in data['layers'] if row['id'] in layer_ids and row['active']}


def require_enabled_layer_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not plan.get('ready'): raise Http404('Central GIS definition is not available.')
    if not plan.get('gis_enabled'): raise Http404("GIS is not enabled by this project's catalog/group definition.")
    return plan
