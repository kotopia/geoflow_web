from __future__ import annotations

import math
from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from . import repository, personal
from .client import G2BError
from .sync import sync_service_notices
from procurement.service import enabled as central_enabled
from procurement import tenant as central_repository
from procurement import preferences


def notice_list(request, alias: str, *, can_review: bool, can_manage: bool):
    history = central_enabled(alias) and request.GET.get("history") == "1"
    repo = central_repository if central_enabled(alias) and not history else repository
    query = str(request.GET.get("q") or "").strip()
    review_status = str(request.GET.get("status") or "").strip()
    include_all = history or str(request.GET.get("scope") or "") == "all"
    try:
        per_page = int(request.GET.get("per_page") or 15)
    except (TypeError, ValueError):
        per_page = 15
    per_page = 30 if per_page == 30 else 15
    try:
        page = max(int(request.GET.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    region = str(request.GET.get("region") or "all") if central_enabled(alias) and not history else "all"
    extra = {"region": region} if central_enabled(alias) and not history else ({"reviewed_only": True} if history else {})
    personal_view = request.GET.get('view', 'all')
    if personal_view not in {'all', 'saved', 'hidden'}:
        personal_view = 'all'
    origin = 'central' if central_enabled(alias) and not history else 'legacy'
    state = personal.rows(alias, personal.user_id(request), origin)
    include_closed = history or request.GET.get('closed') == '1'
    sort = 'new' if request.GET.get('sort') == 'new' else 'deadline'
    try:
        date_from = parse_date(request.GET.get('from', ''))
        date_to = parse_date(request.GET.get('to', ''))
    except ValueError:
        return HttpResponseBadRequest('조회 날짜를 확인하세요.')
    if date_from and date_to and date_from > date_to:
        return HttpResponseBadRequest('시작일은 종료일보다 늦을 수 없습니다.')
    apply_extra = request.GET.get('extra') == '1'
    include_excluded = request.GET.get('excluded') == '1'
    sources = [v for v in request.GET.getlist('source') if v in {'g2b', 'kepco'}]
    if central_enabled(alias) and not history:
        extra.update(apply_extra=apply_extra, include_excluded=include_excluded, sources=sources or None)
    extra.update(personal_state=state, personal_view=personal_view, include_closed=include_closed,
                 date_from=date_from, date_to=date_to, sort=sort)
    region_tabs = []
    if central_enabled(alias) and not history:
        filters = repository.load_filters(alias)
        tabs = [("all", "모든 지역" if include_all else "설정 지역·전국·확인 필요"), *[(r["id"], r["name"]) for r in filters.get("region", [])],
                ("nationwide", "전국"), ("unknown", "지역 확인 필요")]
        for value, label in tabs:
            params = request.GET.copy()
            params.pop("page", None)
            params["region"] = value
            region_tabs.append(dict(value=value, label=label, active=region == value, query=params.urlencode()))
    total_count = repo.count_notices(
        alias, query=query, review_status=review_status, include_all=include_all, **extra
    )
    total_pages = max(math.ceil(total_count / per_page), 1)
    page = min(page, total_pages)
    notices = repo.list_notices(
        alias,
        query=query,
        review_status=review_status,
        include_all=include_all,
        limit=per_page,
        offset=(page - 1) * per_page, **extra,
    )
    for notice in notices:
        notice['saved'] = state.get(str(notice['id']), {}).get('saved', False)
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
        "apply_extra": apply_extra, "include_excluded": include_excluded,
        "source_choices": [dict(value=v, label=l, selected=v in sources) for v,l in [('g2b','나라장터'),('kepco','한국전력')]],
        "active_filters": filters if central_enabled(alias) and not history else {},
        "notices": notices, "personal_view": personal_view, "include_closed": include_closed,
        "sort": sort, "date_from": date_from, "date_to": date_to,
        "return_to": request.get_full_path(),
        "undo_ids": request.session.pop('bid_hidden_undo:' + alias, []),
        "region_tabs": region_tabs,
        "region": region,
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
        "can_review": can_review and not history,
        "legacy_history": history,
        "can_manage": can_manage and not history,
        "latest_sync": repo.latest_sync(alias),
        "central_mode": central_enabled(alias),
        "review_choices": [
            ("unreviewed", "미검토"), ("reviewing", "검토 중"),
            ("interested", "관심"), ("considering", "참여 검토"), ("excluded", "참여 안 함"),
        ],
    })


def settings_page(request, alias: str):
    repo = central_repository if central_enabled(alias) else repository
    central = central_enabled(alias)
    selected = set(preferences.selected_ids(alias)) if central else set()
    rules = [dict(id=str(r.pk), name=r.name, source=r.source, source_label=r.get_source_display(), kind=r.get_kind_display(), active=r.active,
                  selected=str(r.pk) in selected) for r in preferences.choices(alias)] if central else []
    configured = repository.list_settings(alias)
    return render(request, "geoflow_ops/bids/settings.html", {
        "central_mode": central, "central_rules": rules,
        "settings": configured,
        "setting_groups": [dict(kind=kind, label=label, rows=configured.get(kind, []))
                           for kind, label in [('region', '참가가능지역'), ('agency', '발주·수요기관'),
                                               ('include', '결과 내 포함 키워드'), ('exclude', '제외 키워드')]
                           + ([] if central else [('industry', '업종·면허')])],
        "latest_sync": repo.latest_sync(alias),
    })


def filter_value_save(request, alias: str):
    try:
        if request.POST.get("action") == "selection":
            kind = request.POST.get('kind')
            if kind == 'industry' and central_enabled(alias):
                raise ValueError('업종은 중앙 수집조건에서 선택하세요.')
            repository.save_selection(alias, kind, request.POST.getlist('selected_ids'))
        elif central_enabled(alias) and request.POST.get("action") == "central_rules":
            preferences.save(alias, request.POST.getlist("rule_ids"))
        elif central_enabled(alias) and request.POST.get("kind") == "industry":
            raise ValueError("업종은 중앙 수집조건에서 선택하세요.")
        else:
            repository.save_filter_value(alias, request.POST)
        if not central_enabled(alias):
            repository.reevaluate_all(alias)
    except (ValueError, IntegrityError) as exc:
        return HttpResponseBadRequest(str(exc) if isinstance(exc, ValueError) else "같은 구분과 코드가 이미 등록되어 있습니다.")
    messages.success(request, "입찰 기준 항목을 저장했습니다.")
    return redirect("tenant:bid_settings")


def keyword_save(request, alias: str):
    try:
        if central_enabled(alias) and request.POST.get('rule_type') == 'collection':
            preferences.add_keyword(alias, request.POST.get('keyword'), request.POST.get('source') or "g2b")
        else:
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
        messages.info(request, "중앙 DB의 최신 저장 결과를 표시합니다. 공고 수집은 중앙에서 자동 진행합니다.")
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


def personal_save(request, alias):
    origin = 'central' if central_enabled(alias) else 'legacy'
    try:
        ids = personal.save(alias, personal.user_id(request), origin,
                            request.POST.getlist('notice_ids'), request.POST.get('action'))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if request.POST.get('action') == 'hide':
        request.session['bid_hidden_undo:' + alias] = ids
    target = request.POST.get('next', '')
    path = reverse('tenant:bid_notice_list')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()) or target.split('?')[0] != path:
        target = path
    return redirect(target)
