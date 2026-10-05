"""Exercise Survey source presign/upload/import against production and roll DB writes back."""
from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.request import Request, urlopen
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.test import RequestFactory

from control.models import GroupDBConfig
from control.middleware import _set_threadlocal
from control.services.tenant_db_secret_resolver import resolve_tenant_db_password
from geoflow_ops.gis import survey_views
from geoflow_ops.gis.layer_plan import project_layer_plan
from geoflow_ops.services.s3_service import get_bucket_name, get_s3_client


@contextmanager
def _tenant_alias(config):
    alias = str(config.db_alias or "").strip()
    if not alias or alias == "default":
        raise CommandError("survey_upload_smoke_tenant_alias=invalid")
    password = resolve_tenant_db_password(str(config.db_password or "").strip())
    if not password:
        raise CommandError("survey_upload_smoke_tenant_credential=unavailable")
    existing = settings.DATABASES.get(alias)
    db_config = dict(settings.DATABASES["default"])
    db_config.update({
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": config.db_name,
        "USER": config.db_user,
        "PASSWORD": password,
        "HOST": config.db_host,
        "PORT": config.db_port,
        "CONN_MAX_AGE": 0,
    })
    settings.DATABASES[alias] = db_config
    connections.databases[alias] = db_config
    try:
        yield alias
    finally:
        connections[alias].close()
        if existing is None:
            settings.DATABASES.pop(alias, None)
            connections.databases.pop(alias, None)
        else:
            settings.DATABASES[alias] = existing
            connections.databases[alias] = existing


def _json(response, expected=200):
    body = json.loads(response.content.decode("utf-8"))
    if response.status_code != expected or not body.get("ok"):
        raise CommandError(
            f"survey_upload_smoke_api=failed status={response.status_code} "
            f"error={body.get('error', 'unknown')}"
        )
    return body


class Command(BaseCommand):
    help = "Verify Survey upload/import/read/delete with rollback and S3 cleanup"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        configs = list(
            GroupDBConfig.objects.using("default")
            .select_related("group")
            .filter(group__status="active")
            .exclude(db_alias="default")
            .order_by("group_id")
        )
        factory = RequestFactory()
        source_id = str(uuid4())
        object_key = None
        chosen = None
        put_status = None
        import_result = None
        source_count = point_count = 0
        delete_result = precheck = None

        try:
            for config in configs:
                with _tenant_alias(config) as alias:
                    with connections[alias].cursor() as cursor:
                        cursor.execute(
                            "SELECT to_regclass('gis.survey_source'),"
                            "to_regclass('gis.survey'),to_regclass('prj.projects')"
                        )
                        if not all(cursor.fetchone()):
                            continue
                        cursor.execute("SELECT id FROM prj.projects ORDER BY id")
                        project_ids = [row[0] for row in cursor.fetchall()]
                    project_id = next((pid for pid in project_ids
                                       if project_layer_plan(alias, pid).get("ready")
                                       and project_layer_plan(alias, pid).get("gis_enabled")), None)
                    if not project_id:
                        continue
                    chosen = (alias, project_id)
                    user = SimpleNamespace(is_authenticated=True, pk=None, email="", username="")
                    session = {
                        "tenant_db_alias": alias,
                        "db_key": alias,
                        "group_id": str(config.group_id),
                        "gf_perms": ["maps.view"],
                        "gf_roles": ["tenant_admin"],
                    }
                    _set_threadlocal(alias, False, str(config.group_id))

                    def call(method, path, payload=None):
                        request = factory.generic(
                            method,
                            path,
                            data=json.dumps(payload) if payload is not None else None,
                            content_type="application/json",
                            HTTP_ACCEPT="application/json",
                        )
                        request.user = user
                        request.session = session
                        if "survey-points" in path:
                            return survey_views.project_survey_points_api(request, project_id)
                        if f"survey-sources/{source_id}" in path:
                            return survey_views.project_survey_source_api(
                                request, project_id, source_id
                            )
                        return survey_views.project_survey_sources_api(request, project_id)

                    with transaction.atomic(using=alias):
                        presign = _json(call(
                            "POST",
                            f"/gis/projects/{project_id}/api/survey-sources/",
                            {
                                "action": "presign",
                                "id": source_id,
                                "original_file_name": "geoflow-survey-smoke.csv",
                                "mime_type": "text/csv",
                            },
                        ))
                        required = {"id", "object_key", "presigned_url", "headers"}
                        if not required.issubset(presign):
                            raise CommandError("survey_upload_smoke_presign_contract=invalid")
                        object_key = presign["object_key"]
                        file_bytes = (
                            "source_row_id,longitude,latitude,raw_code\n"
                            + "\n".join(
                                f"SMOKE-{i:03d},127.{i:06d},36.{i:06d},SMOKE"
                                for i in range(1, 23)
                            )
                            + "\n"
                        ).encode("utf-8")
                        upload = Request(
                            presign["presigned_url"],
                            data=file_bytes,
                            headers=presign["headers"],
                            method="PUT",
                        )
                        with urlopen(upload, timeout=30) as response:
                            put_status = response.status
                            response.read()
                        if put_status not in (200, 201, 204):
                            raise CommandError(
                                f"survey_upload_smoke_put_status=unexpected:{put_status}"
                            )
                        payload = {
                            "id": source_id,
                            "source_type": "CSV",
                            "original_file_name": "geoflow-survey-smoke.csv",
                            "original_file_key": object_key,
                            "source_crs": "EPSG:5186",
                            "survey_date": "2026-10-05",
                            "note": "rollback production smoke",
                            "points": [
                                ({
                                    "source_row_id": f"SMOKE-{i:03d}",
                                    "longitude": 127 + i / 1_000_000,
                                    "latitude": 36 + i / 1_000_000,
                                    "raw_code": "SMOKE",
                                    "solution_info": "FIX",
                                    "pdop": 1.2,
                                    "antenna_height": 1.8,
                                } if i <= 11 else {
                                    "source_row_id": f"SMOKE-{i:03d}",
                                    "raw_x": 200000 + i,
                                    "raw_y": 500000 + i,
                                    "raw_z": 10 + i / 10,
                                    "raw_code": "SMOKE",
                                    "solution_info": "FIX",
                                    "pdop": 1.2,
                                    "antenna_height": 1.8,
                                })
                                for i in range(1, 23)
                            ],
                        }
                        import_result = _json(call(
                            "POST",
                            f"/gis/projects/{project_id}/api/survey-sources/",
                            payload,
                        ))
                        sources = _json(call(
                            "GET",
                            f"/gis/projects/{project_id}/api/survey-sources/",
                        ))
                        points = _json(call(
                            "GET",
                            f"/gis/projects/{project_id}/api/survey-points/?source_id={source_id}",
                        ))
                        source_count = sum(x["id"] == source_id for x in sources["sources"])
                        point_count = sum(x["source_id"] == source_id for x in points["points"])
                        if source_count != 1 or point_count != 22:
                            raise CommandError("survey_upload_smoke_readback=failed")
                        if any(
                            point.get("survey_date") != "2026-10-05"
                            or point.get("name") != point.get("source_row_id")
                            or point.get("code") != "SMOKE"
                            or point.get("longitude") is None
                            or point.get("latitude") is None
                            for point in points["points"]
                        ):
                            raise CommandError("survey_upload_smoke_point_metadata=failed")
                        precheck = _json(call(
                            "GET",
                            f"/gis/projects/{project_id}/api/survey-sources/{source_id}/",
                        ))
                        if not precheck["delete"].get("can_delete"):
                            raise CommandError("survey_upload_smoke_delete_precheck=blocked")
                        delete_result = _json(call(
                            "DELETE",
                            f"/gis/projects/{project_id}/api/survey-sources/{source_id}/",
                        ))
                        after_sources = _json(call(
                            "GET", f"/gis/projects/{project_id}/api/survey-sources/"
                        ))
                        after_points = _json(call(
                            "GET",
                            f"/gis/projects/{project_id}/api/survey-points/?source_id={source_id}",
                        ))
                        if any(x["id"] == source_id for x in after_sources["sources"]):
                            raise CommandError("survey_upload_smoke_delete_source=failed")
                        if after_points["points"]:
                            raise CommandError("survey_upload_smoke_delete_points=failed")
                        # The production FK from feature_change_log to
                        # changeset_receipt is deferred until commit. Force all
                        # deferred constraints now so rollback-based smoke can
                        # no longer produce a false positive.
                        with connections[alias].cursor() as cursor:
                            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                        transaction.set_rollback(True, using=alias)
                    break
            if not chosen:
                raise CommandError("survey_upload_smoke_project=unavailable")
        finally:
            _set_threadlocal(None, True, None)
            if object_key:
                get_s3_client().delete_object(Bucket=get_bucket_name(), Key=object_key)

        self.stdout.write(f"survey_upload_smoke_tenant={chosen[0]}")
        self.stdout.write("survey_upload_smoke_presign_fields=id,object_key,presigned_url,headers")
        self.stdout.write("survey_upload_smoke_method=PUT")
        self.stdout.write(f"survey_upload_smoke_put_status={put_status}")
        self.stdout.write(f"survey_upload_smoke_created={import_result['created']}")
        self.stdout.write(f"survey_upload_smoke_updated={import_result['updated']}")
        self.stdout.write(f"survey_upload_smoke_source_readback={source_count}")
        self.stdout.write(f"survey_upload_smoke_point_readback={point_count}")
        self.stdout.write("survey_upload_smoke_point_metadata=verified")
        self.stdout.write(
            f"survey_upload_smoke_delete_precheck={str(precheck['delete']['can_delete']).lower()}"
        )
        self.stdout.write(
            f"survey_upload_smoke_deleted_points={delete_result['deleted_point_count']}"
        )
        self.stdout.write(
            f"survey_upload_smoke_deleted_object={str(delete_result['deleted_object']).lower()}"
        )
        self.stdout.write("survey_upload_smoke_deferred_constraints=verified")
        self.stdout.write("survey_upload_smoke_db_rollback=yes")
        self.stdout.write("survey_upload_smoke_s3_cleanup=yes")
        self.stdout.write("RESULT gis_survey_source_upload_smoke=SUCCESS")
