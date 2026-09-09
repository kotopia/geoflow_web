from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone

from . import repository
from .client import G2BError
from .sync import sync_service_notices


def notice_list(request, alias: str, *, can_review: bool, can_manage: bool):
    query = str(request.GET.get("q") or "").strip()
    review_status = str(request.GET.get("status") or "").strip()
    include_all = str(request.GET.get("scope") or "") == "all"
    notices = repository.list_notices(alias, query=query, review_status=review_status, include_all=include_all)
    return render(request, "geoflow_ops/bids/notice_list.html", {
        "notices": notices,
        "query": query,
        "review_status": review_status,
        "include_all": include_all,
        "can_review": can_review,
        "can_manage": can_manage,
        "latest_sync": repository.latest_sync(alias),
        "review_choices": [
            ("unreviewed", "미검토"), ("reviewing", "검토 중"),
            ("interested", "관심"), ("considering", "참여 검토"), ("excluded", "참여 안 함"),
        ],
    })


def settings_page(request, alias: str):
    return render(request, "geoflow_ops/bids/settings.html", {
        "settings": repository.list_settings(alias),
        "latest_sync": repository.latest_sync(alias),
    })


def filter_value_save(request, alias: str):
    try:
        repository.save_filter_value(alias, request.POST)
        repository.reevaluate_all(alias)
    except (ValueError, IntegrityError) as exc:
        return HttpResponseBadRequest(str(exc) if isinstance(exc, ValueError) else "같은 구분과 코드가 이미 등록되어 있습니다.")
    messages.success(request, "입찰 기준 항목을 저장했습니다.")
    return redirect("tenant:bid_settings")


def keyword_save(request, alias: str):
    try:
        repository.save_keyword(alias, request.POST)
        repository.reevaluate_all(alias)
    except (ValueError, IntegrityError) as exc:
        return HttpResponseBadRequest(str(exc) if isinstance(exc, ValueError) else "같은 유형의 키워드가 이미 등록되어 있습니다.")
    messages.success(request, "입찰 키워드를 저장했습니다.")
    return redirect("tenant:bid_settings")


def review_save(request, alias: str, notice_id):
    try:
        repository.save_review(
            alias,
            notice_id,
            status=str(request.POST.get("status") or ""),
            memo=str(request.POST.get("memo") or "").strip(),
            updated_by=repository.actor(request),
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(request, "입찰 검토 상태를 저장했습니다.")
    return redirect("tenant:bid_notice_list")


def sync_now(request, alias: str):
    try:
        days = min(max(int(request.POST.get("days") or 2), 1), 7)
    except (TypeError, ValueError):
        days = 2
    end = timezone.now()
    start = end - timedelta(days=days)
    try:
        result = sync_service_notices(alias, start, end)
    except G2BError as exc:
        messages.error(request, f"입찰공고 수집 실패: {exc}")
    except Exception:
        messages.error(request, "입찰공고 수집 중 오류가 발생했습니다. 수집 이력을 확인하세요.")
    else:
        messages.success(
            request,
            f"공고 {result['fetched']}건 조회, 신규 {result['inserted']}건, 변경 {result['updated']}건을 반영했습니다.",
        )
    return redirect("tenant:bid_notice_list")
