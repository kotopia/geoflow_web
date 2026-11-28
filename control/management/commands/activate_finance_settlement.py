"""Back up finance tenants, apply only 0059 and verify its read paths."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor

from control.management.commands.activate_saved_filters import backup_central
from control.models import GroupDBConfig
from control.services.tenant_db_secret_resolver import resolve_tenant_db_password
from control.tenant_migration_context import allow_tenant_provisioning_migrations
from geoflow_ops.finance_pages_v4 import balance_totals

TARGET = ("webgisapp", "0059_finance_settlement")
FINANCE_BASE = ("webgisapp", "0034_finance_account_card_trash")


def registered_tenants():
    central = settings.CENTRAL_DB_ALIAS
    central_db = connections[central].settings_dict
    targets = []
    aliases = {central, "default"}
    for cfg in GroupDBConfig.objects.using(central).filter(group__status="active").order_by("group_id"):
        alias = str(cfg.db_alias or "").strip()
        if alias == central:
            continue
        if not alias or alias in aliases or cfg.db_name == central_db["NAME"]:
            raise CommandError("Ambiguous finance tenant identity")
        aliases.add(alias)
        db = dict(central_db, ENGINE="django.contrib.gis.db.backends.postgis", NAME=cfg.db_name,
                  HOST=cfg.db_host, PORT=cfg.db_port, USER=cfg.db_user,
                  PASSWORD=resolve_tenant_db_password(cfg.db_password), CONN_MAX_AGE=0,
                  OPTIONS=dict(central_db.get("OPTIONS", {}), sslmode="require"))
        if alias in connections.settings:
            connections[alias].close()
            del connections[alias]
        connections.settings[alias] = db
        conn = connections[alias]
        with conn.cursor() as cur:
            cur.execute("""SELECT current_database(),to_regclass('ctr.contracts'),to_regclass('prj.projects'),
                           to_regclass('hr.employee_profile'),to_regclass('ops.settings_nodes')""")
            db_name, *markers = cur.fetchone()
            if db_name != cfg.db_name or (any(markers) and not all(markers)):
                raise CommandError("Incomplete tenant schema or database identity mismatch")
            if all(markers):
                targets.append(conn)
    if not targets:
        raise CommandError("No finance tenant databases identified")
    return targets


def forward_plan(executor):
    applied = executor.recorder.applied_migrations()
    if FINANCE_BASE not in applied:
        raise CommandError("Tenant is missing the finance base migration")
    if TARGET in applied:
        return []
    plan = executor.migration_plan([TARGET])
    if [(m.app_label, m.name, backwards) for m, backwards in plan] != [(*TARGET, False)]:
        raise CommandError("Finance activation requires a separate migration")
    return plan


def verify(connection):
    if TARGET not in MigrationExecutor(connection).recorder.applied_migrations():
        raise CommandError("Finance migration was not recorded")
    with connection.cursor() as cur:
        for query in (
            "SELECT installment FROM fin.claims LIMIT 0",
            "SELECT holder,attachment_id FROM fin.accounts LIMIT 0",
            "SELECT custodian,settlement_account_id,attachment_id FROM fin.cards LIMIT 0",
            "SELECT bill_attachment_id,statement_attachment_id FROM fin.payment_requests LIMIT 0",
            "SELECT contents,issued_at,submitted_at FROM fin.claim_documents LIMIT 0",
            "SELECT invoice_id,claim_id FROM fin.issued_invoice_links LIMIT 0",
        ):
            cur.execute(query)
    balance_totals(connection.alias)


class Command(BaseCommand):
    help = "Check active tenant finance schemas. Apply 0059 with per-tenant backups."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--backup-dir")

    def handle(self, *args, **options):
        tenants = registered_tenants()
        pending = []
        for connection in tenants:
            if forward_plan(MigrationExecutor(connection)):
                pending.append(connection)
            else:
                verify(connection)
        self.stdout.write(f"finance_0059_tenants={len(tenants)} pending={len(pending)}")
        if not options["apply"]:
            return
        if pending and not options["backup_dir"]:
            raise CommandError("Private backup directory required")
        for index, connection in enumerate(pending):
            directory = Path(options["backup_dir"]) / f"tenant-{index+1}"
            backup = backup_central(connection, directory)
            backup.rename(directory / "before-finance-settlement.dump")
        for connection in pending:
            alias = connection.alias
            with transaction.atomic(using=alias), allow_tenant_provisioning_migrations(alias), connection.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='10s'")
                cur.execute("SET LOCAL statement_timeout='120s'")
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('finance-settlement-0059'))")
                executor = MigrationExecutor(connection)
                plan = forward_plan(executor)
                if plan:
                    executor.migrate([TARGET], plan=plan)
                verify(connection)
        self.stdout.write(f"finance_0059_verified={len(tenants)}")
