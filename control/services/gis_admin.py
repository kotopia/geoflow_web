"""Restricted operational connections for transition and usage checks only."""
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


def guard_definition_deletion(cur, data):
    """No user-selected tenant. Check all registered operational stores before deletion.

    A missing/unreachable store blocks deletion; no guesses about unused data.
    Central transactions serialize authoring. Operational writers continue enforcing
    project authorization; repeat usage check is required for destructive migrations.
    """
    from psycopg2 import sql
    from control.services.gis_definitions import DefinitionError, identifier, one
    action=data.get('action')
    if action not in ('delete_code','delete_field','delete_group'):
        return
    uid=identifier(data.get('id'))
    field=None; code=None
    if action=='delete_code':
        field,code=one(cur,'SELECT field_id::text,code FROM gis.definition_code WHERE id=%s',[uid])
    elif action=='delete_field': field=uid
    source=None
    if field:
        source=one(cur,'SELECT source_layer,physical_name FROM gis.definition_field WHERE id=%s',[field])
    configs=list(GroupDBConfig.objects.using('default').values_list('group_id',flat=True))
    for group_id in configs:
        try:
            with tenant_cursor(group_id) as tc:
                tc.execute("SELECT to_regclass('gis.project_definition')")
                if tc.fetchone()[0]:
                    if action=='delete_group':
                        tc.execute('SELECT 1 FROM gis.project_definition WHERE group_id=%s LIMIT 1',[uid])
                    elif action=='delete_field':
                        tc.execute('SELECT 1 FROM gis.project_definition WHERE additions ? %s LIMIT 1',[field])
                    else:
                        tc.execute('SELECT 1 WHERE false')
                    if tc.fetchone(): raise DefinitionError('프로젝트에서 사용 중입니다. 프로젝트 연결을 먼저 해제하세요.')
                if action=='delete_field':
                    tc.execute("SELECT to_regclass('ops.attachments')")
                    if tc.fetchone()[0]:
                        tc.execute('SELECT 1 FROM ops.attachments WHERE purpose=%s LIMIT 1',['gis_form:'+field])
                        if tc.fetchone(): raise DefinitionError('사진 첨부에서 사용 중인 필드입니다.')
                if source:
                    tc.execute("SELECT to_regclass('gis.meta_feature_type')")
                    if not tc.fetchone()[0]: continue
                    if source[0]:
                        tc.execute('SELECT physical_name FROM gis.meta_feature_type WHERE standard_name=%s',[source[0]])
                        tables=[x[0] for x in tc.fetchall()]
                    else:
                        tc.execute('SELECT physical_name FROM gis.meta_feature_type')
                        tables=[x[0] for x in tc.fetchall()]
                    for table in tables:
                        column=source[1] if source[0] else 'ext_data'
                        tc.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='gis' AND table_name=%s AND column_name=%s",[table,column])
                        column_info=tc.fetchone()
                        if not column_info: continue
                        if source[0]:
                            numeric=column_info[0] in ('smallint','integer','bigint','numeric','decimal','real','double precision')
                            if numeric and code is not None:
                                from decimal import Decimal, InvalidOperation
                                try:
                                    if not Decimal(code).is_finite(): continue
                                except InvalidOperation: continue
                            template='SELECT 1 FROM gis.{} WHERE {}=%s::numeric LIMIT 1' if numeric else 'SELECT 1 FROM gis.{} WHERE {}::text=%s LIMIT 1'
                            tc.execute(sql.SQL(template).format(sql.Identifier(table),sql.Identifier(column)),[code])
                        elif code is not None:
                            tc.execute(sql.SQL("SELECT 1 FROM gis.{} WHERE ext_data->'gis_form'->>%s=%s LIMIT 1").format(sql.Identifier(table)),[field,code])
                        else:
                            tc.execute(sql.SQL("SELECT 1 FROM gis.{} WHERE (ext_data->'gis_form') ? %s LIMIT 1").format(sql.Identifier(table)),[field])
                        if tc.fetchone(): raise DefinitionError('시설물 데이터에서 사용 중인 필드 또는 코드입니다.')
        except DefinitionError: raise
        except Exception:
            raise DefinitionError('사용 현황을 확인할 수 없는 테넌트가 있어 삭제를 중지했습니다.') from None
