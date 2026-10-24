"""Guarded rollout of the approved central personal-filter table only."""
import hashlib
import os
import re
import shutil
from pathlib import Path
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor

TARGET = ('control', '0008_saved_filters')
REVIEWED_BLOB = '2c1797391c67aa4708bf52abaf17cf41d0f566cd'


def forward_plan(executor, target):
    # Targeting an already-applied ancestor must never unapply its descendants.
    if target in executor.recorder.applied_migrations():
        return []
    plan = executor.migration_plan([target])
    if any((m.app_label, m.name) != target or backwards for m, backwards in plan):
        raise CommandError('unexpected_saved_filter_migration_plan')
    return plan


def backup_error_code(error):
    if isinstance(error, FileNotFoundError):
        return 'executable_missing'
    if isinstance(error, PermissionError):
        return 'filesystem_permission_denied'
    if isinstance(error, subprocess.TimeoutExpired):
        return 'timeout'
    stderr = getattr(error, 'stderr', b'') or b''
    if isinstance(stderr, bytes):
        stderr = stderr.decode('utf-8', errors='replace')
    text = stderr.lower()
    for marker, code in (
        ('server version mismatch', 'server_version_mismatch'),
        ('password authentication failed', 'authentication_failed'),
        ('no password supplied', 'password_missing'),
        ('permission denied', 'database_or_file_permission_denied'),
        ('no pg_hba.conf entry', 'connection_policy_denied'),
        ('could not translate host name', 'host_resolution_failed'),
        ('connection refused', 'connection_refused'),
        ('no space left', 'backup_disk_full'),
        ('unsupported version', 'archive_version_mismatch'),
    ):
        if marker in text:
            return code
    return 'tool_failed'


def backup_tools(connection, private_root=None):
    # Ubuntu may have multiple client versions and pg_wrapper may select the
    # oldest default. Resolve a compatible installed pair without changing the OS.
    connection.ensure_connection()
    server_major = connection.pg_version // 10000
    candidates = []
    default = shutil.which('pg_dump')
    private_root = private_root or os.environ.get('GEOFLOW_PG_CLIENT_ROOT')
    private_paths = [Path(private_root) / 'bin/pg_dump'] if private_root else []
    paths = private_paths + ([Path(default)] if default else []) + list(Path('/usr/lib/postgresql').glob('*/bin/pg_dump'))
    for path in paths:
        restore = path.with_name('pg_restore')
        if not restore.is_file():
            continue
        try:
            output = subprocess.run([str(path), '--version'], check=True, capture_output=True, timeout=10).stdout.decode()
            match = re.search(r'PostgreSQL\) (\d+)', output)
            if match and int(match[1]) >= server_major:
                candidates.append((int(match[1]), str(path), str(restore)))
        except (OSError, subprocess.SubprocessError):
            continue
    if not candidates:
        raise CommandError(f'central_backup_compatible_client_missing_server_major_{server_major}')
    _, dump, restore = min(candidates)
    return dump, restore


def backup_central(connection, directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise CommandError('private_backup_directory_required')
    # Never overwrite a previous backup on retry. Credentials stay in subprocess
    # environment, and pg_dump stderr is intentionally not printed in CI logs.
    backup = directory / 'central-before-saved-filters.dump'
    if backup.exists():
        raise CommandError('backup_already_exists_use_new_run_directory')
    try:
        dump, restore = backup_tools(connection)
    except CommandError as error:
        if 'compatible_client_missing_server_major_16' not in str(error):
            raise
        # Official signed packages, extracted under this private backup directory.
        # No package installation, system service or global library changes.
        script = Path(__file__).resolve().parents[3] / 'scripts/ops/prepare_private_pg_client.sh'
        private_root = directory / 'client'
        try:
            subprocess.run(['bash', str(script), str(private_root)], check=True, timeout=300)
        except (OSError, subprocess.SubprocessError):
            raise CommandError('private_pg_client_preparation_failed_no_schema_applied') from None
        dump, restore = backup_tools(connection, private_root)
    cfg = connection.settings_dict
    env = os.environ.copy()
    env['PGPASSWORD'] = str(cfg.get('PASSWORD') or '')
    args = [dump, '--format=custom', '--no-password', '--file', str(backup),
            '--host', str(cfg.get('HOST') or 'localhost'), '--port', str(cfg.get('PORT') or 5432),
            '--username', str(cfg['USER']), '--dbname', str(cfg['NAME'])]
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        subprocess.run(args, env=env, check=True, capture_output=True, timeout=300)
        if backup.stat().st_size == 0:
            raise CommandError('empty_central_backup')
        subprocess.run([restore, '--list', str(backup)], check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        # Log only a fixed category, never raw pg_dump output or connection values.
        raise CommandError('central_backup_failed_no_schema_applied:' + backup_error_code(error)) from None
    return backup


class Command(BaseCommand):
    help = 'Inspect central saved-filter rollout; --apply requires operational authorization.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup-dir')

    def handle(self, *args, **options):
        alias = getattr(settings, 'CENTRAL_DB_ALIAS', 'default')
        connection = connections[alias]
        if connection.vendor != 'postgresql':
            raise CommandError('central_postgresql_required')
        source = (Path(__file__).resolve().parents[2] / 'migrations/0008_saved_filters.py').read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
        if blob != REVIEWED_BLOB:
            raise CommandError('unreviewed_saved_filter_migration')
        executor = MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        plan = forward_plan(executor, TARGET)
        self.stdout.write(f'central_saved_filters_pending={len(plan)}')
        if not options['apply']:
            return
        if plan:
            if not options.get('backup_dir'):
                raise CommandError('backup_directory_required')
            backup_central(connection, options['backup_dir'])
            self.stdout.write('central_saved_filters_backup_verified=yes')
        with transaction.atomic(using=alias), connection.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='10s'")
            cur.execute("SET LOCAL statement_timeout='120s'")
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['geoflow-saved-filters-0008'])
            executor = MigrationExecutor(connection)
            executor.loader.check_consistent_history(connection)
            plan = forward_plan(executor, TARGET)
            executor.migrate([TARGET], plan=plan)
            cur.execute('SELECT id,user_id,group_id,module,name,filter_json,created_at,updated_at FROM public.saved_filters LIMIT 0')
            constraints = connection.introspection.get_constraints(cur, 'saved_filters')
            if not any(v.get('unique') and v['columns'] == ['user_id','group_id','module','name'] for v in constraints.values()):
                raise CommandError('saved_filter_unique_scope_missing')
            if TARGET not in executor.recorder.applied_migrations():
                raise CommandError('saved_filter_migration_not_recorded')
        self.stdout.write('central_saved_filters_activated=yes')
