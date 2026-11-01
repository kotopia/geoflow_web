"""Apply only the approved 0050 to the already-enabled company tenant."""
import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.migrations.executor import MigrationExecutor
from control.management.commands.activate_company_overview import (
    tenant_connection, verify_schema, activation_stage,
)
from control.management.commands.activate_saved_filters import backup_central
from control.tenant_migration_context import allow_tenant_provisioning_migrations
from geoflow_ops.services.company_overview import enabled

TARGET = ('webgisapp', '0050_company_workspace_details')
DEPENDENCY = ('webgisapp', '0049_company_overview')
REVIEWED_BLOB = '6b5d6e407f28c4b55cd7451edd74a89980f26d09'


def forward_plan(executor):
    applied = executor.recorder.applied_migrations()
    if DEPENDENCY not in applied:
        raise CommandError('company_workspace_requires_0049')
    if TARGET in applied:
        return []
    plan = executor.migration_plan([TARGET])
    if [(m.app_label, m.name, backwards) for m, backwards in plan] != [(*TARGET, False)]:
        raise CommandError('company_workspace_unexpected_plan')
    return plan


def verify(connection):
    verify_schema(connection)
    if TARGET not in MigrationExecutor(connection).recorder.applied_migrations():
        raise CommandError('company_workspace_migration_not_recorded')
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE schemaname='ops' AND tablename='company_credit' AND indexname='company_credit_successor'")
        if not cur.fetchone():
            raise CommandError('company_workspace_successor_index_missing')


class Command(BaseCommand):
    help = 'Read-only 0050 preflight; --apply requires the approved private backup.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--verify', action='store_true')
        parser.add_argument('--backup-dir')

    def handle(self, *args, **options):
        source = (Path(__file__).resolve().parents[3] / 'geoflow_ops/migrations/0050_company_workspace_details.py').read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
        if blob != REVIEWED_BLOB:
            raise CommandError('company_workspace_unreviewed_migration')
        with activation_stage('workspace_0050'):
            connection = tenant_connection()
            if connection.vendor != 'postgresql' or not enabled(connection.alias):
                raise CommandError('company_workspace_requires_enabled_postgres_tenant')
            executor = MigrationExecutor(connection)
            executor.loader.check_consistent_history(connection)
            plan = forward_plan(executor)
            self.stdout.write(f'company_workspace_eligible_tenants=1 pending={len(plan)}')
            if options['verify']:
                verify(connection)
                self.stdout.write('company_workspace_schema_verified=yes')
                return
            if not options['apply']:
                return
            if plan:
                if not options.get('backup_dir'):
                    raise CommandError('company_workspace_private_backup_required')
                backup = backup_central(connection, options['backup_dir'])
                backup.rename(backup.with_name('tenant-before-company-workspace.dump'))
                self.stdout.write('company_workspace_private_backup_verified=yes')
            alias = connection.alias
            with allow_tenant_provisioning_migrations(alias), transaction.atomic(using=alias), connection.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='10s'")
                cur.execute("SET LOCAL statement_timeout='120s'")
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['geoflow-company-0050'])
                executor = MigrationExecutor(connection)
                executor.loader.check_consistent_history(connection)
                plan = forward_plan(executor)
                executor.migrate([TARGET], plan=plan)
                verify(connection)
            self.stdout.write('company_workspace_schema_activated=yes')
