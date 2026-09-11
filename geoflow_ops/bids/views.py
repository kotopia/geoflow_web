from __future__ import annotations

import math
from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone

from . import repository
from .client import G2BError
from .sync import sync_service_notices
from procurement.service import enabled as central_enabled, request_sync
from procurement import tenant as central_repository


def notice_list(request, alias: str, *, can_review: bool, can_manage: bool):
    repo = central_repository if central_enabled(alias) else repository
    query = str(request.GET.get("q") or "").strip()
    review_status = str(request.GET.get("status") or "").strip()
    include_all = str(request.GET.get("scope") or "") == "all"
    try:
        per_page = int(request.GET.get("per_page") or 15)
    except (TypeError, ValueError):
        per_page = 15
    per_page = 30 if per_page == 30 else 15
    try:
        page = max(int(request.GET.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    total_count = repo.count_notices(
        alias, query=query, review_status=review_status, include_all=include_all
    )
    total_pages = max(math.ceil(total_count / per_page), 1)
    page = min(page, total_pages)
    notices = repo.list_notices(
        alias,
        query=query,
        review_status=review_status,
        include_all=include_all,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    query_params = request.GET.copy()
    query_params["per_page"] = str(per_page)
    query_params.pop("page", None)
    previous_query = next_query = ""
    if page > 1:
        previous_params = query_params.copy()
        previous_params["page"] = str(page - 1)
        previous_query = previous_params.urlencode()
    if page < total_pages:
        next_params = query_params.copy()
        next_params["page"] = str(page + 1)
        next_query = next_params.urlencode()
    return render(request, "geoflow_ops/bids/notice_list.html", {
        "notices": notices,
        "query": query,
        "review_status": review_status,
        "include_all": include_all,
        "per_page": per_page,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "page_start": ((page - 1) * per_page + 1) if total_count else 0,
        "page_end": min(page * per_page, total_count),
        "previous_query": previous_query,
        "next_query": next_query,
        "can_review": can_review,
        "can_manage": can_manage,
        "latest_sync": repo.latest_sync(alias),
        "central_mode": central_enabled(alias),
        "review_choices": [
            ("unreviewed", "미검토"), ("reviewing", "검토 중"),
            ("interested", "관심"), ("considering", "참여 검토"), ("excluded", "참여 안 함"),
        ],
    })


def settings_page(request, alias: str):
    repo = central_repository if central_enabled(alias) else repository
    return render(request, "geoflow_ops/bids/settings.html", {
        "settings": repository.list_settings(alias),
        "latest_sync": repo.latest_sync(alias),
    })


def filter_value_save(request, alias: str):
    try:
        repository.save_filter_value(alias, request.POST)
        if not central_enabled(alias):
            repository.reevaluate_all(alias)
    except (ValueError, IntegrityError) as exc:
        return HttpResponseBadRequest(str(exc) if isinstance(exc, ValueError) else "같은 구분과 코드가 이미 등록되어 있습니다.")
    messages.success(request, "입찰 기준 항목을 저장했습니다.")
    return redirect("tenant:bid_settings")


def keyword_save(request, alias: str):
    try:
        repository.save_keyword(alias, request.POST)
        if not central_enabled(alias):
            repository.reevaluate_all(alias)
    except (ValueError, IntegrityError) as exc:
        return HttpResponseBadRequest(str(exc) if isinstance(exc, ValueError) else "같은 유형의 키워드가 이미 등록되어 있습니다.")
    messages.success(request, "입찰 키워드를 저장했습니다.")
    return redirect("tenant:bid_settings")


def review_save(request, alias: str, notice_id):
    repo = central_repository if central_enabled(alias) else repository
    try:
        repo.save_review(
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
    if central_enabled(alias):
        count = request_sync()
        messages.success(request, f"중앙 수집조건 {count}개의 갱신을 요청했습니다. 수집은 백그라운드에서 진행합니다.")
        return redirect("tenant:bid_notice_list")
    try:
        days = min(max(int(request.POST.get("days") or 7), 1), 30)
    except (TypeError, ValueError):
        days = 7
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
