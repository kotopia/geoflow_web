from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.contrib import messages
from django.db import connections, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render

from control.gf_authz.permissions import gf_has_perm, gf_has_role
from . import views_finance as legacy
from .services.entity_access import require_tenant_context


SECTION_ROUTE = {
    "dashboard": "tenant:finance_page",
    "claims": "tenant:finance_claims",
    "invoices": "tenant:finance_invoices",
    "payments": "tenant:finance_payments",
    "ledger": "tenant:finance_ledger",
    "balance": "tenant:finance_balance",
    "settings": "tenant:finance_settings",
}


def _uuid(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _org_id_from_contract(alias, contract_id):
    if not contract_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute("SELECT org_unit_id::text FROM ctr.contracts WHERE id=%s LIMIT 1", [str(contract_id)])
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _client_id_from_contract(alias, contract_id):
    if not contract_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute("SELECT client_id::text FROM ctr.contracts WHERE id=%s LIMIT 1", [str(contract_id)])
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _org_id_from_account(alias, account_id):
    if not account_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute("SELECT my_org_unit_id::text FROM fin.accounts WHERE id=%s LIMIT 1", [str(account_id)])
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _valid_id(alias, table, value):
    if not value:
        return False
    with connections[alias].cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s LIMIT 1", [str(value)])
        return bool(cur.fetchone())


def _master_data(alias):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text,name,COALESCE(type,''),COALESCE(biz_no,''),COALESCE(label,'')
              FROM ops.my_org_units
             ORDER BY name
            """
        )
        org_units = [
            {"id": r[0], "name": r[1], "type": r[2], "biz_no": r[3], "label": r[4]}
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT c.id::text,COALESCE(c.code,''),c.name,c.client_id::text,COALESCE(p.name,''),
                   c.org_unit_id::text,COALESCE(o.name,''),c.start_date,c.end_date
              FROM ctr.contracts c
              LEFT JOIN ctr.partners p ON p.id=c.client_id
              LEFT JOIN ops.my_org_units o ON o.id=c.org_unit_id
             ORDER BY COALESCE(c.start_date,c.end_date) DESC NULLS LAST,c.code DESC,c.name
            """
        )
        contracts = [
            {
                "id": r[0], "code": r[1], "name": r[2], "client_id": r[3] or "", "client_name": r[4],
                "org_unit_id": r[5] or "", "org_unit_name": r[6], "start_date": r[7], "end_date": r[8],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT id::text,name,COALESCE(biz_no,''),COALESCE(type,'')
              FROM ctr.partners
             WHERE COALESCE(status,'') NOT IN ('inactive','deleted')
             ORDER BY name
            """
        )
        partners = [{"id": r[0], "name": r[1], "biz_no": r[2], "type": r[3]} for r in cur.fetchall()]

        cur.execute(
            """
            SELECT a.id::text,a.bank_name,a.account_name,COALESCE(a.account_number,''),a.currency,a.active,
                   a.my_org_unit_id::text,COALESCE(o.name,'')
              FROM fin.accounts a
              LEFT JOIN ops.my_org_units o ON o.id=a.my_org_unit_id
             ORDER BY a.active DESC,o.name,a.bank_name,a.account_name
            """
        )
        accounts = [
            {"id": r[0], "bank_name": r[1], "account_name": r[2], "account_number": r[3], "currency": r[4],
             "active": bool(r[5]), "org_unit_id": r[6] or "", "org_unit_name": r[7]}
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT c.id::text,c.my_org_unit_id::text,COALESCE(o.name,''),c.issuer,c.card_name,
                   COALESCE(c.masked_number,''),c.active,COALESCE(c.memo,'')
              FROM fin.cards c
              LEFT JOIN ops.my_org_units o ON o.id=c.my_org_unit_id
             ORDER BY c.active DESC,o.name,c.issuer,c.card_name
            """
        )
        cards = [
            {"id": r[0], "org_unit_id": r[1], "org_unit_name": r[2], "issuer": r[3], "card_name": r[4],
             "masked_number": r[5], "active": bool(r[6]), "memo": r[7]}
            for r in cur.fetchall()
        ]
    return org_units, contracts, partners, accounts, cards


def _rows(alias):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT c.id::text,c.claim_date,c.due_date,c.expected_receipt_date,c.title,c.partner_id::text,COALESCE(p.name,''),
                   c.contract_id::text,COALESCE(k.name,''),c.my_org_unit_id::text,COALESCE(o.name,''),
                   c.supply_amount,c.vat_amount,c.total_amount,COALESCE(c.claim_type,''),COALESCE(c.status,''),COALESCE(c.memo,''),
                   COALESCE((SELECT SUM(t.amount) FROM fin.transactions t WHERE t.claim_id=c.id AND t.is_deleted=false),0)
              FROM fin.claims c
              LEFT JOIN ctr.partners p ON p.id=c.partner_id
              LEFT JOIN ctr.contracts k ON k.id=c.contract_id
              LEFT JOIN ops.my_org_units o ON o.id=c.my_org_unit_id
             WHERE c.is_deleted=false
             ORDER BY c.claim_date DESC NULLS LAST,c.created_at DESC
             LIMIT 1000
            """
        )
        claims = []
        for r in cur.fetchall():
            claims.append({
                "id": r[0], "date": r[1], "due_date": r[2], "expected_receipt_date": r[3], "title": r[4],
                "partner_id": r[5] or "", "partner": r[6], "contract_id": r[7] or "", "contract": r[8],
                "org_unit_id": r[9] or "", "org_unit": r[10], "supply": r[11], "vat": r[12], "total": r[13],
                "claim_type": r[14], "status": r[15], "memo": r[16], "received": r[17],
                "balance": Decimal(r[13] or 0) - Decimal(r[17] or 0),
            })

        cur.execute(
            """
            SELECT i.id::text,i.written_date,i.issued_date,COALESCE(i.invoice_type,''),i.partner_id::text,
                   COALESCE(p.name,i.source_partner_name,''),i.contract_id::text,COALESCE(k.name,''),
                   i.my_org_unit_id::text,COALESCE(o.name,''),i.claim_id::text,i.payment_request_id::text,
                   i.supply_amount,i.vat_amount,i.total_amount,COALESCE(i.approval_no,''),COALESCE(i.status,''),
                   COALESCE(i.memo,''),COALESCE(i.source_type,'manual'),i.attachment_id::text
              FROM fin.tax_invoices i
              LEFT JOIN ctr.partners p ON p.id=i.partner_id
              LEFT JOIN ctr.contracts k ON k.id=i.contract_id
              LEFT JOIN ops.my_org_units o ON o.id=i.my_org_unit_id
             WHERE i.is_deleted=false
             ORDER BY COALESCE(i.issued_date,i.written_date) DESC NULLS LAST,i.created_at DESC
             LIMIT 1000
            """
        )
        invoices = [
            {"id": r[0], "written_date": r[1], "issued_date": r[2], "type": r[3], "partner_id": r[4] or "",
             "partner": r[5], "contract_id": r[6] or "", "contract": r[7], "org_unit_id": r[8] or "", "org_unit": r[9],
             "claim_id": r[10] or "", "payment_request_id": r[11] or "", "supply": r[12], "vat": r[13], "total": r[14],
             "approval_no": r[15], "status": r[16], "memo": r[17], "source_type": r[18], "attachment_id": r[19] or ""}
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT q.id::text,q.request_date,q.due_date,q.title,q.partner_id::text,COALESCE(p.name,''),q.contract_id::text,
                   COALESCE(k.name,''),q.my_org_unit_id::text,COALESCE(o.name,''),q.amount,COALESCE(q.category_code,''),
                   COALESCE(q.status,''),COALESCE(q.memo,''),
                   COALESCE((SELECT SUM(t.amount) FROM fin.transactions t WHERE t.payment_request_id=q.id AND t.is_deleted=false),0)
              FROM fin.payment_requests q
              LEFT JOIN ctr.partners p ON p.id=q.partner_id
              LEFT JOIN ctr.contracts k ON k.id=q.contract_id
              LEFT JOIN ops.my_org_units o ON o.id=q.my_org_unit_id
             WHERE q.is_deleted=false
             ORDER BY q.request_date DESC NULLS LAST,q.created_at DESC
             LIMIT 1000
            """
        )
        payments = []
        for r in cur.fetchall():
            payments.append({
                "id": r[0], "date": r[1], "due_date": r[2], "title": r[3], "partner_id": r[4] or "", "partner": r[5],
                "contract_id": r[6] or "", "contract": r[7], "org_unit_id": r[8] or "", "org_unit": r[9],
                "amount": r[10], "category": r[11], "status": r[12], "memo": r[13], "paid": r[14],
                "balance": Decimal(r[10] or 0) - Decimal(r[14] or 0),
            })

        cur.execute(
            """
            SELECT t.id::text,t.transaction_date,COALESCE(t.transaction_type,''),t.amount,t.partner_id::text,
                   COALESCE(p.name,t.source_partner_name,''),t.account_id::text,COALESCE(a.bank_name||' '||a.account_name,''),
                   COALESCE(t.description,''),t.contract_id::text,COALESCE(k.name,''),t.my_org_unit_id::text,COALESCE(o.name,''),
                   t.claim_id::text,t.payment_request_id::text,COALESCE(t.category_code,''),COALESCE(t.evidence_type,''),
                   COALESCE(t.memo,''),COALESCE(t.source_type,'manual'),t.evidence_attachment_id::text
              FROM fin.transactions t
              LEFT JOIN ctr.partners p ON p.id=t.partner_id
              LEFT JOIN fin.accounts a ON a.id=t.account_id
              LEFT JOIN ctr.contracts k ON k.id=t.contract_id
              LEFT JOIN ops.my_org_units o ON o.id=t.my_org_unit_id
             WHERE t.is_deleted=false
             ORDER BY t.transaction_date DESC,t.created_at DESC
             LIMIT 1500
            """
        )
        transactions = [
            {"id": r[0], "date": r[1], "type": r[2], "amount": r[3], "partner_id": r[4] or "", "partner": r[5],
             "account_id": r[6] or "", "account": r[7], "description": r[8], "contract_id": r[9] or "", "contract": r[10],
             "org_unit_id": r[11] or "", "org_unit": r[12], "claim_id": r[13] or "", "payment_request_id": r[14] or "",
             "category": r[15], "evidence": r[16], "memo": r[17], "source_type": r[18], "attachment_id": r[19] or ""}
            for r in cur.fetchall()
        ]
    return claims, invoices, payments, transactions


def _refs(alias):
    keys = [
        "finance.claim_type", "finance.claim_status", "finance.invoice_type", "finance.invoice_status",
        "finance.payment_status", "finance.transaction_type", "finance.transaction_category", "finance.evidence_type",
    ]
    return {key: legacy._setting_options(alias, key) for key in keys}


def finance_section(request, section="dashboard"):
    alias = require_tenant_context(request)
    org_units, contracts, partners, accounts, cards = _master_data(alias)
    claims, invoices, payments, transactions = _rows(alias)
    return render(request, "geoflow_ops/finance/finance_section.html", {
        "finance_section": section,
        "finance": legacy._dashboard(alias),
        "org_units": org_units,
        "contracts": contracts,
        "partners": partners,
        "accounts": accounts,
        "cards": cards,
        "claims": claims,
        "invoices": invoices,
        "payments": payments,
        "transactions": transactions,
        "trash": legacy._trash(alias),
        "refs": _refs(alias),
        "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
        "can_hard_delete": gf_has_role(request, "tenant_admin"),
    })


def _org_for_write(alias, request, contract_id=None, account_id=None):
    org_id = _uuid(request.POST.get("my_org_unit_id"))
    contract_org = _uuid(_org_id_from_contract(alias, contract_id)) if contract_id else None
    account_org = _uuid(_org_id_from_account(alias, account_id)) if account_id else None
    resolved = contract_org or account_org or org_id
    if not resolved or not _valid_id(alias, "ops.my_org_units", resolved):
        return None
    return resolved


def claim_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id"))
    contract_id = _uuid(request.POST.get("contract_id"))
    if not contract_id or not _valid_id(alias, "ctr.contracts", contract_id):
        return HttpResponseBadRequest("계약을 확인하세요.")
    org_id = _org_for_write(alias, request, contract_id=contract_id)
    if not org_id:
        return HttpResponseBadRequest("귀속회사를 확인하세요.")
    partner_id = _uuid(request.POST.get("partner_id")) or _uuid(_client_id_from_contract(alias, contract_id))
    project_id = legacy._default_project_id(alias, contract_id)
    supply = legacy._money(request.POST.get("supply_amount")); vat = legacy._money(request.POST.get("vat_amount")); total = supply + vat
    params = [str(contract_id), project_id, str(partner_id) if partner_id else None, str(org_id),
              request.POST.get("claim_date", ""), request.POST.get("due_date", ""), request.POST.get("expected_receipt_date", ""),
              request.POST.get("title") or "청구", request.POST.get("claim_type") or None, supply, vat, total,
              request.POST.get("status") or None, request.POST.get("memo") or None]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute("""UPDATE fin.claims SET contract_id=%s,project_id=%s,partner_id=%s,my_org_unit_id=%s,
                    claim_date=NULLIF(%s,'')::date,due_date=NULLIF(%s,'')::date,expected_receipt_date=NULLIF(%s,'')::date,
                    title=%s,claim_type=%s,supply_amount=%s,vat_amount=%s,total_amount=%s,status=%s,memo=%s,updated_at=now()
                    WHERE id=%s AND is_deleted=false""", params + [str(record_id)])
                messages.success(request, "청구 건을 수정했습니다.")
            else:
                cur.execute("""INSERT INTO fin.claims(contract_id,project_id,partner_id,my_org_unit_id,claim_date,due_date,
                    expected_receipt_date,title,claim_type,supply_amount,vat_amount,total_amount,status,memo,created_by)
                    VALUES(%s,%s,%s,%s,NULLIF(%s,'')::date,NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    params + [legacy._actor(request)])
                messages.success(request, "청구 건을 등록했습니다.")
    return redirect("tenant:finance_claims")


def invoice_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id")); contract_id = _uuid(request.POST.get("contract_id"))
    if not contract_id or not _valid_id(alias, "ctr.contracts", contract_id):
        return HttpResponseBadRequest("계약을 확인하세요.")
    org_id = _org_for_write(alias, request, contract_id=contract_id)
    if not org_id:
        return HttpResponseBadRequest("귀속회사를 확인하세요.")
    invoice_type = request.POST.get("invoice_type") or ""
    sales_code = legacy._semantic_code(alias, "finance.value.invoice_type.sales", "sales")
    partner_id = _uuid(request.POST.get("partner_id"))
    if not partner_id and invoice_type == sales_code:
        partner_id = _uuid(_client_id_from_contract(alias, contract_id))
    project_id = legacy._default_project_id(alias, contract_id)
    supply = legacy._money(request.POST.get("supply_amount")); vat = legacy._money(request.POST.get("vat_amount")); total = supply + vat
    claim_id = _uuid(request.POST.get("claim_id")); payment_id = _uuid(request.POST.get("payment_request_id"))
    if claim_id and payment_id:
        return HttpResponseBadRequest("관련 청구와 지급건은 동시에 지정할 수 없습니다.")
    params = [request.POST.get("written_date", ""), request.POST.get("issued_date", ""), invoice_type,
              str(partner_id) if partner_id else None, str(contract_id), project_id, str(org_id),
              str(claim_id) if claim_id else None, str(payment_id) if payment_id else None,
              supply, vat, total, request.POST.get("approval_no") or None, request.POST.get("status") or None, request.POST.get("memo") or None]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute("""UPDATE fin.tax_invoices SET written_date=NULLIF(%s,'')::date,issued_date=NULLIF(%s,'')::date,
                    invoice_type=%s,partner_id=%s,contract_id=%s,project_id=%s,my_org_unit_id=%s,claim_id=%s,payment_request_id=%s,
                    supply_amount=%s,vat_amount=%s,total_amount=%s,approval_no=%s,status=%s,memo=%s,updated_at=now()
                    WHERE id=%s AND is_deleted=false""", params + [str(record_id)])
                messages.success(request, "세금계산서를 수정했습니다.")
            else:
                cur.execute("""INSERT INTO fin.tax_invoices(written_date,issued_date,invoice_type,partner_id,contract_id,project_id,
                    my_org_unit_id,claim_id,payment_request_id,supply_amount,vat_amount,total_amount,approval_no,status,memo,created_by,source_type)
                    VALUES(NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')""",
                    params + [legacy._actor(request)])
                messages.success(request, "세금계산서를 등록했습니다.")
    return redirect("tenant:finance_invoices")


def payment_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id")); contract_id = _uuid(request.POST.get("contract_id")); partner_id = _uuid(request.POST.get("partner_id"))
    org_id = _org_for_write(alias, request, contract_id=contract_id)
    if not org_id:
        return HttpResponseBadRequest("귀속회사를 확인하세요.")
    project_id = legacy._default_project_id(alias, contract_id)
    amount = legacy._money(request.POST.get("amount"))
    params = [str(contract_id) if contract_id else None, project_id, str(partner_id) if partner_id else None, str(org_id),
              request.POST.get("request_date", ""), request.POST.get("due_date", ""), request.POST.get("title") or "지급",
              amount, request.POST.get("category_code") or None, request.POST.get("status") or None, request.POST.get("memo") or None]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute("""UPDATE fin.payment_requests SET contract_id=%s,project_id=%s,partner_id=%s,my_org_unit_id=%s,
                    request_date=NULLIF(%s,'')::date,due_date=NULLIF(%s,'')::date,title=%s,amount=%s,category_code=%s,status=%s,memo=%s,updated_at=now()
                    WHERE id=%s AND is_deleted=false""", params + [str(record_id)])
                messages.success(request, "지급 건을 수정했습니다.")
            else:
                cur.execute("""INSERT INTO fin.payment_requests(contract_id,project_id,partner_id,my_org_unit_id,request_date,due_date,title,
                    amount,category_code,status,memo,created_by) VALUES(%s,%s,%s,%s,NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s)""",
                    params + [legacy._actor(request)])
                messages.success(request, "지급 건을 등록했습니다.")
    return redirect("tenant:finance_payments")


def transaction_save(request):
    alias = require_tenant_context(request)
    record_id = _uuid(request.POST.get("record_id")); contract_id = _uuid(request.POST.get("contract_id")); account_id = _uuid(request.POST.get("account_id"))
    tx_type = request.POST.get("transaction_type") or ""; partner_id = _uuid(request.POST.get("partner_id"))
    incoming_code = legacy._semantic_code(alias, "finance.value.transaction_type.in", "in")
    if not partner_id and contract_id and tx_type == incoming_code:
        partner_id = _uuid(_client_id_from_contract(alias, contract_id))
    org_id = _org_for_write(alias, request, contract_id=contract_id, account_id=account_id)
    if not org_id:
        return HttpResponseBadRequest("귀속회사를 확인하세요.")
    project_id = legacy._default_project_id(alias, contract_id); amount = legacy._money(request.POST.get("amount"))
    claim_id = _uuid(request.POST.get("claim_id")); payment_id = _uuid(request.POST.get("payment_request_id"))
    if claim_id and payment_id:
        return HttpResponseBadRequest("관련 청구와 지급건은 동시에 지정할 수 없습니다.")
    params = [request.POST.get("transaction_date", ""), tx_type, amount, str(partner_id) if partner_id else None,
              str(account_id) if account_id else None, request.POST.get("description") or None, str(contract_id) if contract_id else None,
              project_id, str(org_id), str(claim_id) if claim_id else None, str(payment_id) if payment_id else None,
              request.POST.get("category_code") or None, request.POST.get("evidence_type") or None, request.POST.get("memo") or None]
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if record_id:
                cur.execute("""UPDATE fin.transactions SET transaction_date=NULLIF(%s,'')::date,transaction_type=%s,amount=%s,partner_id=%s,
                    account_id=%s,description=%s,contract_id=%s,project_id=%s,my_org_unit_id=%s,claim_id=%s,payment_request_id=%s,
                    category_code=%s,evidence_type=%s,memo=%s,updated_at=now() WHERE id=%s AND is_deleted=false""",
                    params + [str(record_id)])
                messages.success(request, "입출금 내역을 수정했습니다.")
            else:
                cur.execute("""INSERT INTO fin.transactions(transaction_date,transaction_type,amount,partner_id,account_id,description,contract_id,
                    project_id,my_org_unit_id,claim_id,payment_request_id,category_code,evidence_type,memo,created_by,source_type)
                    VALUES(NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')""",
                    params + [legacy._actor(request)])
                messages.success(request, "입출금 내역을 등록했습니다.")
    return redirect("tenant:finance_ledger")


def account_save(request):
    alias = require_tenant_context(request)
    org_id = _uuid(request.POST.get("my_org_unit_id"))
    if not org_id or not _valid_id(alias, "ops.my_org_units", org_id):
        return HttpResponseBadRequest("계좌의 귀속회사를 선택하세요.")
    if not request.POST.get("bank_name") or not request.POST.get("account_name"):
        return HttpResponseBadRequest("은행과 계좌명을 확인하세요.")
    with connections[alias].cursor() as cur:
        cur.execute("""INSERT INTO fin.accounts(my_org_unit_id,bank_name,account_name,account_number,currency,memo)
            VALUES(%s,%s,%s,%s,%s,%s)""", [str(org_id), request.POST.get("bank_name"), request.POST.get("account_name"),
            request.POST.get("account_number") or None, request.POST.get("currency") or "KRW", request.POST.get("memo") or None])
    messages.success(request, "계좌를 등록했습니다.")
    return redirect("tenant:finance_settings")


def card_save(request):
    alias = require_tenant_context(request)
    org_id = _uuid(request.POST.get("my_org_unit_id"))
    if not org_id or not _valid_id(alias, "ops.my_org_units", org_id):
        return HttpResponseBadRequest("카드의 귀속회사를 선택하세요.")
    issuer = str(request.POST.get("issuer") or "").strip(); name = str(request.POST.get("card_name") or "").strip()
    if not issuer or not name:
        return HttpResponseBadRequest("카드사와 카드명을 확인하세요.")
    with connections[alias].cursor() as cur:
        cur.execute("""INSERT INTO fin.cards(my_org_unit_id,issuer,card_name,masked_number,memo)
            VALUES(%s,%s,%s,%s,%s)""", [str(org_id), issuer, name, request.POST.get("masked_number") or None, request.POST.get("memo") or None])
    messages.success(request, "법인카드를 등록했습니다.")
    return redirect("tenant:finance_settings")
