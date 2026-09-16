"""Authorized v2 schema transition; invoked only by protected production workflow."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from control.services import gis_definition_transition as transition


class Command(BaseCommand):
    help='Bootstrap central GIS definitions from cheonan_db and retire empty superseded form tables.'

    def add_arguments(self,parser):
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--backup-dir',required=True)

    def handle(self,*args,**options):
        if not options['apply']: raise CommandError('Explicit --apply required')
        config=GroupDBConfig.objects.using('default').filter(db_alias='cheonan_db',group__status='active').first()
        if config is None: raise CommandError('Exactly identified cheonan_db configuration required')
        directory=Path(options['backup_dir']).resolve()
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(directory,0o700)
        try:
            # Central is additive. If tenant commit fails after central commit, rerun keeps
            # central UUIDs/edits and retries only tenant retirement. Old code still runs.
            with tenant_cursor(config.group_id,write=True) as tc:
                tc.execute("SET LOCAL statement_timeout='120s'")
                tc.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.gis.definition.transition'))")
                tc.execute('LOCK TABLE gis.meta_feature_type,gis.meta_field_def,gis.ref_code_group,gis.ref_code_value,gis.scope_binding,gis.capability_feature IN SHARE MODE')
                legacy=transition.inspect_tenant(tc)
                source=transition.source_snapshot(tc)
                backup=directory/'pre-transition.json'
                if not backup.exists():
                    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'w') as out:
                        json.dump({'legacy_empty_tables':legacy,'source':source},out,ensure_ascii=False,default=str)
                with transaction.atomic(using='default'),connections['default'].cursor() as cc:
                    cc.execute("SET LOCAL lock_timeout='3s'")
                    cc.execute("SET LOCAL statement_timeout='120s'")
                    ddl=Path(__file__).resolve().parents[3]/'docs/architecture/gis-central-definitions.sql'
                    created=transition.bootstrap(cc,source,ddl.read_text())
                retired=transition.retire_empty_legacy(tc)
            self.stdout.write('gis_central_definitions_ready=yes')
            self.stdout.write('gis_central_bootstrapped='+str(created).lower())
            self.stdout.write('gis_empty_legacy_tables_retired='+str(sum(v is not None for v in retired.values())))
            self.stdout.write('gis_existing_asset_columns_deleted=0')
        except Exception as exc:
            # Avoid printing connection strings, production records or secret resolver errors.
            raise CommandError('GIS definition transition stopped ('+type(exc).__name__+'); transaction rolled back where uncommitted. Central bootstrap is repeatable.') from None
