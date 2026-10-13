"""Central menu persistence and conservative erasure backfill in disposable CI."""
import os
import sys
from importlib import import_module
from pathlib import Path
from uuid import uuid4

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CENTRAL_DB_HOST") not in {"localhost", "127.0.0.1"}:
    raise RuntimeError("Only disposable local GitHub CI databases are allowed")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["DJANGO_SETTINGS_MODULE"] = "geoflow_project.ci_migration_settings"

import django
django.setup()

from django.db import connection, transaction
from control.services import service_menu_visibility as menus
from control.services.central_account_erasure_service import SqlCentralAccountErasureRepository

if connection.settings_dict["HOST"] not in {"localhost", "127.0.0.1"}:
    raise RuntimeError("Resolved database must be local CI")

with transaction.atomic():
    group_a, group_b, erased, pending, active, newly_erased = [uuid4() for _ in range(6)]
    with connection.cursor() as cur:
        for group in (group_a, group_b):
            cur.execute("INSERT INTO groups (id, code, name, status) VALUES (%s,%s,'CI','active')", [group, str(group)])
        for user, email, password, enabled in (
            (erased, f"erased-{uuid4()}@example.invalid", "!disabled", False),
            (pending, f"pending-{uuid4()}@example.invalid", "usable", False),
            (active, f"erased-{uuid4()}@example.invalid", "usable", True),
            (newly_erased, f"normal-{uuid4()}@example.invalid", "usable", True),
        ):
            cur.execute("INSERT INTO users (id,email,password_hash,is_active) VALUES (%s,%s,%s,%s)", [user,email,password,enabled])
        backfill = import_module("control.migrations.0007_admin_visibility").BACKFILL_SQL
        cur.execute(backfill)
        cur.execute("SELECT id FROM users WHERE deleted_at IS NOT NULL AND id=ANY(%s::uuid[])", [[str(erased),str(pending),str(active)]])
        assert cur.fetchall() == [(erased,)]
        SqlCentralAccountErasureRepository()._anonymize(cur, user_id=str(newly_erased), unusable_password_hash="!disabled")
        cur.execute("SELECT deleted_at IS NOT NULL, is_active FROM users WHERE id=%s", [newly_erased])
        assert cur.fetchone() == (True, False)
    assert all(menus.get_service_menus(group_a).values())
    menus.save_service_menus(group_a, dict(bids=False, gis=True, finance=False))
    assert menus.get_service_menus(group_a) == dict(bids=False, gis=True, finance=False)
    assert all(menus.get_service_menus(group_b).values())
    menus.save_service_menus(group_a, dict(bids=True, gis=False, finance=True))
    assert menus.get_service_menus(group_a) == dict(bids=True, gis=False, finance=True)
    transaction.set_rollback(True)
print("central_admin_visibility_rehearsal=yes")
