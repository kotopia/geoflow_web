"""Central administrators manage one explicitly selected tenant per transaction."""
from contextlib import contextmanager

import psycopg2
from django.http import Http404

from control.models import GroupDBConfig
from control.services.tenant_db_secret_resolver import resolve_tenant_db_password


@contextmanager
def tenant_cursor(group_id, *, write=False):
    # The view must enforce require_central_admin before calling this boundary.
    config = (GroupDBConfig.objects.using("default").select_related("group")
              .filter(group_id=group_id, group__status="active").first())
    if config is None or config.db_alias == "default":
        raise Http404("사용 가능한 테넌트가 아닙니다.")
    reference = str(config.db_password or "").strip()
    password = resolve_tenant_db_password(reference)
    if not password:
        raise RuntimeError("Tenant credential unavailable")
    conn = psycopg2.connect(dbname=config.db_name, user=config.db_user, password=password,
                           host=config.db_host, port=config.db_port, sslmode="require",
                           connect_timeout=10, application_name="geoflow_gis_definition_admin")
    try:
        conn.set_session(readonly=not write, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            cur.execute("SET LOCAL lock_timeout='3s'")
            cur.execute("SELECT current_database()")
            if cur.fetchone()[0] != config.db_name:
                raise RuntimeError("Tenant identity mismatch")
            yield cur
        if write:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
