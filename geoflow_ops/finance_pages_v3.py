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
from . import finance_pages_v4 as v4
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


def _org_units(alias):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text,name,COALESCE(type,''),COALESCE(biz_no,'') FROM ops.my_org_units ORDER BY name")
        return [{"id": r[0], "name": r[1], "type": r[2], "biz_no": r[3]} for r in cur.fetchall()]


def settings_page(request):
    alias = require_tenant_context(request)
    org_units = _org_units(alias)
    selected_org = v4._selected_org(request, org_units)
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT a.id::text,a.bank_name,a.account_name,COALESCE(a.account_number,''),a.currency,a.active,
                   a.my_org_unit_id::text,COALESCE(o.name,''),COALESCE(a.memo,'')
              FROM fin.accounts a
              LEFT JOIN ops.my_org_units o ON o.id=a.my_org_unit_id
             WHERE a.is_deleted=false
               AND (%s='' OR a.my_org_unit_id::text=%s)
             ORDER BY a.active DESC,o.name,a.bank_name,a.account_name
            """,
            [selected_org, selected_org],
        )
        accounts = [
            {"id": r[0], "bank_name": r[1], "account_name": r[2], "account_number": r[3], "currency": r[4],
             "active": bool(r[5]), "org_unit_id": r[6] or "", "org_unit_name": r[7], "memo": r[8]}
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT c.id::text,c.my_org_unit_id::text,COALESCE(o.name,''),c.issuer,c.card_name,
                   COALESCE(c.masked_number,''),c.active,COALESCE(c.memo,'')
              FROM fin.cards c
              LEFT JOIN ops.my_org_units o ON o.id=c.my_org_unit_id
             WHERE c.is_deleted=false
               AND (%s='' OR c.my_org_unit_id::text=%s)
             ORDER BY c.active DESC,o.name,c.issuer,c.card_name
            """,
            [selected_org, selected_org],
        )
        cards = [
            {"id": r[0], "org_unit_id": r[1], "org_unit_name": r[2], "issuer": r[3], "card_name": r[4],
             "masked_number": r[5], "active": bool(r[6]), "memo": r[7]}
            for r in cur.fetchall()
        ]
    return render(request, "geoflow_ops/finance/finance_accounts_cards.html", {
        "org_units": org_units,
        "finance_selected_org": selected_org,
        "accounts": accounts,
        "cards": cards,
        "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
    })


def _trash_rows(alias, selected_org=""):
    rows = []
    with connections[alias].cursor() as cur:
        queries = [
            ("claim", "청구", "SELECT id::text,claim_date,title,total_amount,deleted_at,my_org_unit_id::text FROM fin.claims WHERE is_deleted=true"),
            ("invoice", "세금계산서", "SELECT id::text,COALESCE(issued_date,written_date),COALESCE(source_partner_name,approval_no,'세금계산서'),total_amount,deleted_at,my_org_unit_id::text FROM fin.tax_invoices WHERE is_deleted=true"),
            ("payment", "지급", "SELECT id::text,request_date,title,amount,deleted_at,my_org_unit_id::text FROM fin.payment_requests WHERE is_deleted=true"),
            ("transaction", "입출금", "SELECT id::text,transaction_date,COALESCE(description,'입출금'),amount,deleted_at,my_org_unit_id::text FROM fin.transactions WHERE is_deleted=true"),
            ("account", "계좌", "SELECT id::text,NULL::date,bank_name||' '||account_name,0,deleted_at,my_org_unit_id::text FROM fin.accounts WHERE is_deleted=true"),
            ("card", "카드", "SELECT id::text,NULL::date,issuer||' '||card_name,0,deleted_at,my_org_unit_id::text FROM fin.cards WHERE is_deleted=true"),
        ]
        for kind, label, sql in queries:
            cur.execute(sql)
            for r in cur.fetchall():
                org_id = r[5] or ""
                if selected_org and org_id != selected_org:
                    continue
                rows.append({"kind": kind, "kind_label": label, "id": r[0], "date": r[1], "title": r[2] or label,
                             "amount": r[3], "deleted_at": r[4], "org_unit_id": org_id})
    rows.sort(key=lambda item: item["deleted_at"] or item["date"] or "", reverse=True)
    return rows[:1000]


def trash_page(request):
    alias = require_tenant_context(request)
    org_units = _org_units(alias)
    selected_org = v4._selected_org(request, org_units)
    return render(request, "geoflow_ops/finance/finance_trash.html", {
        "trash": _trash_rows(alias, selected_org),
        "org_units": org_units,
        "finance_selected_org": selected_org,
        "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
        "can_hard_delete": gf_has_role(request, "tenant_admin"),
    })


def contract_defaults(request, contract_id):
    alias = require_tenant_context(request)
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT c.client_id::text, COALESCE(p.name,''), c.org_unit_id::text, COALESCE(o.name,'')
              FROM ctr.contracts c
              LEFT JOIN ctr.partners p ON p.id=c.client_id
              LEFT JOIN ops.my_org_units o ON o.id=c.org_unit_id
             WHERE c.id=%s LIMIT 1
            """,
            [str(contract_id)],
        )
        row = cur.fetchone()
    if not row:
        return JsonResponse({"error": "계약을 찾을 수 없습니다."}, status=404)
    return JsonResponse({"contract_id": str(contract_id), "client_id": row[0] or "", "client_name": row[1] or "",
                         "org_unit_id": row[2] or "", "org_unit_name": row[3] or ""})


def account_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id")); org_id = _uuid(request.POST.get("my_org_unit_id"))
    bank_name = str(request.POST.get("bank_name") or "").strip(); account_name = str(request.POST.get("account_name") or "").strip()
    account_number = str(request.POST.get("account_number") or "").strip() or None
    currency = str(request.POST.get("currency") or "KRW").strip() or "KRW"; memo = str(request.POST.get("memo") or "").strip() or None
    if not _valid_org(alias, org_id) or not bank_name or not account_name:
        return HttpResponseBadRequest("귀속회사, 은행, 계좌명을 확인하세요.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute("""UPDATE fin.accounts SET my_org_unit_id=%s,bank_name=%s,account_name=%s,account_number=%s,currency=%s,memo=%s,active=true,updated_at=now() WHERE id=%s AND is_deleted=false""",
                            [str(org_id), bank_name, account_name, account_number, currency, memo, str(record_id)])
                if not cur.rowcount: return HttpResponseBadRequest("수정할 계좌를 찾을 수 없습니다.")
                messages.success(request, "계좌를 수정했습니다.")
            else:
                cur.execute("INSERT INTO fin.accounts(my_org_unit_id,bank_name,account_name,account_number,currency,memo) VALUES(%s,%s,%s,%s,%s,%s)",
                            [str(org_id), bank_name, account_name, account_number, currency, memo])
                messages.success(request, "계좌를 등록했습니다.")
    return redirect("tenant:finance_settings")


def card_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id")); org_id = _uuid(request.POST.get("my_org_unit_id"))
    issuer = str(request.POST.get("issuer") or "").strip(); card_name = str(request.POST.get("card_name") or "").strip()
    masked_number = str(request.POST.get("masked_number") or "").strip() or None; memo = str(request.POST.get("memo") or "").strip() or None
    if not _valid_org(alias, org_id) or not issuer or not card_name:
        return HttpResponseBadRequest("귀속회사, 카드사, 카드명을 확인하세요.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute("UPDATE fin.cards SET my_org_unit_id=%s,issuer=%s,card_name=%s,masked_number=%s,memo=%s,active=true,updated_at=now() WHERE id=%s AND is_deleted=false",
                            [str(org_id), issuer, card_name, masked_number, memo, str(record_id)])
                if not cur.rowcount: return HttpResponseBadRequest("수정할 카드를 찾을 수 없습니다.")
                messages.success(request, "카드를 수정했습니다.")
            else:
                cur.execute("INSERT INTO fin.cards(my_org_unit_id,issuer,card_name,masked_number,memo) VALUES(%s,%s,%s,%s,%s)",
                            [str(org_id), issuer, card_name, masked_number, memo])
                messages.success(request, "카드를 등록했습니다.")
    return redirect("tenant:finance_settings")


def account_delete(request, record_id):
    alias = require_tenant_context(request)
    with connections[alias].cursor() as cur:
        cur.execute("UPDATE fin.accounts SET active=false,is_deleted=true,deleted_at=now(),deleted_by=%s,updated_at=now() WHERE id=%s AND is_deleted=false",
                    [v2.legacy._actor(request), str(record_id)])
    messages.success(request, "계좌를 삭제함으로 이동했습니다.")
    return redirect("tenant:finance_settings")


def card_delete(request, record_id):
    alias = require_tenant_context(request)
    with connections[alias].cursor() as cur:
        cur.execute("UPDATE fin.cards SET active=false,is_deleted=true,deleted_at=now(),deleted_by=%s,updated_at=now() WHERE id=%s AND is_deleted=false",
                    [v2.legacy._actor(request), str(record_id)])
    messages.success(request, "카드를 삭제함으로 이동했습니다.")
    return redirect("tenant:finance_settings")


def _redirect_back(request, response, fallback_name):
    target = str(request.POST.get("next") or request.META.get("HTTP_REFERER") or "").strip()
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    if response is not None:
        return response
    return redirect(reverse(fallback_name))


def record_soft_delete(request, kind, record_id):
    if kind == "account": return account_delete(request, record_id)
    if kind == "card": return card_delete(request, record_id)
    response = legacy_views.record_soft_delete(request, kind, record_id)
    return _redirect_back(request, response, "tenant:finance_page")


def record_restore(request, kind, record_id):
    alias = require_tenant_context(request)
    if kind in {"account", "card"}:
        table = "fin.accounts" if kind == "account" else "fin.cards"
        with connections[alias].cursor() as cur:
            cur.execute(f"UPDATE {table} SET is_deleted=false,active=true,deleted_at=NULL,deleted_by=NULL,updated_at=now() WHERE id=%s AND is_deleted=true", [str(record_id)])
        messages.success(request, "복원했습니다.")
        return _redirect_back(request, None, "tenant:finance_trash")
    response = legacy_views.record_restore(request, kind, record_id)
    return _redirect_back(request, response, "tenant:finance_trash")


def record_hard_delete(request, kind, record_id):
    alias = require_tenant_context(request)
    if kind == "account":
        with connections[alias].cursor() as cur:
            cur.execute("SELECT count(*) FROM fin.transactions WHERE account_id=%s", [str(record_id)])
            linked = int(cur.fetchone()[0] or 0)
            if linked:
                messages.error(request, f"연결된 입출금 {linked}건이 있어 계좌를 완전삭제할 수 없습니다.")
                return _redirect_back(request, None, "tenant:finance_trash")
            cur.execute("DELETE FROM fin.accounts WHERE id=%s AND is_deleted=true", [str(record_id)])
        messages.success(request, "계좌를 완전삭제했습니다.")
        return _redirect_back(request, None, "tenant:finance_trash")
    if kind == "card":
        with connections[alias].cursor() as cur:
            cur.execute("DELETE FROM fin.cards WHERE id=%s AND is_deleted=true", [str(record_id)])
        messages.success(request, "카드를 완전삭제했습니다.")
        return _redirect_back(request, None, "tenant:finance_trash")
    response = legacy_views.record_hard_delete(request, kind, record_id)
    return _redirect_back(request, response, "tenant:finance_trash")
