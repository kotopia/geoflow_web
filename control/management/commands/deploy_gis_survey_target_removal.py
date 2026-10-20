"""Retire the reviewed SQL-only relation, with exact preservation and private recovery."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

MIGRATION = '0047_remove_survey_targets'
TABLE = 'survey_link'


def migration():
    return importlib.import_module('geoflow_ops.migrations.' + MIGRATION)


def pending(cursor):
    cursor.execute("SELECT to_regclass('gis.survey_link') IS NOT NULL, EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name=%s)", [MIGRATION])
    exists, applied = cursor.fetchone()
    return exists or not applied


def preserved_inventory(cursor):
    """Hash every unrelated GIS row, including geometry, in stable primary-key order."""
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='gis' ORDER BY tablename")
    tables = [r[0] for r in cursor.fetchall() if r[0] != TABLE]
    result = {}
    for table in tables:
        if table == 'feature_change_log':
            query = """SELECT (to_jsonb(t)-'old_values'-'new_values') || jsonb_build_object(
                'old_values',CASE WHEN old_values ? 'survey_mapping_id' OR new_values ? 'survey_mapping_id' THEN old_values-'survey_mapping_id'-'survey_id' ELSE old_values END,
                'new_values',CASE WHEN old_values ? 'survey_mapping_id' OR new_values ? 'survey_mapping_id' THEN new_values-'survey_mapping_id'-'survey_id' ELSE new_values END) FROM gis.feature_change_log t
                WHERE physical_name<>%s ORDER BY project_id,revision"""
            cursor.execute(query, [TABLE])
        elif table == 'changeset_receipt':
            cursor.execute("SELECT to_jsonb(t) FROM gis.changeset_receipt t WHERE COALESCE(response_payload->>'protocol','')<>%s ORDER BY project_id,client_id,changeset_id", ['survey_link_changeset_v1'])
        else:
            cursor.execute('SELECT to_jsonb(t) FROM gis.' + '"'+table.replace('"','""')+'" t ORDER BY to_jsonb(t)::text')
        digest, count = hashlib.sha256(), 0
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                value = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                digest.update(json.dumps(value, sort_keys=True, separators=(',',':'), default=str).encode())
                digest.update(b'\n')
                count += 1
        result[table] = {'count': count, 'sha256': digest.hexdigest()}
    return result


def lock_gis(cursor):
    cursor.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='180s'")
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='gis' ORDER BY tablename")
    names = ['gis."'+r[0].replace('"','""')+'"' for r in cursor.fetchall()]
    if names:
        cursor.execute('LOCK TABLE '+','.join(names)+' IN SHARE ROW EXCLUSIVE MODE')


def backup_rows(cursor):
    def rows(table, sql):
        # GIS foundation may be installed before the optional sync runtime.
        # Absence of an audit table means there are no such records to archive.
        cursor.execute('SELECT to_regclass(%s)', ['gis.' + table])
        if cursor.fetchone()[0] is None:
            return []
        cursor.execute(sql)
        return [json.loads(r[0]) if isinstance(r[0],str) else r[0] for r in cursor.fetchall()]
    target_rows = rows(TABLE, 'SELECT to_jsonb(t) FROM gis.survey_link t ORDER BY id')
    return {
        'targets': target_rows,
        'logs': rows('feature_change_log', "SELECT to_jsonb(t) FROM gis.feature_change_log t WHERE physical_name='survey_link' OR old_values ? 'survey_mapping_id' OR new_values ? 'survey_mapping_id' ORDER BY project_id,revision"),
        'receipts': rows('changeset_receipt', "SELECT to_jsonb(t) FROM gis.changeset_receipt t WHERE response_payload->>'protocol'='survey_link_changeset_v1' ORDER BY project_id,client_id,changeset_id"),
    }


def apply_removal(cursor):
    cursor.execute(migration().FORWARD_SQL)
    cursor.execute("INSERT INTO django_migrations(app,name,applied) SELECT 'webgisapp',%s,now() WHERE NOT EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name=%s)", [MIGRATION,MIGRATION])
    if pending(cursor):
        raise CommandError('Target retirement shape validation failed')
    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


def restore(cursor, report):
    if preserved_inventory(cursor) != report['preserved']:
        raise CommandError('Preserved GIS data changed since backup; recovery requires review')
    cursor.execute(migration().REVERSE_SQL)
    for key, table, pk in [('receipts','changeset_receipt','project_id,client_id,changeset_id'),
                           ('logs','feature_change_log','project_id,revision'),('targets',TABLE,'id')]:
        for row in report['rows'][key]:
            if table == 'feature_change_log' and row['physical_name'] != TABLE:
                cursor.execute("UPDATE gis.feature_change_log SET old_values=%s::jsonb,new_values=%s::jsonb WHERE project_id=%s AND revision=%s",[json.dumps(row['old_values']),json.dumps(row['new_values']),row['project_id'],row['revision']])
            else:
                cursor.execute(f'INSERT INTO gis.{table} SELECT * FROM jsonb_populate_record(NULL::gis.{table},%s::jsonb) ON CONFLICT ({pk}) DO NOTHING',[json.dumps(row)])
    cursor.execute("DELETE FROM django_migrations WHERE app='webgisapp' AND name=%s",[MIGRATION])
    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


class Command(BaseCommand):
    help = 'Back up, remove and verify retired target relations, or restore a private backup'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--restore', action='store_true')
        parser.add_argument('--backup-dir')

    def handle(self, *args, **options):
        try:
            self.execute_removal(options)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f'Target retirement stopped ({type(exc).__name__}); committed tenants remain recoverable.') from None

    def execute_removal(self, options):
        from control.models import GroupDBConfig
        from control.services.gis_admin import tenant_cursor
        configs = list(GroupDBConfig.objects.using('default').filter(group__status='active').exclude(db_alias='default').order_by('group_id'))
        if not configs:
            raise CommandError('No active tenants')
        if options['check']:
            state = False
            for config in configs:
                with tenant_cursor(config.group_id, write=False) as c:
                    state = pending(c) or state
            self.stdout.write('survey_target_removal_pending='+('yes' if state else 'no'))
            return
        if not options['apply'] or not options['backup_dir']:
            raise CommandError('Explicit --apply and --backup-dir required')
        directory = Path(options['backup_dir']) / 'survey-target-removal'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        # Check every tenant prerequisite before the first mutation.
        for config in configs:
            with tenant_cursor(config.group_id, write=False) as c:
                c.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name='0046_gis_survey_final_fields')")
                if not c.fetchone()[0]:
                    raise CommandError('Final-field prerequisite missing')
        for index, config in enumerate(configs):
            with tenant_cursor(config.group_id, write=True) as c:
                lock_gis(c)
                output = directory / (str(config.group_id)+'.json')
                if options['restore']:
                    if output.is_symlink() or output.stat().st_mode & 0o077:
                        raise CommandError('Recovery file must be private and not a symlink')
                    report = json.loads(output.read_text())
                    if report['group_id'] != str(config.group_id):
                        raise CommandError('Recovery tenant mismatch')
                    restore(c, report)
                    self.stdout.write(f'survey_target_restore_tenant={index}:complete=yes')
                    continue
                self.stdout.write(f'survey_target_removal_stage={index}:inventory_and_backup')
                before = preserved_inventory(c)
                rows = backup_rows(c)
                # A retry never overwrites the original recovery file.
                if not output.exists():
                    descriptor = os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(descriptor,'w') as stream:
                        json.dump({'group_id':str(config.group_id),'preserved':before,'rows':rows},stream,default=str)
                        stream.flush(); os.fsync(stream.fileno())
                elif output.is_symlink() or output.stat().st_mode & 0o077:
                    raise CommandError('Recovery backup must remain private')
                elif rows['targets']:
                    saved = json.loads(output.read_text())
                    if saved['rows'] != rows or saved['preserved'] != before:
                        raise CommandError('Recovery backup differs from current pre-drop state')
                self.stdout.write(f'survey_target_removal_stage={index}:migration')
                apply_removal(c)
                after = preserved_inventory(c)
                if before != after:
                    raise CommandError('Unrelated GIS data changed; tenant transaction rolled back')
                for table in ('survey','survey_source','wtl_pipe_ps','wtl_valv_ps'):
                    self.stdout.write(f'survey_target_preserved={index}:{table}:rows={after.get(table,{}).get("count",0)}:fingerprint=unchanged')
                self.stdout.write(f'survey_target_removed_tenant={index}:rows={len(rows["targets"])}:logs={sum(r["physical_name"]==TABLE for r in rows["logs"])}')
        self.stdout.write('survey_target_removal_complete=yes')
