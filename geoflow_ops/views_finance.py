from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from django.contrib import messages
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render

from control.gf_authz.permissions import gf_has_perm, gf_has_role
from .services.entity_access import require_tenant_context


RECORD_TABLES = {
    "claim": "fin.claims",
    "invoice": "fin.tax_invoices",
    "payment": "fin.payment_requests",
    "transaction": "fin.transactions",
}


def _uuid(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _money(value):
    try:
        return Decimal(str(value or "0").replace(",", "").strip()).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _actor(request):
    user = getattr(request, "user", None)
    return str(getattr(user, "email", None) or getattr(user, "username", None) or getattr(user, "pk", ""))[:255]


def _setting_options(alias: str, field_ref: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT v.code, v.name, COALESCE(v.system_key,'')
              FROM ops.settings_nodes c
              JOIN ops.settings_nodes v ON v.parent_id=c.id
             WHERE c.field_ref=%s AND v.node_type='value' AND v.active=true
             ORDER BY v.ord, v.name
            """,
            [field_ref],
        )
        return [{"code": r[0], "name": r[1], "system_key": r[2]} for r in cur.fetchall()]


def _semantic_code(alias: str, system_key: str, fallback: str):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT code FROM ops.settings_nodes WHERE system_key=%s AND active=true LIMIT 1", [system_key])
        row = cur.fetchone()
    return row[0] if row else fallback


def _default_project_id(alias: str, contract_id):
    """Keep project linkage hidden while current contracts are effectively 1:1.

    If a contract later owns multiple real projects, Finance deliberately leaves
    project_id empty rather than guessing which project the money belongs to.
    """
    if not contract_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text FROM prj.projects WHERE contract_id=%s ORDER BY id LIMIT 2", [str(contract_id)])
        rows = cur.fetchall()
    return rows[0][0] if len(rows) == 1 else None


def _contract_client_id(alias: str, contract_id):
    if not contract_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute("SELECT client_id::text FROM ctr.contracts WHERE id=%s LIMIT 1", [str(contract_id)])
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _masters(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT c.id::text, COALESCE(c.code,''), c.name,
                   c.client_id::text, COALESCE(p.name,''), c.start_date, c.end_date
              FROM ctr.contracts c
              LEFT JOIN ctr.partners p ON p.id=c.client_id
             ORDER BY COALESCE(c.start_date,c.end_date) DESC NULLS LAST, c.code DESC, c.name
            """
        )
        contracts = [
            {
                "id": r[0], "code": r[1], "name": r[2], "client_id": r[3] or "",
                "client_name": r[4] or "", "start_date": r[5], "end_date": r[6],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT id::text, name, COALESCE(biz_no,''), COALESCE(type,'')
              FROM ctr.partners
             WHERE COALESCE(status,'') NOT IN ('inactive','deleted')
             ORDER BY name
            """
        )
        partners = [{"id": r[0], "name": r[1], "biz_no": r[2], "type": r[3]} for r in cur.fetchall()]

        cur.execute(
            """
            SELECT id::text, bank_name, account_name, COALESCE(account_number,''), currency, active
              FROM fin.accounts
             ORDER BY active DESC, bank_name, account_name
            """
        )
        accounts = [
            {"id": r[0], "bank_name": r[1], "account_name": r[2], "account_number": r[3], "currency": r[4], "active": bool(r[5])}
            for r in cur.fetchall()
        ]
    return contracts, partners, accounts


def _dashboard(alias: str):
    in_code = _semantic_code(alias, "finance.value.transaction_type.in", "in")
    out_code = _semantic_code(alias, "finance.value.transaction_type.out", "out")
    cancelled_claim = _semantic_code(alias, "finance.value.claim_status.cancelled", "cancelled")
    cancelled_payment = _semantic_code(alias, "finance.value.payment_status.cancelled", "cancelled")
    with connections[alias].cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM ctr.contracts")
        contract_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM fin.claims WHERE is_deleted=false AND COALESCE(status,'') <> %s", [cancelled_claim])
        claim_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE is_deleted=false AND transaction_type=%s", [in_code])
        received_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.payment_requests WHERE is_deleted=false AND COALESCE(status,'') <> %s", [cancelled_payment])
        payment_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE is_deleted=false AND transaction_type=%s", [out_code])
        paid_total = cur.fetchone()[0] or 0
    return {
        "contract_total": contract_total,
        "claim_total": claim_total,
        "received_total": received_total,
        "unclaimed_total": max(Decimal(contract_total or 0) - Decimal(claim_total or 0), Decimal("0")),
        "receivable_total": max(Decimal(claim_total or 0) - Decimal(received_total or 0), Decimal("0")),
        "payment_total": payment_total,
        "paid_total": paid_total,
        "payable_total": max(Decimal(payment_total or 0) - Decimal(paid_total or 0), Decimal("0")),
    }


def _rows(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT c.id::text,c.claim_date,c.due_date,c.expected_receipt_date,c.title,
                   c.partner_id::text,COALESCE(p.name,''),c.contract_id::text,COALESCE(k.name,''),
                   c.supply_amount,c.vat_amount,c.total_amount,COALESCE(c.claim_type,''),COALESCE(c.status,''),COALESCE(c.memo,''),
                   COALESCE((SELECT SUM(t.amount) FROM fin.transactions t WHERE t.claim_id=c.id AND t.is_deleted=false),0)
              FROM fin.claims c
              LEFT JOIN ctr.partners p ON p.id=c.partner_id
              LEFT JOIN ctr.contracts k ON k.id=c.contract_id
             WHERE c.is_deleted=false
             ORDER BY c.claim_date DESC NULLS LAST,c.created_at DESC
             LIMIT 500
            """
        )
        claims = []
        for r in cur.fetchall():
            claims.append({
                "id": r[0], "date": r[1], "due_date": r[2], "expected_receipt_date": r[3], "title": r[4],
                "partner_id": r[5] or "", "partner": r[6], "contract_id": r[7] or "", "contract": r[8],
                "supply": r[9], "vat": r[10], "total": r[11], "claim_type": r[12], "status": r[13], "memo": r[14],
                "received": r[15], "balance": Decimal(r[11] or 0) - Decimal(r[15] or 0),
            })

        cur.execute(
            """
            SELECT i.id::text,i.written_date,i.issued_date,COALESCE(i.invoice_type,''),
                   i.partner_id::text,COALESCE(p.name,''),i.contract_id::text,COALESCE(k.name,''),
                   i.claim_id::text,i.payment_request_id::text,i.supply_amount,i.vat_amount,i.total_amount,
                   COALESCE(i.approval_no,''),COALESCE(i.status,''),COALESCE(i.memo,''),COALESCE(i.source_type,'manual'),
                   COALESCE(i.source_partner_name,'')
              FROM fin.tax_invoices i
              LEFT JOIN ctr.partners p ON p.id=i.partner_id
              LEFT JOIN ctr.contracts k ON k.id=i.contract_id
             WHERE i.is_deleted=false
             ORDER BY COALESCE(i.issued_date,i.written_date) DESC NULLS LAST,i.created_at DESC
             LIMIT 500
            """
        )
        invoices = [
            {
                "id": r[0], "written_date": r[1], "issued_date": r[2], "type": r[3],
                "partner_id": r[4] or "", "partner": r[5] or r[17], "contract_id": r[6] or "", "contract": r[7],
                "claim_id": r[8] or "", "payment_request_id": r[9] or "", "supply": r[10], "vat": r[11], "total": r[12],
                "approval_no": r[13], "status": r[14], "memo": r[15], "source_type": r[16], "source_partner_name": r[17],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT q.id::text,q.request_date,q.due_date,q.title,q.partner_id::text,COALESCE(p.name,''),
                   q.contract_id::text,COALESCE(k.name,''),q.amount,COALESCE(q.category_code,''),COALESCE(q.status,''),COALESCE(q.memo,''),
                   COALESCE((SELECT SUM(t.amount) FROM fin.transactions t WHERE t.payment_request_id=q.id AND t.is_deleted=false),0)
              FROM fin.payment_requests q
              LEFT JOIN ctr.partners p ON p.id=q.partner_id
              LEFT JOIN ctr.contracts k ON k.id=q.contract_id
             WHERE q.is_deleted=false
             ORDER BY q.request_date DESC NULLS LAST,q.created_at DESC
             LIMIT 500
            """
        )
        payments = []
        for r in cur.fetchall():
            payments.append({
                "id": r[0], "date": r[1], "due_date": r[2], "title": r[3], "partner_id": r[4] or "", "partner": r[5],
                "contract_id": r[6] or "", "contract": r[7], "amount": r[8], "category": r[9], "status": r[10], "memo": r[11],
                "paid": r[12], "balance": Decimal(r[8] or 0) - Decimal(r[12] or 0),
            })

        cur.execute(
            """
            SELECT t.id::text,t.transaction_date,COALESCE(t.transaction_type,''),t.amount,t.partner_id::text,
                   COALESCE(p.name,''),t.account_id::text,COALESCE(a.bank_name||' '||a.account_name,''),COALESCE(t.description,''),
                   t.contract_id::text,COALESCE(k.name,''),t.claim_id::text,t.payment_request_id::text,
                   COALESCE(t.category_code,''),COALESCE(t.evidence_type,''),COALESCE(t.memo,''),COALESCE(t.source_type,'manual'),COALESCE(t.source_partner_name,'')
              FROM fin.transactions t
              LEFT JOIN ctr.partners p ON p.id=t.partner_id
              LEFT JOIN fin.accounts a ON a.id=t.account_id
              LEFT JOIN ctr.contracts k ON k.id=t.contract_id
             WHERE t.is_deleted=false
             ORDER BY t.transaction_date DESC,t.created_at DESC
             LIMIT 800
            """
        )
        transactions = [
            {
                "id": r[0], "date": r[1], "type": r[2], "amount": r[3], "partner_id": r[4] or "", "partner": r[5] or r[17],
                "account_id": r[6] or "", "account": r[7], "description": r[8], "contract_id": r[9] or "", "contract": r[10],
                "claim_id": r[11] or "", "payment_request_id": r[12] or "", "category": r[13], "evidence": r[14], "memo": r[15],
                "source_type": r[16], "source_partner_name": r[17],
            }
            for r in cur.fetchall()
        ]
    return claims, invoices, payments, transactions


def _trash(alias: str):
    rows = []
    with connections[alias].cursor() as cur:
        queries = [
            ("claim", "청구", "SELECT id::text,claim_date,title,total_amount,deleted_at FROM fin.claims WHERE is_deleted=true ORDER BY deleted_at DESC"),
            ("invoice", "세금계산서", "SELECT id::text,COALESCE(issued_date,written_date),COALESCE(source_partner_name,approval_no,'세금계산서'),total_amount,deleted_at FROM fin.tax_invoices WHERE is_deleted=true ORDER BY deleted_at DESC"),
            ("payment", "지급", "SELECT id::text,request_date,title,amount,deleted_at FROM fin.payment_requests WHERE is_deleted=true ORDER BY deleted_at DESC"),
            ("transaction", "입출금", "SELECT id::text,transaction_date,COALESCE(description,'입출금'),amount,deleted_at FROM fin.transactions WHERE is_deleted=true ORDER BY deleted_at DESC"),
        ]
        for kind, label, sql in queries:
            cur.execute(sql)
            for r in cur.fetchall():
                rows.append({"kind": kind, "kind_label": label, "id": r[0], "date": r[1], "title": r[2] or label, "amount": r[3], "deleted_at": r[4]})
    rows.sort(key=lambda x: x["deleted_at"] or x["date"] or "", reverse=True)
    return rows[:500]


def finance_page(request):
    alias = require_tenant_context(request)
    contracts, partners, accounts = _masters(alias)
    claims, invoices, payments, transactions = _rows(alias)
    refs = {
        key: _setting_options(alias, key)
        for key in [
            "finance.claim_type", "finance.claim_status", "finance.invoice_type", "finance.invoice_status",
            "finance.payment_status", "finance.transaction_type", "finance.transaction_category", "finance.evidence_type",
        ]
    }
    return render(
        request,
        "geoflow_ops/finance/finance_page.html",
        {
            "finance": _dashboard(alias), "contracts": contracts, "partners": partners, "accounts": accounts,
            "claims": claims, "invoices": invoices, "payments": payments, "transactions": transactions,
            "trash": _trash(alias), "refs": refs,
            "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
            "can_hard_delete": gf_has_role(request, "tenant_admin"),
        },
    )


def _exists(alias, table, value):
    if not value:
        return True
    with connections[alias].cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s", [str(value)])
        return bool(cur.fetchone())


def _record_for_update(alias, table, record_id):
    if not record_id:
        return False
    with connections[alias].cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s AND is_deleted=false", [str(record_id)])
        return bool(cur.fetchone())


def claim_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    contract_id = _uuid(request.POST.get("contract_id"))
    partner_id = _uuid(request.POST.get("partner_id"))
    if not contract_id or not _exists(alias, "ctr.contracts", contract_id):
        return HttpResponseBadRequest("계약을 확인하세요.")
    if not partner_id:
        partner_id = _uuid(_contract_client_id(alias, contract_id))
    project_id = _default_project_id(alias, contract_id)
    supply = _money(request.POST.get("supply_amount"))
    vat = _money(request.POST.get("vat_amount"))
    total = supply + vat
    params = [
        str(contract_id), project_id, str(partner_id) if partner_id else None,
        request.POST.get("claim_date", ""), request.POST.get("due_date", ""), request.POST.get("expected_receipt_date", ""),
        request.POST.get("title") or "청구", request.POST.get("claim_type") or None, supply, vat, total,
        request.POST.get("status") or None, request.POST.get("memo") or None,
    ]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                if not _record_for_update(alias, "fin.claims", record_id):
                    return HttpResponseBadRequest("수정할 청구 건을 찾을 수 없습니다.")
                cur.execute(
                    """
                    UPDATE fin.claims
                       SET contract_id=%s,project_id=%s,partner_id=%s,claim_date=NULLIF(%s,'')::date,due_date=NULLIF(%s,'')::date,
                           expected_receipt_date=NULLIF(%s,'')::date,title=%s,claim_type=%s,supply_amount=%s,vat_amount=%s,total_amount=%s,
                           status=%s,memo=%s,updated_at=now()
                     WHERE id=%s
                    """,
                    params + [str(record_id)],
                )
                messages.success(request, "청구 건을 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO fin.claims(contract_id,project_id,partner_id,claim_date,due_date,expected_receipt_date,title,claim_type,supply_amount,vat_amount,total_amount,status,memo,created_by)
                    VALUES(%s,%s,%s,NULLIF(%s,'')::date,NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    params + [_actor(request)],
                )
                messages.success(request, "청구 건을 등록했습니다.")
    return redirect("tenant:finance_page")


def invoice_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    contract_id = _uuid(request.POST.get("contract_id"))
    if not contract_id or not _exists(alias, "ctr.contracts", contract_id):
        return HttpResponseBadRequest("계약을 확인하세요.")
    partner_id = _uuid(request.POST.get("partner_id")) or _uuid(_contract_client_id(alias, contract_id))
    project_id = _default_project_id(alias, contract_id)
    supply = _money(request.POST.get("supply_amount"))
    vat = _money(request.POST.get("vat_amount"))
    total = supply + vat
    invoice_type = request.POST.get("invoice_type") or ""
    claim_id = _uuid(request.POST.get("claim_id"))
    payment_id = _uuid(request.POST.get("payment_request_id"))
    if claim_id and payment_id:
        return HttpResponseBadRequest("관련 청구와 지급건은 동시에 지정할 수 없습니다.")
    params = [
        request.POST.get("written_date", ""), request.POST.get("issued_date", ""), invoice_type,
        str(partner_id) if partner_id else None, str(contract_id), project_id, str(claim_id) if claim_id else None,
        str(payment_id) if payment_id else None, supply, vat, total, request.POST.get("approval_no") or None,
        request.POST.get("status") or None, request.POST.get("memo") or None,
    ]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                if not _record_for_update(alias, "fin.tax_invoices", record_id):
                    return HttpResponseBadRequest("수정할 세금계산서를 찾을 수 없습니다.")
                cur.execute(
                    """
                    UPDATE fin.tax_invoices
                       SET written_date=NULLIF(%s,'')::date,issued_date=NULLIF(%s,'')::date,invoice_type=%s,partner_id=%s,contract_id=%s,
                           project_id=%s,claim_id=%s,payment_request_id=%s,supply_amount=%s,vat_amount=%s,total_amount=%s,approval_no=%s,status=%s,memo=%s,updated_at=now()
                     WHERE id=%s
                    """,
                    params + [str(record_id)],
                )
                messages.success(request, "세금계산서를 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO fin.tax_invoices(written_date,issued_date,invoice_type,partner_id,contract_id,project_id,claim_id,payment_request_id,supply_amount,vat_amount,total_amount,approval_no,status,memo,created_by,source_type)
                    VALUES(NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    params + [_actor(request)],
                )
                messages.success(request, "세금계산서를 등록했습니다.")
    return redirect("tenant:finance_page")


def payment_request_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    contract_id = _uuid(request.POST.get("contract_id"))
    partner_id = _uuid(request.POST.get("partner_id"))
    if contract_id and not partner_id:
        partner_id = _uuid(_contract_client_id(alias, contract_id))
    project_id = _default_project_id(alias, contract_id)
    amount = _money(request.POST.get("amount"))
    params = [
        str(contract_id) if contract_id else None, project_id, str(partner_id) if partner_id else None,
        request.POST.get("request_date", ""), request.POST.get("due_date", ""), request.POST.get("title") or "지급",
        amount, request.POST.get("category_code") or None, request.POST.get("status") or None, request.POST.get("memo") or None,
    ]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                if not _record_for_update(alias, "fin.payment_requests", record_id):
                    return HttpResponseBadRequest("수정할 지급 건을 찾을 수 없습니다.")
                cur.execute(
                    """
                    UPDATE fin.payment_requests
                       SET contract_id=%s,project_id=%s,partner_id=%s,request_date=NULLIF(%s,'')::date,due_date=NULLIF(%s,'')::date,
                           title=%s,amount=%s,category_code=%s,status=%s,memo=%s,updated_at=now()
                     WHERE id=%s
                    """,
                    params + [str(record_id)],
                )
                messages.success(request, "지급 건을 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO fin.payment_requests(contract_id,project_id,partner_id,request_date,due_date,title,amount,category_code,status,memo,created_by)
                    VALUES(%s,%s,%s,NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s)
                    """,
                    params + [_actor(request)],
                )
                messages.success(request, "지급 건을 등록했습니다.")
    return redirect("tenant:finance_page")


def transaction_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    contract_id = _uuid(request.POST.get("contract_id"))
    partner_id = _uuid(request.POST.get("partner_id"))
    if contract_id and not partner_id:
        partner_id = _uuid(_contract_client_id(alias, contract_id))
    project_id = _default_project_id(alias, contract_id)
    amount = _money(request.POST.get("amount"))
    claim_id = _uuid(request.POST.get("claim_id"))
    payment_id = _uuid(request.POST.get("payment_request_id"))
    if claim_id and payment_id:
        return HttpResponseBadRequest("관련 청구와 지급건은 동시에 지정할 수 없습니다.")
    params = [
        request.POST.get("transaction_date", ""), request.POST.get("transaction_type") or "", amount,
        str(partner_id) if partner_id else None, str(_uuid(request.POST.get("account_id"))) if _uuid(request.POST.get("account_id")) else None,
        request.POST.get("description") or None, str(contract_id) if contract_id else None, project_id,
        str(claim_id) if claim_id else None, str(payment_id) if payment_id else None,
        request.POST.get("category_code") or None, request.POST.get("evidence_type") or None, request.POST.get("memo") or None,
    ]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                if not _record_for_update(alias, "fin.transactions", record_id):
                    return HttpResponseBadRequest("수정할 입출금 내역을 찾을 수 없습니다.")
                cur.execute(
                    """
                    UPDATE fin.transactions
                       SET transaction_date=NULLIF(%s,'')::date,transaction_type=%s,amount=%s,partner_id=%s,account_id=%s,description=%s,
                           contract_id=%s,project_id=%s,claim_id=%s,payment_request_id=%s,category_code=%s,evidence_type=%s,memo=%s,updated_at=now()
                     WHERE id=%s
                    """,
                    params + [str(record_id)],
                )
                messages.success(request, "입출금 내역을 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO fin.transactions(transaction_date,transaction_type,amount,partner_id,account_id,description,contract_id,project_id,claim_id,payment_request_id,category_code,evidence_type,memo,created_by,source_type)
                    VALUES(NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                    """,
                    params + [_actor(request)],
                )
                messages.success(request, "입출금 내역을 등록했습니다.")
    return redirect("tenant:finance_page")


def account_save(request):
    alias = require_tenant_context(request)
    if not (request.POST.get("bank_name") and request.POST.get("account_name")):
        return HttpResponseBadRequest("은행과 계좌명을 확인하세요.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                "INSERT INTO fin.accounts(bank_name,account_name,account_number,currency,memo) VALUES(%s,%s,%s,%s,%s)",
                [request.POST.get("bank_name"), request.POST.get("account_name"), request.POST.get("account_number") or None, request.POST.get("currency") or "KRW", request.POST.get("memo") or None],
            )
    messages.success(request, "계좌를 등록했습니다.")
    return redirect("tenant:finance_page")


def record_soft_delete(request, kind, record_id):
    alias = require_tenant_context(request)
    table = RECORD_TABLES.get(kind)
    if not table:
        return HttpResponseBadRequest("삭제 대상을 확인하세요.")
    with connections[alias].cursor() as cur:
        cur.execute(
            f"UPDATE {table} SET is_deleted=true,deleted_at=now(),deleted_by=%s,updated_at=now() WHERE id=%s AND is_deleted=false",
            [_actor(request), str(record_id)],
        )
        changed = cur.rowcount
    if changed:
        messages.success(request, "삭제했습니다. 삭제함에서 복원할 수 있습니다.")
    return redirect("tenant:finance_page")


def record_restore(request, kind, record_id):
    alias = require_tenant_context(request)
    table = RECORD_TABLES.get(kind)
    if not table:
        return HttpResponseBadRequest("복원 대상을 확인하세요.")
    with connections[alias].cursor() as cur:
        cur.execute(
            f"UPDATE {table} SET is_deleted=false,deleted_at=NULL,deleted_by=NULL,updated_at=now() WHERE id=%s AND is_deleted=true",
            [str(record_id)],
        )
        changed = cur.rowcount
    if changed:
        messages.success(request, "Finance 항목을 복원했습니다.")
    return redirect("tenant:finance_page")


def record_hard_delete(request, kind, record_id):
    alias = require_tenant_context(request)
    table = RECORD_TABLES.get(kind)
    if not table:
        return HttpResponseBadRequest("완전 삭제 대상을 확인하세요.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if kind == "claim":
                cur.execute("UPDATE fin.tax_invoices SET claim_id=NULL WHERE claim_id=%s", [str(record_id)])
                cur.execute("UPDATE fin.transactions SET claim_id=NULL WHERE claim_id=%s", [str(record_id)])
            elif kind == "payment":
                cur.execute("UPDATE fin.tax_invoices SET payment_request_id=NULL WHERE payment_request_id=%s", [str(record_id)])
                cur.execute("UPDATE fin.transactions SET payment_request_id=NULL WHERE payment_request_id=%s", [str(record_id)])
            cur.execute(f"DELETE FROM {table} WHERE id=%s AND is_deleted=true", [str(record_id)])
            changed = cur.rowcount
    if changed:
        messages.success(request, "완전 삭제했습니다. 이 작업은 복원할 수 없습니다.")
    return redirect("tenant:finance_page")


def contract_finance_summary(request, contract_id):
    alias = require_tenant_context(request)
    in_code = _semantic_code(alias, "finance.value.transaction_type.in", "in")
    out_code = _semantic_code(alias, "finance.value.transaction_type.out", "out")
    with connections[alias].cursor() as cur:
        cur.execute("SELECT COALESCE(amount,0) FROM ctr.contracts WHERE id=%s", [str(contract_id)])
        row = cur.fetchone()
        if not row:
            return JsonResponse({"detail": "not found"}, status=404)
        amount = Decimal(row[0] or 0)
        cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM fin.claims WHERE contract_id=%s AND is_deleted=false", [str(contract_id)])
        claimed = Decimal(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE contract_id=%s AND transaction_type=%s AND is_deleted=false", [str(contract_id), in_code])
        received = Decimal(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.payment_requests WHERE contract_id=%s AND is_deleted=false", [str(contract_id)])
        payreq = Decimal(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE contract_id=%s AND transaction_type=%s AND is_deleted=false", [str(contract_id), out_code])
        paid = Decimal(cur.fetchone()[0] or 0)
    return JsonResponse({
        "contract_amount": amount, "claimed": claimed, "received": received,
        "unclaimed": max(amount - claimed, Decimal("0")), "receivable": max(claimed - received, Decimal("0")),
        "payment_requested": payreq, "paid": paid, "payable": max(payreq - paid, Decimal("0")),
    })
