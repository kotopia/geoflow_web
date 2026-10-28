"""Narrow, restartable relation-only rollout; no code assignment or asset writes."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

CENTRAL = ('control', '0009_gis_reference_code_groups', '0008_saved_filters', 'definition_code_group')
TENANT = ('webgisapp', '0048_gis_project_reference_groups', '0047_remove_survey_targets', 'project_reference_group')
LOCK = 'geoflow.central.gis.definitions'


def migration(central):
    package = 'control' if central else 'geoflow_ops'
    return importlib.import_module(package + '.migrations.' + (CENTRAL if central else TENANT)[1])


def exists(cursor, relation):
    cursor.execute('SELECT to_regclass(%s)', [relation])
    return cursor.fetchone()[0] is not None


def recorded(cursor, app, name):
    cursor.execute('SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app=%s AND name=%s)', [app, name])
    return bool(cursor.fetchone()[0])


def check_state(cursor, central):
    app, name, prerequisite, table = CENTRAL if central else TENANT
    bases = ('gis.definition_code', 'gis.definition_group') if central else ('gis.project_definition', 'prj.projects')
    if not all(exists(cursor, item) for item in bases):
        if central:
            raise CommandError('reference_groups_central_foundation=missing')
        return {'eligible': False, 'applied': False, 'table': False}
    if not exists(cursor, 'django_migrations') or not recorded(cursor, app, prerequisite):
        raise CommandError('reference_groups_prerequisite_missing='+app+'.'+prerequisite)
    present = exists(cursor, 'gis.'+table)
    applied = recorded(cursor, app, name)
    if applied and not present:
        raise CommandError('reference_groups_recorded_relation=missing_restore_required')
    if present:
        expected = [('code_id', 'uuid', True), ('group_id', 'uuid', True), ('sort_order', 'integer', True)] if central else [
            ('project_id', 'uuid', True), ('catalog_l2_id', 'uuid', True), ('group_id', 'uuid', True)]
        cursor.execute('''SELECT attname,format_type(atttypid,atttypmod),attnotnull
                            FROM pg_attribute WHERE attrelid=%s::regclass
                            AND attnum>0 AND NOT attisdropped ORDER BY attnum''', ['gis.'+table])
        if cursor.fetchall() != expected:
            raise CommandError('reference_groups_existing_columns=unexpected')
        cursor.execute('SELECT pg_get_constraintdef(oid),contype,confrelid::regclass::text,confdeltype FROM pg_constraint WHERE conrelid=%s::regclass', ['gis.'+table])
        constraints = cursor.fetchall()
        pk = 'PRIMARY KEY (code_id, group_id)' if central else 'PRIMARY KEY (project_id, catalog_l2_id, group_id)'
        fks = {(row[0].split('(')[1].split(')')[0].replace(' ', ''), row[2].rsplit('.',1)[-1], row[3]) for row in constraints if row[1] == 'f'}
        wanted = {('code_id','definition_code','c'),('group_id','definition_group','r')} if central else {('project_id','projects','c')}
        if pk not in {row[0] for row in constraints} or fks != wanted:
            raise CommandError('reference_groups_existing_constraints=unexpected')
        if not exists(cursor, 'gis.'+table+'_group_idx'):
            raise CommandError('reference_groups_group_index=missing')
    return {'eligible': True, 'applied': applied, 'table': present}


def fingerprint(cursor, *, exclude=()):
    """Hash all existing GIS rows, including asset geometry and definition data."""
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='gis' ORDER BY tablename")
    result = {}
    for (table,) in cursor.fetchall():
        if table in exclude:
            continue
        quoted = '"'+table.replace('"','""')+'"'
        cursor.execute('SELECT to_jsonb(t) FROM gis.'+quoted+' t ORDER BY to_jsonb(t)::text')
        digest, count = hashlib.sha256(), 0
        while True:
            rows = cursor.fetchmany(500)
            if not rows:
                break
            for (value,) in rows:
                digest.update(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode())
                digest.update(b'\n')
                count += 1
        result[table] = {'count': count, 'sha256': digest.hexdigest()}
    return result


def baseline(cursor, central):
    table = (CENTRAL if central else TENANT)[3]
    state = check_state(cursor, central)
    if not state['eligible']:
        return {'state': state}
    rows = []
    if state['table']:
        cursor.execute('SELECT to_jsonb(t) FROM gis.'+table+' t ORDER BY to_jsonb(t)::text')
        rows = [row[0] for row in cursor.fetchall()]
    return {'state': state, 'relations': rows, 'preserved': fingerprint(cursor, exclude=(table,))}


def apply_store(cursor, central, before):
    app, name, _prior, table = CENTRAL if central else TENANT
    cursor.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='180s'")
    cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [LOCK])
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='gis' ORDER BY tablename")
    names = ['gis."'+row[0].replace('"','""')+'"' for row in cursor.fetchall()]
    if names:
        cursor.execute('LOCK TABLE '+','.join(names)+' IN SHARE ROW EXCLUSIVE MODE')
    current = baseline(cursor, central)
    if current != before:
        raise CommandError('reference_groups_baseline_changed=retry_readonly_preflight')
    if not current['state']['table']:
        cursor.execute(migration(central).SQL)
    if not current['state']['applied']:
        cursor.execute('INSERT INTO django_migrations(app,name,applied) VALUES (%s,%s,now())', [app, name])
    after = baseline(cursor, central)
    if after['preserved'] != before['preserved'] or after['relations'] != before['relations']:
        raise CommandError('reference_groups_preservation=mismatch')
    if not after['state']['applied'] or not after['state']['table']:
        raise CommandError('reference_groups_migration=incomplete')
    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def save_report(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        # Keep the first pre-migration baseline across partial retries.
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, default=str)


class Command(BaseCommand):
    help = 'Preflight/apply only the central code-group and tenant L2-group relations'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--check', action='store_true')
        mode.add_argument('--apply', action='store_true')
        mode.add_argument('--verify', action='store_true')
        parser.add_argument('--backup-dir', type=Path)

    def handle(self, *args, **options):
        from control.models import GroupDBConfig
        from control.services.gis_admin import tenant_cursor
        configs = list(GroupDBConfig.objects.using('default').filter(group__status='active')
                       .exclude(db_alias='default').order_by('group_id'))
        if not configs:
            raise CommandError('reference_groups_tenants=missing')
        try:
            if options['verify']:
                self.verify(configs)
                return
            with connections['default'].cursor() as cursor:
                central_state = check_state(cursor, True)
            states = []
            for config in configs:
                with tenant_cursor(config.group_id, write=False) as cursor:
                    states.append(check_state(cursor, False))
            pending = any(s['eligible'] and not (s['table'] and s['applied']) for s in [central_state, *states])
            if options['check']:
                self.stdout.write('reference_groups_pending='+('yes' if pending else 'no'))
                return
            if not options['backup_dir']:
                raise CommandError('--backup-dir required with --apply')
            directory = options['backup_dir'] / 'reference-groups'
            # Complete all read-only baselines/backups before the first DDL.
            with connections['default'].cursor() as cursor:
                central_before = baseline(cursor, True)
            save_report(directory/'central-before.json', central_before)
            tenant_before = []
            for number, config in enumerate(configs):
                with tenant_cursor(config.group_id, write=False) as cursor:
                    value = baseline(cursor, False)
                tenant_before.append(value)
                token = hashlib.sha256(str(config.group_id).encode()).hexdigest()[:16]
                save_report(directory/f'tenant-{token}-before.json',
                            {'target': {'group_id': str(config.group_id), 'alias': str(config.db_alias)}, **value})
            with transaction.atomic(using='default'), connections['default'].cursor() as cursor:
                apply_store(cursor, True, central_before)
            for number, (config, before) in enumerate(zip(configs, tenant_before)):
                if not before['state']['eligible']:
                    self.stdout.write(f'reference_groups_tenant_{number}=gis_not_installed')
                    continue
                with tenant_cursor(config.group_id, write=True) as cursor:
                    apply_store(cursor, False, before)
                self.stdout.write(f'reference_groups_tenant_{number}=ready_preserved')
            self.stdout.write('reference_groups_existing_gis_fingerprints=unchanged')
            self.stdout.write('RESULT reference_groups_migration=SUCCESS')
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError('Reference group rollout stopped ('+type(exc).__name__+').') from None

    def verify(self, configs):
        from control.management.commands.smoke_gis_survey_source_upload import _tenant_alias
        from geoflow_ops.gis.central_definitions import central_snapshot
        from geoflow_ops.gis.layer_plan import project_layer_plan
        from geoflow_ops.gis.reference_catalog import project_reference_catalog
        data = central_snapshot()
        if not data or not data.get('reference_groups_ready'):
            raise CommandError('reference_groups_central_runtime=not_ready')
        checked = fields = 0
        for config in configs:
            with _tenant_alias(config) as alias:
                with connections[alias].cursor() as cursor:
                    state = check_state(cursor, False)
                    if not state['eligible']:
                        continue
                    if not state['applied'] or not state['table']:
                        raise CommandError('reference_groups_tenant_runtime=not_ready')
                    cursor.execute('SELECT DISTINCT project_id::text FROM prj.scope_item WHERE project_id IS NOT NULL ORDER BY project_id::text')
                    projects = [row[0] for row in cursor.fetchall()]
                for project_id in projects:
                    plan = project_layer_plan(alias, project_id)
                    if not plan.get('gis_enabled'):
                        continue
                    catalog = project_reference_catalog(using=alias, plan=plan)
                    by_key = {row['code_group_key']: row['values'] for row in catalog['groups']}
                    actual = {(row['layer_id'], row['field_id']): by_key[row['code_group_key']] for row in catalog['bindings']}
                    for field in plan['form_definition']['fields']:
                        if not field.get('reference_constrained'):
                            continue
                        final = {row['id'] for row in field['reference_codes'] if row['enabled']}
                        reference = {row['id'] for row in actual.get((field['layer_id'],field['id']), []) if row['enabled']}
                        if final != reference:
                            raise CommandError('reference_groups_final_reference=mismatch')
                        fields += 1
                    checked += 1
        if not checked:
            raise CommandError('reference_groups_projects=missing')
        self.stdout.write(f'reference_groups_verified_projects={checked}')
        self.stdout.write(f'reference_groups_verified_fields={fields}')
        self.stdout.write('reference_groups_final_reference=identical')
        self.stdout.write('reference_groups_code_assignment=preserved_no_backfill')
        self.stdout.write('RESULT reference_groups_runtime=SUCCESS')
