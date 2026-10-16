"""Inventory, back up, migrate and backfill the approved Survey final fields."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from control.management.commands.smoke_gis_survey_source_upload import _tenant_alias
from geoflow_ops.gis.survey_backfill import backfill_survey_project

MIGRATION = '0046_gis_survey_final_fields'


def migration_sql():
    path = Path(__file__).resolve().parents[3] / 'geoflow_ops' / 'migrations' / (MIGRATION+'.py')
    spec = importlib.util.spec_from_file_location(MIGRATION, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Migration.operations[0].sql


class Command(BaseCommand):
    help = 'Apply Survey final-field constraints and provenance-preserving backfill'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup-dir', required=True)

    def handle(self, *args, **options):
        if not options['apply']:
            raise CommandError('Explicit --apply required')
        backup = Path(options['backup_dir']) / 'survey-final-fields'
        backup.mkdir(mode=0o700, parents=True, exist_ok=True)
        with connections['default'].cursor() as c:
            c.execute("""SELECT to_jsonb(f) FROM gis.definition_field f
                          JOIN gis.definition_layer l ON l.id=f.source_layer_id
                         WHERE l.physical_name='survey'
                           AND f.physical_name IN ('survey_no','type','x','y','z')""")
            central_rows = [json.loads(r[0]) if isinstance(r[0],str) else r[0] for r in c.fetchall()]
        central_backup = backup / 'central-definition-fields.json'
        central_backup.touch(mode=0o600, exist_ok=True)
        central_backup.chmod(0o600)
        central_backup.write_text(json.dumps(central_rows, default=str), encoding='utf-8')
        configs = list(GroupDBConfig.objects.using('default').filter(group__status='active')
                       .exclude(db_alias='default').order_by('group_id'))
        if not configs:
            raise CommandError('No active tenants')
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
                report = {'schema': schema, 'rows': rows}
                output = backup / f'tenant-{ordinal}.json'
                output.touch(mode=0o600, exist_ok=True)
                output.chmod(0o600)
                output.write_text(json.dumps(report, default=str), encoding='utf-8')
                self.stdout.write(f'survey_final_inventory_tenant={ordinal}:rows={len(rows)}')
        for ordinal, config in enumerate(configs):
            with _tenant_alias(config) as alias:
                with transaction.atomic(using=alias):
                    with connections[alias].cursor() as c:
                        c.execute("SET LOCAL lock_timeout='8s'")
                        c.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow:survey-final-fields-0046'))")
                        c.execute("SELECT EXISTS(SELECT 1 FROM django_migrations WHERE app='webgisapp' AND name=%s)", [MIGRATION])
                        if not c.fetchone()[0]:
                            c.execute(migration_sql())
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
