"""Central administrator's GIS photo catalogue endpoint."""
import json
import logging

from django.db import connections, transaction, DatabaseError, IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from control.decorators import require_central_admin
from control.services import gis_photo_policy

logger = logging.getLogger(__name__)


@require_central_admin
@require_http_methods(["GET", "POST"])
def catalog_api(request):
    try:
        with transaction.atomic(using="default"), connections["default"].cursor() as cur:
            if not gis_photo_policy.ready(cur):
                return JsonResponse({"ok": False, "error": "photo_policy_schema_pending"}, status=503)
            item_id = None
            if request.method == "POST":
                try:
                    payload = json.loads(request.body)
                except (TypeError, ValueError):
                    raise gis_photo_policy.PhotoPolicyError("요청 JSON이 올바르지 않습니다.") from None
                if not isinstance(payload, dict):
                    raise gis_photo_policy.PhotoPolicyError("요청은 객체여야 합니다.")
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('geoflow.central.gis.photo_policy'))")
                item_id = gis_photo_policy.mutate(cur, payload)
            data = gis_photo_policy.snapshot(cur)
            data["catalog"] = gis_photo_policy.catalog_options(cur)
            return JsonResponse({"ok": True, "id": item_id, **data}, json_dumps_params={"ensure_ascii":False})
    except (gis_photo_policy.PhotoPolicyError, IntegrityError) as exc:
        return JsonResponse({"ok":False,"error":str(exc)}, status=409)
    except DatabaseError:
        logger.exception("Central GIS photo catalogue unavailable")
        return JsonResponse({"ok":False,"error":"photo_policy_unavailable"}, status=503)
