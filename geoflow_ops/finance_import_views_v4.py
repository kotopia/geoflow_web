from __future__ import annotations

from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from control.gf_authz.permissions import gf_has_perm
from .finance_import_views_v2 import (
    INVOICE_FIELDS,
    _actor,
    _existing_invoice,
    _existing_transaction,
    _invoice_preview,
)
from .finance_import_views_v3 import (
    TRANSACTION_FIELDS,
    _find_header,
    _read_excel,
    _transaction_preview,
)
from .services.entity_access import require_tenant_context


def _choices(alias):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text,name,COALESCE(biz_no,'') FROM ops.my_org_units ORDER BY name")
        org_units = [{"id": r[0], "name": r[1], "biz_no": r[2]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT c.id::text,COALESCE(c.code,''),c.name,c.client_id::text,COALESCE(p.name,''),c.org_unit_id::text,COALESCE(o.name,'')
              FROM ctr.contracts c
              LEFT JOIN ctr.partners p ON p.id=c.client_id
              LEFT JOIN ops.my_org_units o ON o.id=c.org_unit_id
             ORDER BY COALESCE(c.start_date,c.end_date) DESC NULLS LAST,c.code DESC,c.name
            """
        )
        contracts = [{"id": r[0], "code": r[1], "name": r[2], "client_id": r[3] or "", "client_name": r[4], "org_unit_id": r[5] or "", "org_unit_name": r[6]} for r in cur.fetchall()]
        cur.execute("SELECT id::text,name FROM ctr.partners WHERE COALESCE(status,'') NOT IN ('inactive','deleted') ORDER BY name")
        partners = [{"id": r[0], "name": r[1]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT a.id::text,a.bank_name,a.account_name,a.my_org_unit_id::text,COALESCE(o.name,'')
              FROM fin.accounts a LEFT JOIN ops.my_org_units o ON o.id=a.my_org_unit_id
             WHERE a.active=true ORDER BY o.name,a.bank_name,a.account_name
            """
        )
        accounts = [{"id": r[0], "bank_name": r[1], "account_name": r[2], "org_unit_id": r[3] or "", "org_unit_name": r[4]} for r in cur.fetchall()]
    return org_units, contracts, partners, accounts


def _by_id(items):
    return {str(item["id"]): item for item in items}


def _apply_defaults(alias, rows, import_type, defaults, contracts, partners, accounts):
    contract_map = _by_id(contracts); partner_map = _by_id(partners); account_map = _by_id(accounts)
    default_contract = contract_map.get(defaults.get("contract_id") or "")
    default_partner = partner_map.get(defaults.get("partner_id") or "")
    default_account = account_map.get(defaults.get("account_id") or "")

    for row in rows:
        p = row.get("payload") or {}
        if not p.get("contract_id") and default_contract:
            p["contract_id"] = default_contract["id"]
            if row.get("display") is not None:
                row["display"]["contract"] = default_contract["name"]
        if import_type == "transaction" and not p.get("account_id") and default_account:
            p["account_id"] = default_account["id"]

        contract = contract_map.get(str(p.get("contract_id") or ""))
        account = account_map.get(str(p.get("account_id") or ""))
        org_id = (contract or {}).get("org_unit_id") or (account or {}).get("org_unit_id") or defaults.get("org_unit_id") or ""
        p["my_org_unit_id"] = org_id

        if contract and account and contract.get("org_unit_id") and account.get("org_unit_id") and contract["org_unit_id"] != account["org_unit_id"]:
            row["selectable"] = False
            row["status"] = "error"
            row["status_label"] = "저장 불가"
            row["message"] = "선택한 계약의 귀속회사와 계좌의 귀속회사가 다릅니다."
            continue
        if not org_id:
            row["selectable"] = False
            row["status"] = "error"
            row["status_label"] = "저장 불가"
            row["message"] = ((row.get("message") or "") + " / 귀속회사를 결정할 수 없습니다.").strip(" /")
            continue

        if not p.get("partner_id"):
            chosen_partner = None
            if default_partner:
                chosen_partner = default_partner
            elif contract:
                if import_type == "invoice" and p.get("invoice_type") == "sales":
                    chosen_partner = partner_map.get(contract.get("client_id") or "")
                elif import_type == "transaction" and p.get("transaction_type") == "in":
                    chosen_partner = partner_map.get(contract.get("client_id") or "")
            if chosen_partner:
                p["partner_id"] = chosen_partner["id"]
                if not p.get("source_partner_name"):
                    p["source_partner_name"] = chosen_partner["name"]
                if row.get("display") is not None:
                    row["display"]["partner"] = chosen_partner["name"]

        if row.get("status") != "error":
            duplicate = _existing_invoice(alias, p) if import_type == "invoice" else _existing_transaction(alias, p)
            row["duplicate"] = duplicate
            if duplicate:
                row["status"] = "duplicate"
                row["status_label"] = "중복 의심"
                row["default_selected"] = False
    return rows


def _commit_preview(alias, preview, selected, request):
    batch_id = str(uuid4())
    created = 0
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            for row in preview.get("rows", []):
                if str(row.get("index")) not in selected or not row.get("selectable"):
                    continue
                p = row.get("payload") or {}
                if preview.get("import_type") == "invoice":
                    cur.execute(
                        """
                        INSERT INTO fin.tax_invoices(
                            written_date,issued_date,invoice_type,partner_id,contract_id,project_id,my_org_unit_id,
                            supply_amount,vat_amount,total_amount,approval_no,status,memo,created_by,source_type,
                            source_partner_name,source_partner_biz_no,import_fingerprint,import_batch_id
                        ) VALUES(
                            NULLIF(%s,'')::date,NULLIF(%s,'')::date,%s,NULLIF(%s,'')::uuid,NULLIF(%s,'')::uuid,NULLIF(%s,'')::uuid,NULLIF(%s,'')::uuid,
                            %s,%s,%s,NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),%s,'xlsx',NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),%s::uuid
                        )
                        """,
                        [p.get("written_date",""),p.get("issued_date",""),p.get("invoice_type",""),p.get("partner_id",""),p.get("contract_id",""),
                         p.get("project_id",""),p.get("my_org_unit_id",""),p.get("supply_amount","0"),p.get("vat_amount","0"),p.get("total_amount","0"),
                         p.get("approval_no",""),p.get("status",""),p.get("memo",""),_actor(request),p.get("source_partner_name",""),
                         p.get("source_partner_biz_no",""),p.get("fingerprint",""),batch_id],
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO fin.transactions(
                            transaction_date,transaction_type,amount,partner_id,account_id,description,contract_id,project_id,my_org_unit_id,
                            category_code,evidence_type,memo,created_by,source_type,source_partner_name,source_partner_biz_no,import_fingerprint,import_batch_id
                        ) VALUES(
                            %s::date,%s,%s,NULLIF(%s,'')::uuid,NULLIF(%s,'')::uuid,NULLIF(%s,''),NULLIF(%s,'')::uuid,NULLIF(%s,'')::uuid,NULLIF(%s,'')::uuid,
                            NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),%s,'xlsx',NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),%s::uuid
                        )
                        """,
                        [p.get("transaction_date",""),p.get("transaction_type",""),p.get("amount","0"),p.get("partner_id",""),p.get("account_id",""),
                         p.get("description",""),p.get("contract_id",""),p.get("project_id",""),p.get("my_org_unit_id",""),p.get("category_code",""),
                         p.get("evidence_type",""),p.get("memo",""),_actor(request),p.get("source_partner_name",""),p.get("source_partner_biz_no",""),
                         p.get("fingerprint",""),batch_id],
                    )
                created += 1
    return created


def _render(request, alias, **ctx):
    org_units, contracts, partners, accounts = _choices(alias)
    ctx.setdefault("preview", None)
    ctx.setdefault("import_type", request.GET.get("import_type") or "invoice")
    ctx.setdefault("invoice_direction", "auto")
    ctx.setdefault("header_row", "")
    ctx.update({"org_units": org_units, "contracts": contracts, "partners": partners, "accounts": accounts})
    return render(request, "geoflow_ops/finance/finance_import_popup.html", ctx)


@login_required
@require_http_methods(["GET", "POST"])
def finance_import(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    can_write = gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")
    if request.method == "GET":
        request.session.pop("finance_import_preview", None)
        return _render(request, alias, can_write=can_write)
    if not can_write:
        raise PermissionDenied("Permission denied")

    action = str(request.POST.get("action") or "preview").strip()
    if action == "commit":
        preview = request.session.get("finance_import_preview") or {}
        selected = set(request.POST.getlist("selected"))
        if not preview or not selected:
            messages.warning(request, "저장할 행을 선택해 주세요.")
            return _render(request, alias, can_write=can_write, preview=preview or None, import_type=preview.get("import_type","invoice"))
        created = _commit_preview(alias, preview, selected, request)
        request.session.pop("finance_import_preview", None)
        messages.success(request, f"선택한 {created}건을 Finance에 저장했습니다.")
        return redirect(reverse("tenant:finance_import") + "?modal=1&import_type=" + preview.get("import_type","invoice"))

    upload = request.FILES.get("file")
    import_type = str(request.POST.get("import_type") or "invoice").strip()
    invoice_direction = str(request.POST.get("invoice_direction") or "auto").strip()
    header_row_text = str(request.POST.get("header_row") or "").strip()
    defaults = {
        "org_unit_id": str(request.POST.get("default_org_unit_id") or "").strip(),
        "account_id": str(request.POST.get("default_account_id") or "").strip(),
        "contract_id": str(request.POST.get("default_contract_id") or "").strip(),
        "partner_id": str(request.POST.get("default_partner_id") or "").strip(),
    }
    extension = str(getattr(upload,"name","") or "").lower().rsplit(".",1)[-1] if upload else ""
    if import_type not in {"invoice","transaction"} or not upload or extension not in {"xlsx","xls"}:
        messages.error(request, "XLSX 또는 XLS 파일과 가져오기 유형을 확인하세요.")
        return _render(request, alias, can_write=can_write, import_type=import_type, invoice_direction=invoice_direction, header_row=header_row_text, **{f"default_{k}":v for k,v in defaults.items()})

    try:
        manual_row = int(header_row_text) if header_row_text else None
        ws = _read_excel(upload)
        detected_row, mapping, _ = _find_header(ws, import_type, manual_row)
        rows = _invoice_preview(alias, ws, mapping, detected_row, invoice_direction) if import_type == "invoice" else _transaction_preview(alias, ws, mapping, detected_row)
        org_units, contracts, partners, accounts = _choices(alias)
        rows = _apply_defaults(alias, rows, import_type, defaults, contracts, partners, accounts)
        matched = sorted(set(mapping).intersection(INVOICE_FIELDS if import_type == "invoice" else TRANSACTION_FIELDS))
        preview = {"import_type": import_type, "invoice_direction": invoice_direction, "header_row": detected_row, "matched_fields": matched, "file_name": str(upload.name), "rows": rows}
        request.session["finance_import_preview"] = preview
        request.session.modified = True
        return _render(request, alias, can_write=can_write, preview=preview, import_type=import_type, invoice_direction=invoice_direction, header_row=str(detected_row), **{f"default_{k}":v for k,v in defaults.items()})
    except Exception as exc:
        messages.error(request, f"Excel 미리보기에 실패했습니다: {exc}")
        return _render(request, alias, can_write=can_write, import_type=import_type, invoice_direction=invoice_direction, header_row=header_row_text, **{f"default_{k}":v for k,v in defaults.items()})
