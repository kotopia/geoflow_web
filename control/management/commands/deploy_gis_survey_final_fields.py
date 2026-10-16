"""Inventory, back up, migrate and backfill the approved Survey final fields."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from geoflow_ops.gis.survey_backfill import backfill_survey_project

MIGRATION = '0046_gis_survey_final_fields'


def migration_sql():
    path = Path(__file__).resolve().parents[3] / 'geoflow_ops' / 'migrations' / (MIGRATION+'.py')
    spec = importlib.util.spec_from_file_location(MIGRATION, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Migration.operations[0].sql


def final_fields_pending(cursor):
    cursor.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name=%s)", [MIGRATION])
    if not cursor.fetchone()[0]:
        return True
    cursor.execute("""SELECT count(*) FROM information_schema.columns
                       WHERE table_schema='gis' AND table_name='survey_source'
                         AND column_name IN ('survey_type','target_crs')""")
    if cursor.fetchone()[0] != 2:
        return True
    cursor.execute("""SELECT count(*) FROM pg_constraint
                       WHERE conrelid='gis.survey'::regclass
                         AND conname IN ('survey_project_no_uq','survey_type_ck')""")
    return cursor.fetchone()[0] != 2


class Command(BaseCommand):
    help = 'Apply Survey final-field constraints and provenance-preserving backfill'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup-dir')
        parser.add_argument('--check', action='store_true')

    def handle(self, *args, **options):
        try:
            self._execute(options)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f'Survey final-field deployment stopped ({type(exc).__name__}).') from None

    def _execute(self, options):
        from control.models import GroupDBConfig
        from control.services.gis_admin import tenant_cursor
        from control.management.commands.smoke_gis_survey_source_upload import _tenant_alias

        configs = list(GroupDBConfig.objects.using('default').filter(group__status='active')
                       .exclude(db_alias='default').order_by('group_id'))
        if not configs:
            raise CommandError('No active tenants')
        if options['check']:
            pending = False
            for config in configs:
                with tenant_cursor(config.group_id, write=False) as cursor:
                    pending = final_fields_pending(cursor) or pending
            self.stdout.write('survey_final_pending='+('yes' if pending else 'no'))
            return
        if not options['apply']:
            raise CommandError('Explicit --apply required')
        if not options['backup_dir']:
            raise CommandError('--backup-dir is required with --apply')
        backup = Path(options['backup_dir']) / 'survey-final-fields'
        backup.mkdir(mode=0o700, parents=True, exist_ok=True)
        with connections['default'].cursor() as c:
            c.execute("""SELECT to_jsonb(f) FROM gis.definition_field f
                          JOIN gis.definition_layer l ON l.id=f.source_layer_id
                         WHERE l.physical_name='survey'
                           AND f.physical_name IN ('survey_no','type','x','y','z')""")
            central_rows = [json.loads(r[0]) if isinstance(r[0],str) else r[0] for r in c.fetchall()]
        central_backup = backup / 'central-definition-fields.json'
        if not central_backup.exists():
            with central_backup.open('x', encoding='utf-8') as stream:
                central_backup.chmod(0o600)
                stream.write(json.dumps(central_rows, default=str))
        # Complete all read-only prerequisite checks/backups before first DDL.
        for ordinal, config in enumerate(configs):
            with tenant_cursor(config.group_id, write=False) as c:
                c.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name='0045_gis_survey_soft_delete')")
                if not c.fetchone()[0]:
                    raise CommandError('Survey soft-delete prerequisite missing')
                c.execute("SELECT count(*) FROM gis.survey WHERE type IS NOT NULL AND type NOT IN ('GNSS','TOTAL_STATION')")
                if c.fetchone()[0]:
                    raise CommandError('Unknown existing Survey method; no schema change applied')
                c.execute("SELECT count(*) FROM (SELECT project_id,survey_no FROM gis.survey WHERE survey_no IS NOT NULL GROUP BY project_id,survey_no HAVING count(*)>1) d")
                if c.fetchone()[0]:
                    raise CommandError('Duplicate existing Survey numbers; no schema change applied')
                c.execute("SELECT column_name,data_type,column_default,is_nullable FROM information_schema.columns WHERE table_schema='gis' AND table_name='survey' ORDER BY ordinal_position")
                schema = c.fetchall()
                c.execute("SELECT to_jsonb(s) - 'geom' - 'raw_geom' FROM gis.survey s ORDER BY id")
                rows = [json.loads(r[0]) if isinstance(r[0],str) else r[0] for r in c.fetchall()]
                report = {'tenant_alias':str(config.db_alias),'group_id':str(config.group_id),
                          'schema': schema, 'rows': rows}
                output = backup / f'tenant-{ordinal}.json'
                if not output.exists():
                    with output.open('x', encoding='utf-8') as stream:
                        output.chmod(0o600)
                        stream.write(json.dumps(report, default=str))
                self.stdout.write(f'survey_final_inventory_tenant={ordinal}:rows={len(rows)}')
        for ordinal, config in enumerate(configs):
            with _tenant_alias(config) as alias:
                with transaction.atomic(using=alias):
                    with connections[alias].cursor() as c:
                        c.execute("SET LOCAL lock_timeout='8s'")
                        c.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:survey-final-fields-0046'))")
                        c.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name=%s)", [MIGRATION])
                        applied = bool(c.fetchone()[0])
                        if not applied or final_fields_pending(c):
                            c.execute(migration_sql())
                        if not applied:
                            c.execute("INSERT INTO django_migrations(app,name,applied) VALUES ('webgisapp',%s,now())", [MIGRATION])
                        c.execute('SELECT DISTINCT project_id::text FROM gis.survey ORDER BY project_id::text')
                        projects = [r[0] for r in c.fetchall()]
                    for project_id in projects:
                        counts = backfill_survey_project(alias, project_id)
                        self.stdout.write('survey_final_backfill='+json.dumps({'tenant':ordinal,**counts},sort_keys=True))
                    with connections[alias].cursor() as c:
                        c.execute('SET CONSTRAINTS ALL IMMEDIATE')
            self.stdout.write(f'survey_final_tenant_ready={ordinal}')
        # Physical fields already exist in the live central definition. Reconcile
        # only this Survey contract; keep labels/layout and unrelated layers.
        with transaction.atomic(using='default'):
            with connections['default'].cursor() as c:
                c.execute("""UPDATE gis.definition_field f SET readonly=true,updated_at=now()
                              FROM gis.definition_layer l WHERE l.id=f.source_layer_id
                               AND l.physical_name='survey'
                               AND f.physical_name IN ('survey_no','type','x','y','z')
                               AND NOT f.readonly""")
        self.stdout.write('survey_final_deploy_complete=yes')
