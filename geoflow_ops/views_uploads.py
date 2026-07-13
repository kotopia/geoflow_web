# geoflow_ops/views_uploads.py
"""
첨부파일 업로드 API (S3 Presigned URL 방식)
- POST /api/uploads/presign-put/
- POST /api/uploads/commit/
- GET /api/uploads/presign-get/<attachment_id>/
"""
import logging
from typing import Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET, require_http_methods

from control.middleware import current_db_alias
from .models import Attachment
from .services.s3_service import (
    build_object_key,
    generate_presigned_put_url,
    generate_presigned_get_url,
    extract_extension,
)

logger = logging.getLogger(__name__)


def _alias(request):
    """현재 테넌트 DB alias"""
    return current_db_alias()


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@login_required
@csrf_exempt
@require_POST
def presign_put(request):
    """
    POST /api/uploads/presign-put/
    
    입력 (JSON):
      - entity_type: "employee" | "contract" | "orgunit" | "event"
      - entity_id: UUID string
      - purpose: "photo" | "attachment" | "logo" | "doc" | ...
      - filename: "example.jpg"
      - mime_type: "image/jpeg" (optional)
      - size_bytes: 12345 (optional)
      - event_id: UUID string (optional, entity_type="event"일 때 필수)
    
    반환:
      {
        "object_key": "tenants/.../...",
        "presigned_url": "https://...",
        "headers": {...}
      }
    """
    import json
    try:
        data = json.loads(request.body)
    except Exception as e:
        return _json_error(f"Invalid JSON: {e}")

    entity_type = data.get("entity_type")
    entity_id_str = data.get("entity_id")
    purpose = data.get("purpose")
    filename = data.get("filename")
    mime_type = data.get("mime_type")
    size_bytes = data.get("size_bytes")
    event_id_str = data.get("event_id")  # event 타입일 때 사용

    if not all([entity_type, entity_id_str, purpose, filename]):
        return _json_error("Missing required fields: entity_type, entity_id, purpose, filename")

    if entity_type not in ("employee", "contract", "orgunit", "event"):
        return _json_error("entity_type must be 'employee', 'contract', 'orgunit', or 'event'")

    # event 타입일 때는 event_id 필수
    if entity_type == "event" and not event_id_str:
        return _json_error("event_id is required when entity_type is 'event'")

    try:
        entity_id = UUID(entity_id_str)
    except Exception:
        return _json_error("entity_id must be a valid UUID")

    alias = _alias(request)
    extension = extract_extension(filename)

    try:
        object_key = build_object_key(
            tenant_db_alias=alias,
            entity_type=entity_type,
            entity_id=str(entity_id),
            purpose=purpose,
            extension=extension,
            event_id=event_id_str,  # event 타입일 때 사용
        )
    except Exception as e:
        logger.exception("[PRESIGN_PUT] build_object_key failed")
        return _json_error(f"Failed to build object_key: {e}")

    try:
        presigned = generate_presigned_put_url(
            object_key=object_key,
            mime_type=mime_type,
            expires_in=3600,
        )
    except Exception as e:
        logger.exception("[PRESIGN_PUT] generate_presigned_put_url failed")
        return _json_error(f"Failed to generate presigned URL: {e}")

    logger.info(
        "[PRESIGN_PUT] alias=%s entity=%s/%s purpose=%s object_key=%s size=%s",
        alias,
        entity_type,
        entity_id,
        purpose,
        object_key,
        size_bytes,
    )

    return JsonResponse({
        "object_key": object_key,
        "presigned_url": presigned["presigned_url"],
        "headers": presigned.get("headers", {}),
    })


@login_required
@csrf_exempt
@require_POST
def commit(request):
    """
    POST /api/uploads/commit/
    
    브라우저가 S3에 PUT 완료 후 호출 → DB에 메타데이터 저장
    
    입력 (JSON):
      - object_key: "tenants/..."
      - entity_type: "employee" | "contract" | "event"
      - entity_id: UUID string
      - purpose: "photo" | "attachment" | "thumb"
      - original_name: "myfile.jpg"
      - mime_type: "image/jpeg" (optional)
      - size_bytes: 12345 (optional)
      - sha256: "abc..." (optional)
      - kind: "file" | "image" | "thumb" (optional, default: "file")
      - parent_attachment_id: UUID string (optional, for thumbnails)
      - event_id: UUID string (optional, entity_type="event"일 때 자동 링크)
    
    반환:
      {
        "attachment_id": "<uuid>",
        "object_key": "...",
        "event_link_id": "<uuid>" (event 타입일 때만)
      }
    """
    import json
    try:
        data = json.loads(request.body)
    except Exception as e:
        return _json_error(f"Invalid JSON: {e}")

    object_key = data.get("object_key")
    entity_type = data.get("entity_type")
    entity_id_str = data.get("entity_id")
    purpose = data.get("purpose")
    original_name = data.get("original_name")
    mime_type = data.get("mime_type")
    size_bytes = data.get("size_bytes")
    sha256 = data.get("sha256")
    kind = data.get("kind", "file")
    parent_attachment_id_str = data.get("parent_attachment_id")
    event_id_str = data.get("event_id")  # event 타입일 때 링크용

    if not all([object_key, entity_type, entity_id_str, purpose, original_name]):
        return _json_error("Missing required fields: object_key, entity_type, entity_id, purpose, original_name")

    try:
        entity_id = UUID(entity_id_str)
    except Exception:
        return _json_error("entity_id must be a valid UUID")

    # parent_attachment_id 검증
    parent_attachment_id = None
    if parent_attachment_id_str:
        try:
            parent_attachment_id = UUID(parent_attachment_id_str)
        except Exception:
            return _json_error("parent_attachment_id must be a valid UUID")

    alias = _alias(request)

    try:
        # 중복 방지: object_key unique constraint
        attachment = Attachment(
            entity_type=entity_type,
            entity_id=entity_id,
            purpose=purpose,
            object_key=object_key,
            original_name=original_name,
            mime_type=mime_type or "",
            size_bytes=size_bytes,
            sha256=sha256,
            kind=kind,
            parent_id=parent_attachment_id,
            active=True,
            ord=0,
            meta={},
        )
        attachment.save(using=alias)
    except Exception as e:
        logger.exception("[COMMIT] Failed to save Attachment alias=%s object_key=%s", alias, object_key)
        return _json_error(f"Failed to save attachment: {e}", status=500)

    logger.info(
        "[COMMIT] alias=%s attachment_id=%s entity=%s/%s purpose=%s object_key=%s",
        alias,
        attachment.id,
        entity_type,
        entity_id,
        purpose,
        object_key,
    )

    # 사용자 자신의 employee 사진 업로드 시 세션의 avatar_attachment_id 갱신
    if entity_type == "employee" and purpose in ("photo", "thumb", "photo_thumb"):
        try:
            # 현재 로그인 사용자의 employee_id 조회
            from django.db import connections
            user_email = request.user.username
            
            with connections[alias].cursor() as cur:
                cur.execute("""
                    SELECT id::text, name
                    FROM hr.employee_profile
                    WHERE lower(email) = lower(%s)
                    LIMIT 1
                """, [user_email])
                emp_row = cur.fetchone()
                
                if emp_row and str(emp_row[0]) == str(entity_id):
                    # 본인 사진 업로드인 경우 topbar 세션 캐시 갱신
                    emp_name = emp_row[1] or user_email
                    
                    # photo_thumb 또는 thumb 우선
                    if purpose in ("photo_thumb", "thumb"):
                        request.session["avatar_attachment_id"] = str(attachment.id)
                        request.session["topbar_avatar_attachment_id"] = str(attachment.id)
                    elif purpose == "photo":
                        # thumb이 없을 때만 photo로 갱신
                        if not request.session.get("avatar_attachment_id"):
                            request.session["avatar_attachment_id"] = str(attachment.id)
                        if not request.session.get("topbar_avatar_attachment_id"):
                            request.session["topbar_avatar_attachment_id"] = str(attachment.id)
                    
                    # topbar 이름도 갱신
                    request.session["topbar_name"] = emp_name
                    request.session["topbar_emp_id"] = str(emp_row[0])
        except Exception as e:
            # 세션 갱신 실패해도 업로드 자체는 성공으로 처리
            logger.warning("[COMMIT] Failed to update avatar session: %s", e)

    # entity_type="event"일 때 자동으로 ProcessEventAttachment 링크 생성
    event_link_id = None
    if entity_type == "event" and event_id_str:
        try:
            from .models import ProcessEvent, ProcessEventAttachment
            event_id = UUID(event_id_str)
            
            # Event 존재 확인
            event = ProcessEvent.objects.using(alias).get(id=event_id)
            
            # 링크 생성 (중복 방지: unique constraint)
            link, created = ProcessEventAttachment.objects.using(alias).get_or_create(
                event=event,
                attachment=attachment,
                defaults={
                    "role": "primary",  # 기본값: primary
                    "ord": 0,
                }
            )
            event_link_id = str(link.id)
            
            # Event 상태 업데이트: draft → done (최초 첨부 시)
            if event.status == 'draft':
                event.status = 'done'
                event.save(using=alias)
                logger.info("[COMMIT] Event %s status updated: draft → done", event_id)
            
            logger.info(
                "[COMMIT] Event link created: event_id=%s attachment_id=%s link_id=%s created=%s",
                event_id,
                attachment.id,
                event_link_id,
                created,
            )
        except ProcessEvent.DoesNotExist:
            logger.warning("[COMMIT] Event not found: event_id=%s", event_id_str)
        except Exception as e:
            logger.exception("[COMMIT] Failed to create event link: event_id=%s", event_id_str)

    response_data = {
        "attachment_id": str(attachment.id),
        "object_key": object_key,
    }
    
    if event_link_id:
        response_data["event_link_id"] = event_link_id

    return JsonResponse(response_data)


@login_required
@require_GET
def presign_get(request, attachment_id):
    """
    GET /api/uploads/presign-get/<attachment_id>/
    
    반환:
      {
        "presigned_url": "https://...",
        "original_name": "...",
        "mime_type": "..."
      }
    """
    alias = _alias(request)

    try:
        att = Attachment.objects.using(alias).get(id=attachment_id)
    except Attachment.DoesNotExist:
        return _json_error("Attachment not found", status=404)

    # 삭제된 파일은 410 Gone 반환
    if att.deleted_at:
        logger.warning(
            "[PRESIGN_GET] Attempt to access deleted attachment: alias=%s attachment_id=%s deleted_at=%s",
            alias,
            attachment_id,
            att.deleted_at,
        )
        return _json_error("Attachment has been deleted", status=410)

    # mode 파라미터 읽기 (inline | download)
    mode = request.GET.get("mode", "inline")

    # PDF 여부 판정 (mime_type 또는 확장자 기반)
    is_pdf = (
        att.mime_type == "application/pdf" or
        (att.original_name and att.original_name.lower().endswith(".pdf"))
    )

    try:
        if is_pdf:
            if mode == "download":
                presigned_url = generate_presigned_get_url(
                    att.object_key,
                    expires_in=3600,
                    content_type="application/pdf",
                    disposition="attachment",
                    filename=att.original_name
                )
            else:  # mode == "inline" (기본값)
                presigned_url = generate_presigned_get_url(
                    att.object_key,
                    expires_in=3600,
                    content_type="application/pdf",
                    disposition="inline",
                    filename=att.original_name
                )
        else:
            presigned_url = generate_presigned_get_url(
                att.object_key,
                expires_in=3600
            )
    except Exception as e:
        logger.exception("[PRESIGN_GET] Failed to generate presigned GET URL attachment_id=%s", attachment_id)
        return _json_error(f"Failed to generate download URL: {e}", status=500)

    logger.info(
        "[PRESIGN_GET] alias=%s attachment_id=%s object_key=%s is_pdf=%s mode=%s",
        alias,
        attachment_id,
        att.object_key,
        is_pdf,
        mode,
    )

    return JsonResponse({
        "presigned_url": presigned_url,
        "original_name": att.original_name,
        "mime_type": att.mime_type or "",
    })


@login_required
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_attachment(request, attachment_id):
    """
    DELETE /api/uploads/delete/<attachment_id>/
    
    첨부파일 소프트 삭제 (deleted_at, deleted_by 설정)
    """
    alias = _alias(request)

    try:
        att = Attachment.objects.using(alias).get(id=attachment_id)
    except Attachment.DoesNotExist:
        return _json_error("Attachment not found", status=404)

    # 이미 삭제된 파일
    if att.deleted_at:
        return _json_error("Already deleted", status=410)

    # 소프트 삭제 처리
    att.deleted_at = timezone.now()
    att.deleted_by = request.user.username
    att.is_deleted = True
    att.save(using=alias)

    logger.info(
        "[DELETE_ATTACHMENT] alias=%s attachment_id=%s deleted_by=%s",
        alias,
        attachment_id,
        request.user.username,
    )

    # 아바타 삭제 시 세션 갱신
    if str(att.id) == request.session.get("avatar_attachment_id"):
        try:
            # 다른 사진이 있는지 조회
            from django.db import connections
            user_email = request.user.username
            
            with connections[alias].cursor() as cur:
                cur.execute("""
                    SELECT id::text, name
                    FROM hr.employee_profile
                    WHERE lower(email) = lower(%s)
                    LIMIT 1
                """, [user_email])
                emp_row = cur.fetchone()
                
                if emp_row:
                    employee_id = emp_row[0]
                    
                    # 남은 photo_thumb 우선 조회
                    cur.execute("""
                        SELECT id::text
                        FROM ops.attachments
                        WHERE entity_type = 'employee'
                        AND entity_id::text = %s
                        AND purpose IN ('photo_thumb', 'thumb')
                        AND active = true
                        AND (deleted_at IS NULL OR is_deleted = false)
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, [employee_id])
                    thumb_row = cur.fetchone()
                    
                    if thumb_row:
                        request.session["avatar_attachment_id"] = thumb_row[0]
                        request.session["topbar_avatar_attachment_id"] = thumb_row[0]
                    else:
                        # thumb 없으면 photo 조회
                        cur.execute("""
                            SELECT id::text
                            FROM ops.attachments
                            WHERE entity_type = 'employee'
                            AND entity_id::text = %s
                            AND purpose = 'photo'
                            AND active = true
                            AND (deleted_at IS NULL OR is_deleted = false)
                            ORDER BY created_at DESC
                            LIMIT 1
                        """, [employee_id])
                        photo_row = cur.fetchone()
                        
                        if photo_row:
                            request.session["avatar_attachment_id"] = photo_row[0]
                            request.session["topbar_avatar_attachment_id"] = photo_row[0]
                        else:
                            # 사진이 없으면 None (기본 아바타)
                            request.session["avatar_attachment_id"] = None
                            request.session["topbar_avatar_attachment_id"] = None
        except Exception as e:
            logger.warning("[DELETE_ATTACHMENT] Failed to update avatar session: %s", e)

    return JsonResponse({
        "success": True,
        "message": "Attachment deleted successfully"
    })


@login_required
@require_GET
def excel_preview(request, attachment_id):
    """
    GET /uploads/excel-preview/<attachment_id>/
    
    엑셀 파일 미리보기 페이지 (SheetJS 사용)
    """
    return render(request, "geoflow_ops/excel_preview.html", {
        "attachment_id": attachment_id
    })
