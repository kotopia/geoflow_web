from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.contrib import messages
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render

from .services.entity_access import require_tenant_context


def _uuid(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _money(value):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _actor(request):
    user = getattr(request, "user", None)
    return str(getattr(user, "email", None) or getattr(user, "username", None) or getattr(user, "pk", ""))[:255]


def _setting_options(alias: str, field_ref: str):
    with connections[alias].cursor() as cur:
        cur.execute("""
            SELECT v.code, v.name, COALESCE(v.system_key,'')
              FROM ops.settings_nodes c
              JOIN ops.settings_nodes v ON v.parent_id=c.id
             WHERE c.field_ref=%s AND v.node_type='value' AND v.active=true
             ORDER BY v.ord, v.name
        """, [field_ref])
        return [{"code": r[0], "name": r[1], "system_key": r[2]} for r in cur.fetchall()]


def _semantic_code(alias: str, system_key: str, fallback: str):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT code FROM ops.settings_nodes WHERE system_key=%s AND active=true LIMIT 1", [system_key])
        row = cur.fetchone()
    return (row[0] if row else fallback)


def _masters(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, COALESCE(code,''), name FROM ctr.contracts ORDER BY COALESCE(end_date,start_date) DESC NULLS LAST, name")
        contracts = [{"id": r[0], "code": r[1], "name": r[2]} for r in cur.fetchall()]
        cur.execute("SELECT id::text, contract_id::text, COALESCE(code,''), COALESCE(name,'') FROM prj.projects ORDER BY name")
        projects = [{"id": r[0], "contract_id": r[1] or "", "code": r[2], "name": r[3]} for r in cur.fetchall()]
        cur.execute("SELECT id::text, name FROM ctr.partners WHERE COALESCE(status,'') NOT IN ('inactive','deleted') ORDER BY name")
        partners = [{"id": r[0], "name": r[1]} for r in cur.fetchall()]
        cur.execute("SELECT id::text, bank_name, account_name, COALESCE(account_number,''), currency, active FROM fin.accounts ORDER BY active DESC, bank_name, account_name")
        accounts = [{"id":r[0],"bank_name":r[1],"account_name":r[2],"account_number":r[3],"currency":r[4],"active":bool(r[5])} for r in cur.fetchall()]
    return contracts, projects, partners, accounts


def _dashboard(alias: str):
    in_code = _semantic_code(alias, "finance.value.transaction_type.in", "in")
    out_code = _semantic_code(alias, "finance.value.transaction_type.out", "out")
    with connections[alias].cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM ctr.contracts")
        contract_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM fin.claims WHERE COALESCE(status,'') <> %s", [_semantic_code(alias,"finance.value.claim_status.cancelled","cancelled")])
        claim_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE transaction_type=%s", [in_code])
        received_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.payment_requests WHERE COALESCE(status,'') <> %s", [_semantic_code(alias,"finance.value.payment_status.cancelled","cancelled")])
        payment_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE transaction_type=%s", [out_code])
        paid_total = cur.fetchone()[0] or 0
    return {
        "contract_total": contract_total,
        "claim_total": claim_total,
        "received_total": received_total,
        "unclaimed_total": max(Decimal(contract_total or 0)-Decimal(claim_total or 0), Decimal("0")),
        "receivable_total": max(Decimal(claim_total or 0)-Decimal(received_total or 0), Decimal("0")),
        "payment_total": payment_total,
        "paid_total": paid_total,
        "payable_total": max(Decimal(payment_total or 0)-Decimal(paid_total or 0), Decimal("0")),
    }


def _rows(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute("""
            SELECT c.id::text,c.claim_date,c.title,COALESCE(p.name,''),COALESCE(k.name,''),c.total_amount,c.status,
                   COALESCE((SELECT SUM(t.amount) FROM fin.transactions t WHERE t.claim_id=c.id),0)
              FROM fin.claims c LEFT JOIN ctr.partners p ON p.id=c.partner_id LEFT JOIN ctr.contracts k ON k.id=c.contract_id
             ORDER BY c.claim_date DESC NULLS LAST,c.created_at DESC LIMIT 300
        """)
        claims=[{"id":r[0],"date":r[1],"title":r[2],"partner":r[3],"contract":r[4],"total":r[5],"status":r[6],"received":r[7],"balance":Decimal(r[5] or 0)-Decimal(r[7] or 0)} for r in cur.fetchall()]
        cur.execute("""
            SELECT i.id::text,i.written_date,i.issued_date,i.invoice_type,COALESCE(p.name,''),COALESCE(k.name,''),i.total_amount,i.approval_no,i.status
              FROM fin.tax_invoices i LEFT JOIN ctr.partners p ON p.id=i.partner_id LEFT JOIN ctr.contracts k ON k.id=i.contract_id
             ORDER BY COALESCE(i.issued_date,i.written_date) DESC NULLS LAST,i.created_at DESC LIMIT 300
        """)
        invoices=[{"id":r[0],"written_date":r[1],"issued_date":r[2],"type":r[3],"partner":r[4],"contract":r[5],"total":r[6],"approval_no":r[7],"status":r[8]} for r in cur.fetchall()]
        cur.execute("""
            SELECT q.id::text,q.request_date,q.title,COALESCE(p.name,''),COALESCE(k.name,''),q.amount,q.status,
                   COALESCE((SELECT SUM(t.amount) FROM fin.transactions t WHERE t.payment_request_id=q.id),0)
              FROM fin.payment_requests q LEFT JOIN ctr.partners p ON p.id=q.partner_id LEFT JOIN ctr.contracts k ON k.id=q.contract_id
             ORDER BY q.request_date DESC NULLS LAST,q.created_at DESC LIMIT 300
        """)
        payments=[{"id":r[0],"date":r[1],"title":r[2],"partner":r[3],"contract":r[4],"amount":r[5],"status":r[6],"paid":r[7],"balance":Decimal(r[5] or 0)-Decimal(r[7] or 0)} for r in cur.fetchall()]
        cur.execute("""
            SELECT t.id::text,t.transaction_date,t.transaction_type,t.amount,COALESCE(p.name,''),COALESCE(a.bank_name||' '||a.account_name,''),COALESCE(t.description,''),COALESCE(k.name,''),COALESCE(t.category_code,''),COALESCE(t.evidence_type,'')
              FROM fin.transactions t LEFT JOIN ctr.partners p ON p.id=t.partner_id LEFT JOIN fin.accounts a ON a.id=t.account_id LEFT JOIN ctr.contracts k ON k.id=t.contract_id
             ORDER BY t.transaction_date DESC,t.created_at DESC LIMIT 500
        """)
        transactions=[{"id":r[0],"date":r[1],"type":r[2],"amount":r[3],"partner":r[4],"account":r[5],"description":r[6],"contract":r[7],"category":r[8],"evidence":r[9]} for r in cur.fetchall()]
    return claims,invoices,payments,transactions


def finance_page(request):
    alias=require_tenant_context(request)
    contracts,projects,partners,accounts=_masters(alias)
    claims,invoices,payments,transactions=_rows(alias)
    refs={key:_setting_options(alias,key) for key in [
        "finance.claim_type","finance.claim_status","finance.invoice_type","finance.invoice_status",
        "finance.payment_status","finance.transaction_type","finance.transaction_category","finance.evidence_type"
    ]}
    return render(request,"geoflow_ops/finance/finance_page.html",{
        "finance":_dashboard(alias),"contracts":contracts,"projects":projects,"partners":partners,"accounts":accounts,
        "claims":claims,"invoices":invoices,"payments":payments,"transactions":transactions,"refs":refs,
    })


def _exists(alias, table, value):
    if not value: return True
    with connections[alias].cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s", [str(value)])
        return bool(cur.fetchone())


def claim_save(request):
    alias=require_tenant_context(request); contract_id=_uuid(request.POST.get("contract_id")); project_id=_uuid(request.POST.get("project_id")); partner_id=_uuid(request.POST.get("partner_id"))
    if not contract_id or not _exists(alias,"ctr.contracts",contract_id): return HttpResponseBadRequest("계약을 확인하세요.")
    supply=_money(request.POST.get("supply_amount")); vat=_money(request.POST.get("vat_amount")); total=supply+vat
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute("""INSERT INTO fin.claims(contract_id,project_id,partner_id,claim_date,due_date,expected_receipt_date,title,claim_type,supply_amount,vat_amount,total_amount,status,memo,created_by)
                           VALUES(%s,%s,%s,NULLIF(%s,'')::date,NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [str(contract_id),str(project_id) if project_id else None,str(partner_id) if partner_id else None,request.POST.get("claim_date",""),request.POST.get("due_date",""),request.POST.get("expected_receipt_date",""),request.POST.get("title") or "청구",request.POST.get("claim_type") or None,supply,vat,total,request.POST.get("status") or None,request.POST.get("memo") or None,_actor(request)])
    messages.success(request,"청구 건을 등록했습니다."); return redirect("tenant:finance_page")


def invoice_save(request):
    alias=require_tenant_context(request); supply=_money(request.POST.get("supply_amount")); vat=_money(request.POST.get("vat_amount")); total=supply+vat
    invoice_type=request.POST.get("invoice_type") or ""; claim_id=_uuid(request.POST.get("claim_id")); payment_id=_uuid(request.POST.get("payment_request_id"))
    if claim_id and payment_id: return HttpResponseBadRequest("관련 청구와 지급건은 동시에 지정할 수 없습니다.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute("""INSERT INTO fin.tax_invoices(written_date,issued_date,invoice_type,partner_id,contract_id,project_id,claim_id,payment_request_id,supply_amount,vat_amount,total_amount,approval_no,status,memo,created_by)
                           VALUES(NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [request.POST.get("written_date",""),request.POST.get("issued_date",""),invoice_type,str(_uuid(request.POST.get("partner_id"))) if _uuid(request.POST.get("partner_id")) else None,str(_uuid(request.POST.get("contract_id"))) if _uuid(request.POST.get("contract_id")) else None,str(_uuid(request.POST.get("project_id"))) if _uuid(request.POST.get("project_id")) else None,str(claim_id) if claim_id else None,str(payment_id) if payment_id else None,supply,vat,total,request.POST.get("approval_no") or None,request.POST.get("status") or None,request.POST.get("memo") or None,_actor(request)])
    messages.success(request,"세금계산서를 등록했습니다."); return redirect("tenant:finance_page")


def payment_request_save(request):
    alias=require_tenant_context(request); amount=_money(request.POST.get("amount"))
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute("""INSERT INTO fin.payment_requests(contract_id,project_id,partner_id,request_date,due_date,title,amount,category_code,status,memo,created_by)
                           VALUES(%s,%s,%s,NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s)""",
                        [str(_uuid(request.POST.get("contract_id"))) if _uuid(request.POST.get("contract_id")) else None,str(_uuid(request.POST.get("project_id"))) if _uuid(request.POST.get("project_id")) else None,str(_uuid(request.POST.get("partner_id"))) if _uuid(request.POST.get("partner_id")) else None,request.POST.get("request_date",""),request.POST.get("due_date",""),request.POST.get("title") or "지급",amount,request.POST.get("category_code") or None,request.POST.get("status") or None,request.POST.get("memo") or None,_actor(request)])
    messages.success(request,"지급 건을 등록했습니다."); return redirect("tenant:finance_page")


def transaction_save(request):
    alias=require_tenant_context(request); amount=_money(request.POST.get("amount")); claim_id=_uuid(request.POST.get("claim_id")); payment_id=_uuid(request.POST.get("payment_request_id"))
    if claim_id and payment_id: return HttpResponseBadRequest("관련 청구와 지급건은 동시에 지정할 수 없습니다.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute("""INSERT INTO fin.transactions(transaction_date,transaction_type,amount,partner_id,account_id,description,contract_id,project_id,claim_id,payment_request_id,category_code,evidence_type,memo,created_by)
                           VALUES(NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [request.POST.get("transaction_date",""),request.POST.get("transaction_type") or "",amount,str(_uuid(request.POST.get("partner_id"))) if _uuid(request.POST.get("partner_id")) else None,str(_uuid(request.POST.get("account_id"))) if _uuid(request.POST.get("account_id")) else None,request.POST.get("description") or None,str(_uuid(request.POST.get("contract_id"))) if _uuid(request.POST.get("contract_id")) else None,str(_uuid(request.POST.get("project_id"))) if _uuid(request.POST.get("project_id")) else None,str(claim_id) if claim_id else None,str(payment_id) if payment_id else None,request.POST.get("category_code") or None,request.POST.get("evidence_type") or None,request.POST.get("memo") or None,_actor(request)])
    messages.success(request,"입출금 내역을 등록했습니다."); return redirect("tenant:finance_page")


def account_save(request):
    alias=require_tenant_context(request)
    if not (request.POST.get("bank_name") and request.POST.get("account_name")): return HttpResponseBadRequest("은행과 계좌명을 확인하세요.")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute("INSERT INTO fin.accounts(bank_name,account_name,account_number,currency,memo) VALUES(%s,%s,%s,%s,%s)",[request.POST.get("bank_name"),request.POST.get("account_name"),request.POST.get("account_number") or None,request.POST.get("currency") or "KRW",request.POST.get("memo") or None])
    messages.success(request,"계좌를 등록했습니다."); return redirect("tenant:finance_page")


def contract_finance_summary(request, contract_id):
    alias=require_tenant_context(request); in_code=_semantic_code(alias,"finance.value.transaction_type.in","in"); out_code=_semantic_code(alias,"finance.value.transaction_type.out","out")
    with connections[alias].cursor() as cur:
        cur.execute("SELECT COALESCE(amount,0) FROM ctr.contracts WHERE id=%s",[str(contract_id)]); row=cur.fetchone()
        if not row: return JsonResponse({"detail":"not found"},status=404)
        amount=Decimal(row[0] or 0)
        cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM fin.claims WHERE contract_id=%s",[str(contract_id)]); claimed=Decimal(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE contract_id=%s AND transaction_type=%s",[str(contract_id),in_code]); received=Decimal(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.payment_requests WHERE contract_id=%s",[str(contract_id)]); payreq=Decimal(cur.fetchone()[0] or 0)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE contract_id=%s AND transaction_type=%s",[str(contract_id),out_code]); paid=Decimal(cur.fetchone()[0] or 0)
    return JsonResponse({"contract_amount":amount,"claimed":claimed,"received":received,"unclaimed":max(amount-claimed,Decimal('0')),"receivable":max(claimed-received,Decimal('0')),"payment_requested":payreq,"paid":paid,"payable":max(payreq-paid,Decimal('0'))})
