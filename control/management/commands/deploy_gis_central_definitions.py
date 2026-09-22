"""Authorized central GIS SSOT migration; invoked by the protected workflow."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from control.services import gis_definition_transition as transition
from control.services import gis_schema_manager


class Command(BaseCommand):
    help='Reconcile central GIS definitions from physical PostGIS schema and remove tenant copies.'

    def add_arguments(self,parser):
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--backup-dir',required=True)

    def handle(self,*args,**options):
        if not options['apply']: raise CommandError('Explicit --apply required')
        configs=list(GroupDBConfig.objects.using('default').filter(group__status='active').order_by('group_id'))
        directory=Path(options['backup_dir']).resolve(); directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(directory,0o700)
        try:
            snapshots=[]; states=[]
            for config in configs:
                if config.db_alias=='default': continue
                with tenant_cursor(config.group_id,write=True) as cursor:
                    cursor.execute("SET LOCAL statement_timeout='180s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.gis.definition.transition'))")
                    cursor.execute("SELECT to_regclass('gis.meta_feature_type') IS NOT NULL")
                    has_legacy=bool(cursor.fetchone()[0])
                    if has_legacy:
                        cursor.execute('LOCK TABLE gis.meta_feature_type,gis.meta_field_def,gis.ref_code_group,gis.ref_code_value,gis.scope_binding,gis.capability_feature,gis.profile_field IN SHARE MODE')
                        snapshots.append(transition.source_snapshot(cursor))
                    states.append(transition.inspect_tenant(cursor))
            source=transition.merge_source_snapshots(snapshots)
            backup=directory/'pre-central-ssot.json'
            if not backup.exists():
                fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as output:
                    json.dump({'tenant_definition_counts':states,'physical_source':source or 'already-central-v3'},output,
                              ensure_ascii=False,default=str)

            ddl=(Path(__file__).resolve().parents[3]/'docs/architecture/gis-central-definitions.sql').read_text()
            with transaction.atomic(using='default'),connections['default'].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='5s'"); cursor.execute("SET LOCAL statement_timeout='180s'")
                if source is not None:
                    corrected=transition.type_correction_count(cursor,source)
                    created=transition.bootstrap(cursor,source,ddl)
                else:
                    cursor.execute("SELECT obj_description('gis.definition_group'::regclass)")
                    if cursor.fetchone()[0] != transition.V3_COMMENT:
                        raise RuntimeError('central v3 definition is required after tenant retirement')
                    created=False
                    corrected=0
                gis_schema_manager.ensure_admin_schema(cursor)
                cursor.execute('SELECT standard_name,id::text FROM gis.definition_layer')
                layer_ids=dict(cursor.fetchall())
                cursor.execute('SELECT count(*) FROM gis.definition_layer'); layer_count=cursor.fetchone()[0]
                cursor.execute('SELECT count(*) FROM gis.definition_field'); field_count=cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM gis.definition_field WHERE widget_type<>''"); widget_count=cursor.fetchone()[0]
                cursor.execute('SELECT count(*) FROM gis.definition_code'); code_count=cursor.fetchone()[0]

            migrated=0
            for config in configs:
                if config.db_alias=='default': continue
                with tenant_cursor(config.group_id,write=True) as cursor:
                    cursor.execute("SET LOCAL statement_timeout='180s'")
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.gis.definition.transition'))")
                    cursor.execute("SELECT to_regclass('gis.meta_feature_type') IS NOT NULL")
                    if not cursor.fetchone()[0]: continue
                    transition.migrate_project_config(cursor,layer_ids)
                    transition.migrate_runtime_fks(cursor,layer_ids)
                    transition.retire_legacy(cursor)
                    migrated+=1

            self.stdout.write('gis_central_definitions_version=3')
            self.stdout.write('gis_central_bootstrapped='+str(created).lower())
            self.stdout.write('gis_central_layer_count='+str(layer_count))
            self.stdout.write('gis_central_field_count='+str(field_count))
            self.stdout.write('gis_physical_type_corrections='+str(corrected))
            self.stdout.write('gis_widget_metadata_count='+str(widget_count))
            self.stdout.write('gis_reference_code_count='+str(code_count))
            self.stdout.write('gis_tenant_definition_stores_retired='+str(migrated))
            self.stdout.write('gis_non_gis_operational_tables_changed=0')
        except Exception as exc:
            raise CommandError('GIS central SSOT migration stopped ('+type(exc).__name__+'); uncommitted transaction rolled back.') from None
