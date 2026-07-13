# geoflow_ops/views_events.py
"""
Process Event API
- 업무 타임라인 이벤트 생성/조회/관리
"""
import logging
import json
from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone

from control.middleware import current_db_alias
from .models import ProcessEvent, ProcessEventAttachment, Attachment

logger = logging.getLogger(__name__)


def _alias(request):
    """현재 테넌트 DB alias"""
    return current_db_alias()


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@login_required
@csrf_exempt
@require_POST
def create_event(request):
    """
    POST /api/events/create/
    
    업무 이벤트 생성 (draft 상태로 시작)
    
    입력 (JSON):
      - scope_type: "contract" | "employee" | "orgunit"
      - scope_id: UUID string
      - stage: "pre_contract" | "contract" | "closeout" | "onboarding" 등
      - event_type: "estimate" | "contract_doc" | "license" 등
      - title: str (optional)
      - memo: str (optional)
      - occurred_at: YYYY-MM-DD (optional)
      - due_at: YYYY-MM-DD (optional)
    
    반환:
      {
        "event_id": "<uuid>",
        "status": "draft",
        "scope_type": "...",
        "scope_id": "...",
        "stage": "...",
        "event_type": "..."
      }
    """
    try:
        data = json.loads(request.body)
    except Exception as e:
        return _json_error(f"Invalid JSON: {e}")

    scope_type = data.get("scope_type")
    scope_id_str = data.get("scope_id")
    stage = data.get("stage")
    event_type = data.get("event_type")
    title = data.get("title", "")
    memo = data.get("memo", "")
    occurred_at = data.get("occurred_at")
    due_at = data.get("due_at")
    status = data.get("status")

    # 필수 필드 검증
    if not all([scope_type, scope_id_str, stage, event_type]):
        return _json_error("Missing required fields: scope_type, scope_id, stage, event_type")

    # UUID 검증
    try:
        scope_id = UUID(scope_id_str)
    except Exception:
        return _json_error("scope_id must be a valid UUID")

    # scope_type 검증 (허용 목록)
    ALLOWED_SCOPE_TYPES = ["contract", "employee", "orgunit"]
    if scope_type not in ALLOWED_SCOPE_TYPES:
        return _json_error(f"Invalid scope_type. Allowed: {', '.join(ALLOWED_SCOPE_TYPES)}")

    alias = _alias(request)
    created_by = request.user.username or request.user.email or "unknown"

    logger.info(
        "[CREATE_EVENT] START alias=%s scope=%s/%s stage=%s type=%s title=%s",
        alias,
        scope_type,
        scope_id,
        stage,
        event_type,
        title,
    )

    try:
        event = ProcessEvent(
            scope_type=scope_type,
            scope_id=scope_id,
            stage=stage,
            event_type=event_type,
            title=title,
            memo=memo,
            status=status or 'draft',
            occurred_at=occurred_at,
            due_at=due_at,
            created_by=created_by,
        )
        event.save(using=alias)
    except Exception as e:
        logger.exception("[CREATE_EVENT] Failed to create event alias=%s", alias)
        return _json_error(f"Failed to create event: {e}", status=500)

    logger.info(
        "[CREATE_EVENT] SUCCESS alias=%s event_id=%s scope=%s/%s stage=%s type=%s",
        alias,
        event.id,
        scope_type,
        scope_id,
        stage,
        event_type,
    )

    return JsonResponse({
        "event_id": str(event.id),
        "status": event.status,
        "scope_type": event.scope_type,
        "scope_id": str(event.scope_id),
        "stage": event.stage,
        "event_type": event.event_type,
        "title": event.title,
    })


@login_required
@require_GET
def list_events(request):
    """
    GET /api/events/list/?scope_type=<type>&scope_id=<id>
    
    특정 scope의 이벤트 목록 조회
    
    반환:
      {
        "events": [
          {
            "id": "<uuid>",
            "stage": "...",
            "event_type": "...",
            "title": "...",
            "status": "...",
            "occurred_at": "...",
            "attachment_count": 2,
            "attachments": [...]
          },
          ...
        ]
      }
    """
    scope_type = request.GET.get("scope_type")
    scope_id_str = request.GET.get("scope_id")

    if not scope_type or not scope_id_str:
        return _json_error("Missing required parameters: scope_type, scope_id")

    try:
        scope_id = UUID(scope_id_str)
    except Exception:
        return _json_error("scope_id must be a valid UUID")

    alias = _alias(request)

    try:
        events = ProcessEvent.objects.using(alias).filter(
            scope_type=scope_type,
            scope_id=scope_id
        ).order_by("stage", "occurred_at", "created_at")

        result_events = []
        for event in events:
            # 첨부 파일 정보 조회
            links = ProcessEventAttachment.objects.using(alias).filter(
                event=event
            ).select_related("attachment").order_by("ord", "created_at")

            attachments = []
            for link in links:
                att = link.attachment
                if not att.deleted_at:  # 삭제되지 않은 것만
                    attachments.append({
                        "id": str(att.id),
                        "original_name": att.original_name,
                        "mime_type": att.mime_type or "",
                        "size_bytes": att.size_bytes,
                        "role": link.role,
                    })

            result_events.append({
                "id": str(event.id),
                "scope_type": event.scope_type,
                "scope_id": str(event.scope_id),
                "stage": event.stage,
                "event_type": event.event_type,
                "title": event.title,
                "memo": event.memo,
                "status": event.status,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "due_at": event.due_at.isoformat() if event.due_at else None,
                "created_at": event.created_at.isoformat(),
                "updated_at": event.updated_at.isoformat() if event.updated_at else None,
                "created_by": event.created_by,
                "attachment_count": len(attachments),
                "attachments": attachments,
            })

    except Exception as e:
        logger.exception("[LIST_EVENTS] Failed to list events")
        return _json_error(f"Failed to list events: {e}", status=500)

    return JsonResponse({"events": result_events})


@login_required
@csrf_exempt
@require_POST
def update_event(request, event_id):
    """
    POST /api/events/update/<event_id>/
    
    이벤트 수정
    
    입력 (JSON):
      - title: str (optional)
      - memo: str (optional)
      - occurred_at: YYYY-MM-DD (optional)
      - status: str (optional)
    
    반환:
      {
        "success": true,
        "event_id": "<uuid>"
      }
    """
    alias = _alias(request)

    try:
        event = ProcessEvent.objects.using(alias).get(id=event_id)
    except ProcessEvent.DoesNotExist:
        return _json_error("Event not found", status=404)

    try:
        data = json.loads(request.body)
    except Exception as e:
        return _json_error(f"Invalid JSON: {e}")

    # 업데이트 가능한 필드만 수정
    if "stage" in data:
        event.stage = data["stage"]
    if "event_type" in data:
        event.event_type = data["event_type"]
    if "title" in data:
        event.title = data["title"]
    if "memo" in data:
        event.memo = data["memo"]
    if "occurred_at" in data:
        event.occurred_at = data["occurred_at"]
    if "status" in data:
        event.status = data["status"]

    try:
        event.save(using=alias)
    except Exception as e:
        logger.exception("[UPDATE_EVENT] Failed to update event_id=%s", event_id)
        return _json_error(f"Failed to update event: {e}", status=500)

    logger.info("[UPDATE_EVENT] alias=%s event_id=%s updated", alias, event_id)

    return JsonResponse({
        "success": True,
        "event_id": str(event.id)
    })


@login_required
@csrf_exempt
@require_POST
def delete_event(request, event_id):
    """
    POST /api/events/delete/<event_id>/
    
    이벤트 삭제 (링크된 첨부는 유지, 링크만 제거)
    """
    alias = _alias(request)

    try:
        event = ProcessEvent.objects.using(alias).get(id=event_id)
    except ProcessEvent.DoesNotExist:
        return _json_error("Event not found", status=404)

    try:
        # 링크된 첨부 제거
        ProcessEventAttachment.objects.using(alias).filter(event=event).delete()
        
        # 이벤트 삭제
        event.delete(using=alias)
    except Exception as e:
        logger.exception("[DELETE_EVENT] Failed to delete event_id=%s", event_id)
        return _json_error(f"Failed to delete event: {e}", status=500)

    logger.info("[DELETE_EVENT] alias=%s event_id=%s deleted", alias, event_id)

    return JsonResponse({
        "success": True,
        "message": "Event deleted successfully"
    })
