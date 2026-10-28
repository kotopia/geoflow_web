"""Exact, additive company migration for a runtime with exactly one eligible tenant.

Read-only by default. Does not provision tenants, change grants, or discover
credentials outside the canonical GroupDBConfig -> Secrets Manager path.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor
from control.models import GroupDBConfig
from control.services.tenant_db_secret_resolver import resolve_tenant_db_password
from control.tenant_migration_context import allow_tenant_provisioning_migrations
from control.management.commands.activate_saved_filters import backup_central

TARGET = ('webgisapp', '0049_company_overview')
DEPENDENCY = ('webgisapp', '0048_gis_project_reference_groups')
REVIEWED_BLOB = '9caebb15259fecbeae22d130571f90a9080f8c0b'
TABLES = ('company_profile', 'company_registration', 'company_revenue', 'company_headcount', 'company_credit', 'company_evidence')


@contextmanager
def activation_stage(stage):
    """Expose only fixed stages/categories, never exception messages or DB identifiers."""
    try:
        yield
    except CommandError:
        raise
    except Exception as error:
        from django.db import DatabaseError
        from django.db.migrations.exceptions import InconsistentMigrationHistory
        from control.services.tenant_db_secret_resolver import TenantDBCredentialError
        category = 'unexpected'
        for kind, name in ((TenantDBCredentialError, 'credential_resolution'),
                           (InconsistentMigrationHistory, 'inconsistent_history'),
                           (DatabaseError, 'database'), (AttributeError, 'attribute'),
                           (KeyError, 'configuration_key')):
            if isinstance(error, kind):
                category = name
                break
        raise CommandError(f'company_activation_stage={stage} category={category}') from None


def forward_plan(executor):
    applied = executor.recorder.applied_migrations()
    if DEPENDENCY not in applied:
        raise CommandError('company_dependency_0048_not_applied')
    if TARGET in applied:
        return []
    plan = executor.migration_plan([TARGET])
    if len(plan) != 1 or any((m.app_label, m.name) != TARGET or backwards for m, backwards in plan):
        raise CommandError('company_unexpected_migration_plan')
    return plan


def tenant_connection():
    central = getattr(settings, 'CENTRAL_DB_ALIAS', 'default')
    with activation_stage('tenant_catalog'):
        configs = list(GroupDBConfig.objects.using(central).filter(group__status='active').exclude(db_alias=central))
    eligible = []
    for config in configs:
        alias = str(config.db_alias).strip()
        if not alias or alias == central:
            raise CommandError('company_central_alias_rejected')
        base = connections[central].settings_dict
        if (str(config.db_host), str(config.db_port), str(config.db_name)) == (str(base.get('HOST')), str(base.get('PORT')), str(base.get('NAME'))):
            raise CommandError('company_central_database_rejected')
        with activation_stage('tenant_credentials'):
            password = resolve_tenant_db_password(config.db_password)
        db = dict(base)
        db.update(ENGINE='django.contrib.gis.db.backends.postgis', NAME=config.db_name,
                  HOST=config.db_host, PORT=config.db_port, USER=config.db_user,
                  PASSWORD=password,
                  OPTIONS=dict(base.get('OPTIONS', {})), CONN_MAX_AGE=0,
                  CONN_HEALTH_CHECKS=False, ATOMIC_REQUESTS=False, AUTOCOMMIT=True)
        if alias in connections.settings:
            connections[alias].close()
            del connections[alias]
        connections.settings[alias] = db
        settings.DATABASES[alias] = db
        connection = connections[alias]
        with activation_stage('tenant_readiness'), connection.cursor() as cur:
            cur.execute("SELECT to_regclass('ops.my_org_units'), to_regclass('django_migrations')")
            company_table, history = cur.fetchone()
            if not company_table or not history:
                continue
            cur.execute('SELECT 1 FROM django_migrations WHERE app=%s AND name=%s', DEPENDENCY)
            if cur.fetchone():
                eligible.append(connection)
    return choose_eligible(eligible)


def choose_eligible(eligible):
    if len(eligible) != 1:
        raise CommandError(f'company_requires_one_eligible_tenant_found_{len(eligible)}')
    return eligible[0]



def verify_schema(connection):
    from geoflow_ops.company_models import CompanyProfile, CompanyRegistration, CompanyRevenue, CompanyHeadcount, CompanyCredit, CompanyEvidence
    with connection.cursor() as cur:
        for model in (CompanyProfile, CompanyRegistration, CompanyRevenue, CompanyHeadcount, CompanyCredit, CompanyEvidence):
            columns = ','.join(connection.ops.quote_name(field.column) for field in model._meta.local_fields)
            cur.execute(f'SELECT {columns} FROM {model._meta.db_table} LIMIT 0')
        cur.execute('SELECT org_unit_id,hire_date,term_date,status,is_deleted FROM hr.employee_profile LIMIT 0')
    if TARGET not in MigrationExecutor(connection).recorder.applied_migrations():
        raise CommandError('company_migration_not_recorded')


class Command(BaseCommand):
    help = 'Inspect company rollout; --apply is restricted to the exact approved additive migration.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup-dir')
        parser.add_argument('--verify', action='store_true')
        parser.add_argument('--activation-config')

    def handle(self, *args, **options):
        source = (Path(__file__).resolve().parents[3] / 'geoflow_ops/migrations/0049_company_overview.py').read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
        if blob != REVIEWED_BLOB:
            raise CommandError('company_unreviewed_migration')
        try:
            connection = tenant_connection()
            if connection.vendor != 'postgresql':
                raise CommandError('company_postgresql_required')
            with activation_stage('migration_loader'):
                executor = MigrationExecutor(connection)
            with activation_stage('migration_history'):
                executor.loader.check_consistent_history(connection)
            with activation_stage('migration_plan'):
                plan = forward_plan(executor)
            self.stdout.write(f'company_eligible_tenants=1 company_pending_migrations={len(plan)}')
            if options['verify']:
                verify_schema(connection)
                from geoflow_ops.services.company_overview import enabled
                self.stdout.write(f'company_schema_verified=yes company_feature_enabled={int(enabled(connection.alias))}')
                return
            if not options['apply']:
                return
            if plan:
                if not options.get('backup_dir'):
                    raise CommandError('company_private_backup_directory_required')
                # Reuse the reviewed private pg_dump/restore validation machinery.
                backup = backup_central(connection, options['backup_dir'])
                backup.rename(backup.with_name('tenant-before-company-overview.dump'))
                self.stdout.write('company_private_backup_verified=yes')
            alias = connection.alias
            with allow_tenant_provisioning_migrations(alias), transaction.atomic(using=alias), connection.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='10s'")
                cur.execute("SET LOCAL statement_timeout='120s'")
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['geoflow-company-0049'])
                executor = MigrationExecutor(connection)
                executor.loader.check_consistent_history(connection)
                plan = forward_plan(executor)
                executor.migrate([TARGET], plan=plan)
                verify_schema(connection)
            if options.get('activation_config'):
                config_path = Path(options['activation_config'])
                if config_path.parent.stat().st_mode & 0o077:
                    raise CommandError('company_private_config_directory_required')
                fd = os.open(config_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'tenant_alias':alias}, stream)
            self.stdout.write('company_schema_activated=yes')
        except CommandError:
            raise
        except Exception:
            # Connection/credential exceptions must never reveal private endpoints.
            raise CommandError('company_activation_failed_private_details_suppressed') from None
