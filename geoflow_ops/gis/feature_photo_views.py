"""GIS-owned photo metadata and private S3 handoff; never ops.attachments."""
from __future__ import annotations

import json
import re
from uuid import uuid4
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction, DatabaseError, IntegrityError
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from control.services import gis_photo_policy as definitions
from geoflow_ops.services.s3_service import (
    S3ObjectVerificationError, generate_presigned_get_url,
    generate_presigned_put_url, head_private_object,
)
from .photo_policy_views import _feature_ext_data, _paired_scopes, central_photo_snapshot
from .qgis_views import _require_project, _require_qgis_context

_EXTENSIONS = {"image/jpeg":"jpg", "image/png":"png", "image/webp":"webp"}
_TENANT = re.compile(r"^[a-zA-Z0-9_-]+$")


def _body(request):
    try:
        result = json.loads(request.body)
    except (TypeError, ValueError):
        raise definitions.PhotoPolicyError("요청 JSON이 올바르지 않습니다.") from None
    if not isinstance(result, dict):
        raise definitions.PhotoPolicyError("요청은 객체여야 합니다.")
    return result


def _context(request, project_id, layer_id, feature_id, *, write=False):
    alias = _require_qgis_context(request)
    project, policy, plan = _require_project(request,alias,project_id)
    if write and not policy.can_webgis_write(project.id):
        raise PermissionDenied("Permission denied")
    layer_id, feature_id = definitions.uid(layer_id,"레이어"), definitions.uid(feature_id,"객체")
    layer = next((l for l in plan["layers"] if str(l["id"]) == layer_id), None)
    if layer is None:
        raise definitions.PhotoPolicyError("프로젝트에서 사용할 수 없는 레이어입니다.")
    ext = _feature_ext_data(alias,project.id,layer,feature_id)
    data = central_photo_snapshot()
    if data is None:
        raise definitions.PhotoPolicyError("사진 정책 스키마가 준비되지 않았습니다.")
    effective = definitions.resolve(data,_paired_scopes(alias,project.id),layer_id,ext)
    return alias, project, data, effective, layer_id, feature_id


def _slot(effective, slot_id):
    if slot_id is None:
        if effective and not effective["allow_extra_photo"]:
            raise definitions.PhotoPolicyError("이 레이어에서는 일반 사진을 허용하지 않습니다.")
        return None
    slot_id = definitions.uid(slot_id,"사진 항목")
    slots = effective["template"]["slots"] if effective else []
    slot = next((s for s in slots if s["id"] == slot_id), None)
    if slot is None:
        raise definitions.PhotoPolicyError("현재 촬영방식의 사진 항목이 아닙니다.")
    return slot


def _extra(slot, value):
    if not isinstance(value, dict):
        raise definitions.PhotoPolicyError("사진 추가 입력값은 객체여야 합니다.")
    fields = (slot or {}).get("extra_schema") or {"fields":[]}
    definitions.validate_extra_schema(fields)
    allowed = {f["key"]:f for f in fields["fields"]}
    if set(value) - set(allowed):
        raise definitions.PhotoPolicyError("정의되지 않은 사진 추가 입력값입니다.")
    for key, field in allowed.items():
        item = value.get(key)
        if field.get("required") and item in (None, ""):
            raise definitions.PhotoPolicyError(field["label"]+" 값은 필수입니다.")
        if item is None:
            continue
        kind = field["kind"]
        if kind == "boolean":
            valid = isinstance(item,bool)
        elif kind == "integer":
            valid = isinstance(item,int) and not isinstance(item,bool)
        elif kind == "decimal":
            valid = isinstance(item,(int,float)) and not isinstance(item,bool)
        else:
            valid = isinstance(item,str) and len(item) <= 4000
        if not valid:
            raise definitions.PhotoPolicyError(field["label"]+" 자료형이 올바르지 않습니다.")
        choices = field.get("codes")
        if choices and item not in choices:
            raise definitions.PhotoPolicyError(field["label"]+" 참조코드가 올바르지 않습니다.")
    return value


def _key(alias, project_id, layer_id, feature_id, photo_id, extension):
    if not _TENANT.fullmatch(alias):
        raise definitions.PhotoPolicyError("테넌트 키가 올바르지 않습니다.")
    return f"tenants/{alias}/gis/{project_id}/{layer_id}/{feature_id}/{photo_id}.{extension}"


def _rows(cur):
    fields = [c[0] for c in cur.description]
    return [dict(zip(fields, row)) for row in cur.fetchall()]


@login_required
@require_http_methods(["GET", "POST"])
def feature_photos_api(request, project_id, layer_id, feature_id):
    try:
        alias, project, data, effective, layer_id, feature_id = _context(
            request,project_id,layer_id,feature_id,write=request.method == "POST")
        if request.method == "GET":
            with connections[alias].cursor() as cur:
                cur.execute("""SELECT id::text,slot_id::text,object_key,original_name,mime_type,
                    size_bytes,sha256,captured_at,captured_by::text,sort_order,note,extra_data,
                    created_at,updated_at FROM gis.feature_photo
                    WHERE project_id=%s AND layer_id=%s AND feature_id=%s AND deleted_at IS NULL
                    ORDER BY sort_order,created_at,id""",[project.id,layer_id,feature_id])
                photos = _rows(cur)
            for photo in photos:
                if isinstance(photo.get("extra_data"), str):
                    photo["extra_data"] = json.loads(photo["extra_data"])
            if request.GET.get("download_urls") == "1":
                for photo in photos:
                    photo["download_url"] = generate_presigned_get_url(photo["object_key"],
                        content_type=photo["mime_type"],disposition="inline")
            response = JsonResponse({"ok":True,"photos":photos,"photo_policy_revision":data["revision"]})
            response["Cache-Control"] = "private, no-store"
            return response
        body = _body(request)
        action = body.get("action")
        if action == "presign":
            mime = body.get("mime_type")
            if mime not in _EXTENSIONS:
                raise definitions.PhotoPolicyError("지원하지 않는 사진 형식입니다.")
            _slot(effective,body.get("slot_id"))
            photo_id = str(uuid4())
            key = _key(alias,project.id,layer_id,feature_id,photo_id,_EXTENSIONS[mime])
            signed = generate_presigned_put_url(key,mime_type=mime,expires_in=900)
            return JsonResponse({"ok":True,"id":photo_id,"object_key":key,**signed})
        if action != "finalize":
            raise definitions.PhotoPolicyError("지원하지 않는 사진 작업입니다.")
        photo_id = definitions.uid(body.get("id"),"사진")
        mime = body.get("mime_type")
        if mime not in _EXTENSIONS:
            raise definitions.PhotoPolicyError("지원하지 않는 사진 형식입니다.")
        key = _key(alias,project.id,layer_id,feature_id,photo_id,_EXTENSIONS[mime])
        slot = _slot(effective,body.get("slot_id"))
        extra = _extra(slot,body.get("extra_data",{}))
        filename = str(body.get("original_name") or "").strip()
        if not filename or len(filename) > 255:
            raise definitions.PhotoPolicyError("원본 파일명을 확인하세요.")
        captured_at = None
        if body.get("captured_at"):
            captured_at = parse_datetime(str(body["captured_at"]))
            if captured_at is None or captured_at.utcoffset() is None:
                raise definitions.PhotoPolicyError("촬영 시각에는 시간대를 포함해야 합니다.")
        try:
            captured_by = str(UUID(str(request.user.pk)))
        except (TypeError, ValueError, AttributeError):
            captured_by = None
        metadata = head_private_object(key)
        if metadata.content_type != mime or not metadata.encryption_matches or not 0 < metadata.size_bytes <= 25*1024*1024:
            raise definitions.PhotoPolicyError("업로드한 사진의 형식·크기·암호화를 확인하세요.")
        with transaction.atomic(using=alias), connections[alias].cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                        ["gis.photo:"+str(project.id)+":"+layer_id+":"+feature_id])
            if slot:
                cur.execute("""SELECT count(*) FROM gis.feature_photo WHERE project_id=%s
                    AND layer_id=%s AND feature_id=%s AND slot_id=%s AND deleted_at IS NULL""",
                    [project.id,layer_id,feature_id,slot["id"]])
                if int(cur.fetchone()[0]) >= int(slot["max_count"]):
                    raise definitions.PhotoPolicyError("사진 항목의 최대 장수를 초과했습니다.")
            cur.execute("""INSERT INTO gis.feature_photo(id,project_id,layer_id,feature_id,slot_id,
                object_key,original_name,mime_type,size_bytes,captured_at,captured_by,
                extra_data,note,sort_order)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                [photo_id,project.id,layer_id,feature_id,slot["id"] if slot else None,
                 key,filename,mime,metadata.size_bytes,captured_at,captured_by,json.dumps(extra),
                 str(body.get("note") or "")[:2000],int(body.get("sort_order") or 0)])
        return JsonResponse({"ok":True,"id":photo_id},status=201)
    except (definitions.PhotoPolicyError, ValueError, IntegrityError, S3ObjectVerificationError) as exc:
        return JsonResponse({"ok":False,"error":str(exc)},status=409)
    except DatabaseError:
        return JsonResponse({"ok":False,"error":"gis_photo_unavailable"},status=503)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def feature_photo_item_api(request, project_id, layer_id, feature_id, photo_id):
    try:
        alias, project, data, effective, layer_id, feature_id = _context(
            request,project_id,layer_id,feature_id,write=True)
        photo_id = definitions.uid(photo_id,"사진")
        with transaction.atomic(using=alias), connections[alias].cursor() as cur:
            cur.execute("""SELECT slot_id::text FROM gis.feature_photo
                WHERE id=%s AND project_id=%s AND layer_id=%s AND feature_id=%s
                  AND deleted_at IS NULL FOR UPDATE""",
                [photo_id,project.id,layer_id,feature_id])
            row = cur.fetchone()
            if row is None:
                return JsonResponse({"ok":False,"error":"photo_not_found"},status=404)
            if request.method == "DELETE":
                cur.execute("""UPDATE gis.feature_photo SET deleted_at=now(),deleted_by=%s,
                    updated_at=now() WHERE id=%s""",[str(request.user.pk),photo_id])
            else:
                body = _body(request)
                if set(body)-{"note","sort_order","extra_data"}:
                    raise definitions.PhotoPolicyError("수정할 수 없는 사진 항목입니다.")
                # Existing photos remain editable after a feature switches mode;
                # the old slot is retained until explicitly reclassified.
                slot = next((s for s in data["slots"] if s["id"] == row[0]),None)
                if "extra_data" in body and row[0] and slot is None:
                    raise definitions.PhotoPolicyError("기존 사진 항목 정의를 찾을 수 없습니다.")
                extra = _extra(slot,body.get("extra_data",{})) if "extra_data" in body else None
                cur.execute("""UPDATE gis.feature_photo SET
                    note=COALESCE(%s,note),sort_order=COALESCE(%s,sort_order),
                    extra_data=COALESCE(%s::jsonb,extra_data),updated_at=now() WHERE id=%s""",
                    [str(body["note"])[:2000] if "note" in body else None,
                     int(body["sort_order"]) if "sort_order" in body else None,
                     json.dumps(extra) if extra is not None else None,photo_id])
        return JsonResponse({"ok":True,"id":photo_id})
    except (definitions.PhotoPolicyError, ValueError, IntegrityError) as exc:
        return JsonResponse({"ok":False,"error":str(exc)},status=409)
    except DatabaseError:
        return JsonResponse({"ok":False,"error":"gis_photo_unavailable"},status=503)
