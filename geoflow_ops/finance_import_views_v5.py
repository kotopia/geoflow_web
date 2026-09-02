from __future__ import annotations

from uuid import UUID, uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from control.gf_authz.permissions import gf_has_perm
from .finance_import_views_v2 import (
    INVOICE_FIELDS,
    _actor,
    _default_project_id,
    _invoice_preview,
)
from .finance_import_views_v3 import (
    TRANSACTION_FIELDS,
    _find_header,
    _read_excel,
    _transaction_preview,
)
from .finance_import_views_v4 import _choices
from .services.entity_access import require_tenant_context


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _maps(items):
    return {str(item["id"]): item for item in items}


def _valid_import_type(value):
    return value if value in {"invoice", "transaction"} else "invoice"


def _apply_global_context(rows, import_type, org_id, account_id, contracts, accounts):
    contract_map = _maps(contracts)
    account_map = _maps(accounts)
    account = account_map.get(account_id or "")
    account_org = (account or {}).get("org_unit_id") or ""
    for row in rows:
        payload = row.get("payload") or {}
        if import_type == "transaction" and account:
            payload["account_id"] = account["id"]
        contract = contract_map.get(str(payload.get("contract_id") or ""))
        contract_org = (contract or {}).get("org_unit_id") or ""
        payload["my_org_unit_id"] = contract_org or account_org or org_id or ""
        if contract and not payload.get("partner_id") and contract.get("client_id"):
            payload["partner_id"] = contract["client_id"]
            row.get("display", {})["partner"] = contract.get("client_name") or row.get("display", {}).get("partner")
        if contract and row.get("display") is not None:
            row["display"]["contract"] = contract.get("name") or "-"
    return rows


def _lookup_contract(alias, contract_id):
    if not contract_id:
        return None
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text,client_id::text,org_unit_id::text FROM ctr.contracts WHERE id=%s LIMIT 1", [str(contract_id)])
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "client_id": row[1] or "", "org_unit_id": row[2] or ""}


def _lookup_account_org(alias, account_id):
    if not account_id:
        return ""
    with connections[alias].cursor() as cur:
        cur.execute("SELECT my_org_unit_id::text FROM fin.accounts WHERE id=%s AND is_deleted=false LIMIT 1", [str(account_id)])
        row = cur.fetchone()
    return row[0] if row and row[0] else ""


def _valid_partner(alias, partner_id):
    if not partner_id:
        return True
    with connections[alias].cursor() as cur:
        cur.execute("SELECT 1 FROM ctr.partners WHERE id=%s LIMIT 1", [str(partner_id)])
        return bool(cur.fetchone())


def _commit_preview(alias, preview, selected, request):
    batch_id = str(uuid4())
    created = 0
    skipped = 0
    import_type = preview.get("import_type") or "invoice"
    global_org = str(preview.get("global_org_id") or "")
    global_account = str(preview.get("global_account_id") or "")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            for row in preview.get("rows", []):
                idx = str(row.get("index"))
                if idx not in selected or not row.get("selectable"):
                    continue
                payload = dict(row.get("payload") or {})
                posted_contract = str(request.POST.get(f"row_contract_{idx}") or "").strip()
                posted_partner = str(request.POST.get(f"row_partner_{idx}") or "").strip()
                contract = _lookup_contract(alias, posted_contract) if posted_contract else _lookup_contract(alias, payload.get("contract_id"))
                if posted_contract and not contract:
                    skipped += 1
                    continue
                if posted_partner and not _valid_partner(alias, posted_partner):
                    skipped += 1
                    continue

                contract_id = contract["id"] if contract else ""
                partner_id = posted_partner or str(payload.get("partner_id") or "") or ((contract or {}).get("client_id") or "")
                account_id = str(payload.get("account_id") or global_account or "")
                contract_org = (contract or {}).get("org_unit_id") or ""
                account_org = _lookup_account_org(alias, account_id)
                if contract_org and account_org and contract_org != account_org:
                    skipped += 1
                    continue
                org_id = contract_org or account_org or str(payload.get("my_org_unit_id") or "") or global_org
                if not org_id:
                    skipped += 1
                    continue

                payload["contract_id"] = contract_id
                payload["partner_id"] = partner_id
                payload["account_id"] = account_id
                payload["project_id"] = _default_project_id(alias, contract_id) if contract_id else ""
                payload["my_org_unit_id"] = org_id

                if import_type == "invoice":
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
                        [payload.get("written_date", ""), payload.get("issued_date", ""), payload.get("invoice_type", ""),
                         payload.get("partner_id", ""), payload.get("contract_id", ""), payload.get("project_id", ""), payload.get("my_org_unit_id", ""),
                         payload.get("supply_amount", "0"), payload.get("vat_amount", "0"), payload.get("total_amount", "0"),
                         payload.get("approval_no", ""), payload.get("status", ""), payload.get("memo", ""), _actor(request),
                         payload.get("source_partner_name", ""), payload.get("source_partner_biz_no", ""), payload.get("fingerprint", ""), batch_id],
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
                        [payload.get("transaction_date", ""), payload.get("transaction_type", ""), payload.get("amount", "0"),
                         payload.get("partner_id", ""), payload.get("account_id", ""), payload.get("description", ""), payload.get("contract_id", ""),
                         payload.get("project_id", ""), payload.get("my_org_unit_id", ""), payload.get("category_code", ""),
                         payload.get("evidence_type", ""), payload.get("memo", ""), _actor(request), payload.get("source_partner_name", ""),
                         payload.get("source_partner_biz_no", ""), payload.get("fingerprint", ""), batch_id],
                    )
                created += 1
    return created, skipped


def _render(request, alias, **ctx):
    org_units, contracts, partners, accounts = _choices(alias)
    ctx.setdefault("preview", None)
    ctx.setdefault("import_type", _valid_import_type(request.GET.get("import_type") or request.POST.get("import_type") or "invoice"))
    ctx.setdefault("invoice_direction", "auto")
    ctx.setdefault("header_row", "")
    ctx.setdefault("default_org_unit_id", "")
    ctx.setdefault("default_account_id", "")
    ctx.update({"org_units": org_units, "contracts": contracts, "partners": partners, "accounts": accounts})
    return render(request, "geoflow_ops/finance/finance_import_popup_v2.html", ctx)


@login_required
@require_http_methods(["GET", "POST"])
def finance_import(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    can_write = gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")
    import_type = _valid_import_type(request.GET.get("import_type") or request.POST.get("import_type") or "invoice")

    if request.method == "GET":
        request.session.pop("finance_import_preview", None)
        return _render(request, alias, can_write=can_write, import_type=import_type)
    if not can_write:
        raise PermissionDenied("Permission denied")

    action = str(request.POST.get("action") or "preview").strip()
    if action == "commit":
        preview = request.session.get("finance_import_preview") or {}
        selected = set(request.POST.getlist("selected"))
        if not preview or not selected:
            messages.warning(request, "저장할 행을 선택해 주세요.")
            return _render(request, alias, can_write=can_write, preview=preview or None, import_type=import_type)
        created, skipped = _commit_preview(alias, preview, selected, request)
        request.session.pop("finance_import_preview", None)
        if created:
            messages.success(request, f"선택한 {created}건을 Finance에 저장했습니다.")
        if skipped:
            messages.warning(request, f"계약/귀속회사 연결을 확인할 수 없는 {skipped}건은 저장하지 않았습니다.")
        return _render(request, alias, can_write=can_write, import_type=import_type, import_complete=bool(created))

    upload = request.FILES.get("file")
    invoice_direction = str(request.POST.get("invoice_direction") or "auto").strip()
    header_row_text = str(request.POST.get("header_row") or "").strip()
    org_id = str(request.POST.get("default_org_unit_id") or "").strip()
    account_id = str(request.POST.get("default_account_id") or "").strip()
    extension = str(getattr(upload, "name", "") or "").lower().rsplit(".", 1)[-1] if upload else ""
    if not upload or extension not in {"xlsx", "xls"}:
        messages.error(request, "XLSX 또는 XLS 파일을 확인하세요.")
        return _render(request, alias, can_write=can_write, import_type=import_type, invoice_direction=invoice_direction,
                       header_row=header_row_text, default_org_unit_id=org_id, default_account_id=account_id)

    try:
        manual_row = int(header_row_text) if header_row_text else None
        ws = _read_excel(upload)
        detected_row, mapping, _ = _find_header(ws, import_type, manual_row)
        rows = _invoice_preview(alias, ws, mapping, detected_row, invoice_direction) if import_type == "invoice" else _transaction_preview(alias, ws, mapping, detected_row)
        org_units, contracts, partners, accounts = _choices(alias)
        rows = _apply_global_context(rows, import_type, org_id, account_id, contracts, accounts)
        matched = sorted(set(mapping).intersection(INVOICE_FIELDS if import_type == "invoice" else TRANSACTION_FIELDS))
        preview = {
            "import_type": import_type,
            "invoice_direction": invoice_direction,
            "header_row": detected_row,
            "matched_fields": matched,
            "file_name": str(upload.name),
            "global_org_id": org_id,
            "global_account_id": account_id,
            "rows": rows,
        }
        request.session["finance_import_preview"] = preview
        request.session.modified = True
        return _render(request, alias, can_write=can_write, preview=preview, import_type=import_type, invoice_direction=invoice_direction,
                       header_row=str(detected_row), default_org_unit_id=org_id, default_account_id=account_id)
    except Exception as exc:
        messages.error(request, f"Excel 미리보기에 실패했습니다: {exc}")
        return _render(request, alias, can_write=can_write, import_type=import_type, invoice_direction=invoice_direction,
                       header_row=header_row_text, default_org_unit_id=org_id, default_account_id=account_id)
