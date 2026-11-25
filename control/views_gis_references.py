"""Staff-only central spatial-reference management; default DB only."""

import json
import logging

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from control.decorators import require_central_admin
from control.services import gis_reference_files as files
from control.services import gis_reference_vworld as vworld
from control.services import gis_references as references
from control.services_identity import lookup_user_id_from_request

logger = logging.getLogger(__name__)


def unavailable():
    return JsonResponse(
        {
            "ok": False,
            "error": "참조자료 저장소가 준비되지 않았습니다. 중앙 migration 적용 상태를 확인하세요.",
        },
        status=503,
    )


@require_central_admin
@require_http_methods(["GET"])
def dashboard(request):
    return render(request, "control/gis/references.html")


@require_central_admin
@require_http_methods(["GET", "POST"])
@csrf_protect
def catalog_api(request):
    try:
        try:
            page = int(request.GET.get("history_page", "1"))
            if not 1 <= page <= 1000000:
                raise ValueError
        except ValueError:
            raise references.ReferenceError("이력 페이지를 확인하세요.") from None
        with (
            transaction.atomic(using="default"),
            connections["default"].cursor() as cur,
        ):
            if not references.ready(cur):
                return unavailable()
            item_id = None
            if request.method == "POST":
                if len(request.body) > 16000:
                    raise references.ReferenceError("요청이 너무 큽니다.")
                try:
                    payload = json.loads(request.body)
                except (TypeError, ValueError):
                    raise references.ReferenceError("요청 JSON을 확인하세요.") from None
                actor = lookup_user_id_from_request(request)
                if (
                    isinstance(payload, dict)
                    and payload.get("action") == "setup_vworld"
                ):
                    item_id = vworld.setup(cur, actor)
                else:
                    item_id = references.mutate(cur, payload, actor)
            data = references.snapshot(cur, page)
            if request.GET.get("dataset"):
                data["versions"] = references.versions(cur, request.GET["dataset"])
            return JsonResponse(
                {
                    "ok": True,
                    "id": item_id,
                    "uploads_enabled": files.uploads_enabled(),
                    "vworld": vworld.credential_status(cur),
                    "vworld_services": vworld.SERVICES,
                    **data,
                }
            )
    except references.ReferenceError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except IntegrityError:
        return JsonResponse(
            {"ok": False, "error": "이미 사용 중인 코드·버전이거나 연결된 자료입니다."},
            status=409,
        )
    except DatabaseError:
        # Do not log SQL parameters, source URLs, or credential references.
        logger.error("Central GIS reference catalogue database unavailable")
        return unavailable()


@require_central_admin
@require_http_methods(["POST"])
@csrf_protect
@never_cache
@sensitive_post_parameters("api_key")
@sensitive_variables("payload")
def vworld_key(request):
    # Form encoding allows Django's error reporter to scrub the named secret field.
    try:
        if len(request.body) > 4096:
            raise references.ReferenceError("키 등록 요청이 너무 큽니다.")
        payload = {
            "api_key": request.POST.get("api_key"),
            "domain": request.POST.get("domain"),
            "revision": int(request.POST.get("revision", "-1")),
        }
        with (
            transaction.atomic(using="default"),
            connections["default"].cursor() as cur,
        ):
            status = vworld.save_credential(
                cur, payload, lookup_user_id_from_request(request)
            )
        return JsonResponse({"ok": True, **status})
    except (references.ReferenceError, ValueError) as exc:
        # Never echo input, upstream response or exception text from secret SDKs.
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc)
                if isinstance(exc, references.ReferenceError)
                else "키 등록 요청 형식을 확인하세요.",
            },
            status=400,
        )
    except DatabaseError:
        return unavailable()


@require_central_admin
@require_http_methods(["POST"])
@csrf_protect
@never_cache
def lookup_api(request):
    from control.services import gis_reference_lookup as lookup

    try:
        if len(request.body) > 200000:
            raise references.ReferenceError("조회 요청이 너무 큽니다.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise references.ReferenceError("요청은 객체여야 합니다.")
        with connections["default"].cursor() as cur:
            if payload.get("action") == "inspect":
                result = {
                    "layers": lookup.inspect_file(
                        lookup.dataset(
                            cur, payload.get("dataset_id"), payload.get("version_id")
                        )
                    )
                }
            else:
                result = lookup.lookup(cur, payload)
        return JsonResponse({"ok": True, **result})
    except (
        references.ReferenceError,
        files.ReferenceStorageError,
        ValueError,
        KeyError,
    ) as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc)
                if isinstance(exc, references.ReferenceError)
                else "참조자료 조회 설정 또는 원본 읽기 상태를 확인하세요.",
            },
            status=400,
        )
    except DatabaseError:
        return unavailable()


@require_central_admin
@require_http_methods(["POST"])
@csrf_protect
def upload_original(request, dataset_id):
    if not files.uploads_enabled():
        return JsonResponse(
            {"ok": False, "error": "원본 파일 저장이 아직 활성화되지 않았습니다."},
            status=503,
        )
    stream = None
    try:
        if "file" not in request.FILES:
            raise references.ReferenceError("원본 파일을 선택하세요.")
        stream, info = files.prepare(request.FILES["file"])
        actor = lookup_user_id_from_request(request)
        with (
            transaction.atomic(using="default"),
            connections["default"].cursor() as cur,
        ):
            if not references.ready(cur):
                return unavailable()
            version_id, key = references.reserve_version(
                cur, actor, dataset_id, request.POST, info
            )
        success = False
        try:
            files.store(stream, key)
            success = True
        except (files.ReferenceStorageError, references.ReferenceError):
            # A timeout may have left an object: keep the reserved key for reconciliation.
            logger.error("Central GIS reference original storage failed")
        with (
            transaction.atomic(using="default"),
            connections["default"].cursor() as cur,
        ):
            references.finish_version(cur, actor, version_id, success)
        return JsonResponse(
            {
                "ok": success,
                "id": version_id,
                "error": ""
                if success
                else "원본 저장에 실패했습니다. 이전 원본은 보존됩니다.",
            },
            status=201 if success else 503,
        )
    except references.ReferenceError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except IntegrityError:
        return JsonResponse(
            {"ok": False, "error": "같은 버전명이 있습니다. 새 버전명을 입력하세요."},
            status=409,
        )
    except DatabaseError:
        logger.error("Central GIS reference upload database unavailable")
        return unavailable()
    finally:
        if stream is not None:
            stream.close()


@require_central_admin
@require_http_methods(["GET"])
def download_original(request, version_id):
    try:
        with connections["default"].cursor() as cur:
            if not references.ready(cur):
                return unavailable()
            cur.execute(
                "SELECT object_key,filename FROM gis.reference_version WHERE id=%s AND status='stored'",
                [str(version_id)],
            )
            row = cur.fetchone()
        if not row:
            return JsonResponse(
                {"ok": False, "error": "저장된 원본이 없습니다."}, status=404
            )
        response = HttpResponseRedirect(files.download_url(*row))
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response
    except (DatabaseError, files.ReferenceStorageError):
        logger.error("Central GIS reference original download unavailable")
        return unavailable()
