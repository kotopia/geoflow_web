from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from control.gf_authz.permissions import gf_has_perm, gf_has_role

from . import finance_pages_v2 as v2
from . import views_finance as legacy_views
from .services.entity_access import require_tenant_context


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _valid_org(alias, org_id):
    if not org_id:
        return False
    with connections[alias].cursor() as cur:
        cur.execute("SELECT 1 FROM ops.my_org_units WHERE id=%s LIMIT 1", [str(org_id)])
        return bool(cur.fetchone())


def settings_page(request):
    alias = require_tenant_context(request)
    org_units, contracts, partners, accounts, cards = v2._master_data(alias)
    return render(
        request,
        "geoflow_ops/finance/finance_accounts_cards.html",
        {
            "org_units": org_units,
            "accounts": accounts,
            "cards": cards,
            "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
        },
    )


def trash_page(request):
    alias = require_tenant_context(request)
    return render(
        request,
        "geoflow_ops/finance/finance_trash.html",
        {
            "trash": legacy_views._trash(alias),
            "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
            "can_hard_delete": gf_has_role(request, "tenant_admin"),
        },
    )


def contract_defaults(request, contract_id):
    alias = require_tenant_context(request)
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT c.client_id::text, COALESCE(p.name,''), c.org_unit_id::text, COALESCE(o.name,'')
              FROM ctr.contracts c
              LEFT JOIN ctr.partners p ON p.id=c.client_id
              LEFT JOIN ops.my_org_units o ON o.id=c.org_unit_id
             WHERE c.id=%s
             LIMIT 1
            """,
            [str(contract_id)],
        )
        row = cur.fetchone()
    if not row:
        return JsonResponse({"error": "계약을 찾을 수 없습니다."}, status=404)
    return JsonResponse(
        {
            "contract_id": str(contract_id),
            "client_id": row[0] or "",
            "client_name": row[1] or "",
            "org_unit_id": row[2] or "",
            "org_unit_name": row[3] or "",
        }
    )


def account_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    org_id = _uuid(request.POST.get("my_org_unit_id"))
    bank_name = str(request.POST.get("bank_name") or "").strip()
    account_name = str(request.POST.get("account_name") or "").strip()
    account_number = str(request.POST.get("account_number") or "").strip() or None
    currency = str(request.POST.get("currency") or "KRW").strip() or "KRW"
    memo = str(request.POST.get("memo") or "").strip() or None
    if not _valid_org(alias, org_id) or not bank_name or not account_name:
        return HttpResponseBadRequest("귀속회사, 은행, 계좌명을 확인하세요.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute(
                    """
                    UPDATE fin.accounts
                       SET my_org_unit_id=%s,bank_name=%s,account_name=%s,account_number=%s,
                           currency=%s,memo=%s,active=true,updated_at=now()
                     WHERE id=%s
                    """,
                    [str(org_id), bank_name, account_name, account_number, currency, memo, str(record_id)],
                )
                if not cur.rowcount:
                    return HttpResponseBadRequest("수정할 계좌를 찾을 수 없습니다.")
                messages.success(request, "계좌를 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO fin.accounts(my_org_unit_id,bank_name,account_name,account_number,currency,memo)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    """,
                    [str(org_id), bank_name, account_name, account_number, currency, memo],
                )
                messages.success(request, "계좌를 등록했습니다.")
    return redirect("tenant:finance_settings")


def card_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    org_id = _uuid(request.POST.get("my_org_unit_id"))
    issuer = str(request.POST.get("issuer") or "").strip()
    card_name = str(request.POST.get("card_name") or "").strip()
    masked_number = str(request.POST.get("masked_number") or "").strip() or None
    memo = str(request.POST.get("memo") or "").strip() or None
    if not _valid_org(alias, org_id) or not issuer or not card_name:
        return HttpResponseBadRequest("귀속회사, 카드사, 카드명을 확인하세요.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute(
                    """
                    UPDATE fin.cards
                       SET my_org_unit_id=%s,issuer=%s,card_name=%s,masked_number=%s,
                           memo=%s,active=true,updated_at=now()
                     WHERE id=%s
                    """,
                    [str(org_id), issuer, card_name, masked_number, memo, str(record_id)],
                )
                if not cur.rowcount:
                    return HttpResponseBadRequest("수정할 카드를 찾을 수 없습니다.")
                messages.success(request, "카드를 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO fin.cards(my_org_unit_id,issuer,card_name,masked_number,memo)
                    VALUES(%s,%s,%s,%s,%s)
                    """,
                    [str(org_id), issuer, card_name, masked_number, memo],
                )
                messages.success(request, "카드를 등록했습니다.")
    return redirect("tenant:finance_settings")


def account_delete(request, record_id):
    alias = require_tenant_context(request)
    with connections[alias].cursor() as cur:
        cur.execute("UPDATE fin.accounts SET active=false,updated_at=now() WHERE id=%s AND active=true", [str(record_id)])
    messages.success(request, "계좌를 삭제했습니다. 과거 거래 연결은 유지됩니다.")
    return redirect("tenant:finance_settings")


def card_delete(request, record_id):
    alias = require_tenant_context(request)
    with connections[alias].cursor() as cur:
        cur.execute("UPDATE fin.cards SET active=false,updated_at=now() WHERE id=%s AND active=true", [str(record_id)])
    messages.success(request, "카드를 삭제했습니다. 과거 사용 이력 연결을 위한 레코드는 유지됩니다.")
    return redirect("tenant:finance_settings")


def _redirect_back(request, response, fallback_name):
    target = str(request.POST.get("next") or request.META.get("HTTP_REFERER") or "").strip()
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    if response is not None:
        return response
    return redirect(reverse(fallback_name))


def record_soft_delete(request, kind, record_id):
    response = legacy_views.record_soft_delete(request, kind, record_id)
    return _redirect_back(request, response, "tenant:finance_page")


def record_restore(request, kind, record_id):
    response = legacy_views.record_restore(request, kind, record_id)
    return _redirect_back(request, response, "tenant:finance_trash")


def record_hard_delete(request, kind, record_id):
    response = legacy_views.record_hard_delete(request, kind, record_id)
    return _redirect_back(request, response, "tenant:finance_trash")
