from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from openpyxl import load_workbook

from control.gf_authz.permissions import gf_has_perm
from .finance_import_views import (
    _actor, _cell, _date, _headers, _import_transactions, _lookup, _money, _project, _ref_code,
)
from .services.entity_access import require_tenant_context


def _system_code(alias, system_key):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT code FROM ops.settings_nodes WHERE system_key=%s AND active=true LIMIT 1", [system_key])
        row = cur.fetchone()
    if not row:
        raise ValueError(f"필수 Finance 환경설정이 없습니다: {system_key}")
    return row[0]


def _import_invoices(alias, ws, mapping, request):
    created = 0
    errors = []
    default_status = _system_code(alias, "finance.value.invoice_status.issued")
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(v not in (None, "") for v in row):
            continue
        try:
            partner_id = _lookup(alias, "ctr.partners", _cell(row, mapping, "partner"), columns=("name",), required=True)
            contract_id = _lookup(alias, "ctr.contracts", _cell(row, mapping, "contract"), required=False)
            project_id = _project(alias, _cell(row, mapping, "project"), contract_id)
            invoice_type = _ref_code(alias, "finance.invoice_type", _cell(row, mapping, "invoice_type"), required=True)
            status_cell = _cell(row, mapping, "status")
            status = _ref_code(alias, "finance.invoice_status", status_cell, required=True) if status_cell not in (None, "") else default_status
            supply = _money(_cell(row, mapping, "supply_amount"))
            vat = _money(_cell(row, mapping, "vat_amount"))
            total = _money(_cell(row, mapping, "total_amount")) if _cell(row, mapping, "total_amount") not in (None, "") else supply + vat
            approval_no = str(_cell(row, mapping, "approval_no") or "").strip() or None
            if approval_no:
                with connections[alias].cursor() as cur:
                    cur.execute("SELECT 1 FROM fin.tax_invoices WHERE approval_no=%s LIMIT 1", [approval_no])
                    if cur.fetchone():
                        continue
            with connections[alias].cursor() as cur:
                cur.execute("""INSERT INTO fin.tax_invoices(written_date,issued_date,invoice_type,partner_id,contract_id,project_id,supply_amount,vat_amount,total_amount,approval_no,status,memo,created_by)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
                    _date(_cell(row,mapping,"written_date")), _date(_cell(row,mapping,"issued_date")), invoice_type, partner_id,
                    contract_id, project_id, supply, vat, total, approval_no, status, str(_cell(row,mapping,"memo") or "").strip() or None, _actor(request)
                ])
            created += 1
        except Exception as exc:
            errors.append(f"{row_no}행: {exc}")
    return created, errors


@login_required
@require_http_methods(["GET", "POST"])
def finance_import(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    can_write = gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")
    if request.method == "GET":
        errors = request.session.pop("finance_import_errors", [])
        return render(request, "geoflow_ops/finance/finance_import.html", {"import_errors": errors})
    if not can_write:
        raise PermissionDenied("Permission denied")

    upload = request.FILES.get("file")
    import_type = str(request.POST.get("import_type") or "").strip()
    if not upload or import_type not in {"invoice", "transaction"}:
        messages.error(request, "가져오기 유형과 XLSX 파일을 확인하세요.")
        return redirect("tenant:finance_import")
    if not str(upload.name).lower().endswith(".xlsx"):
        messages.error(request, "XLSX 파일만 지원합니다.")
        return redirect("tenant:finance_import")

    try:
        wb = load_workbook(upload, read_only=True, data_only=True)
        ws = wb.active
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        mapping = _headers(first_row or [])
        required = {"invoice": {"invoice_type", "partner", "supply_amount"}, "transaction": {"transaction_date", "transaction_type", "amount"}}[import_type]
        missing = sorted(required - set(mapping))
        if missing:
            raise ValueError("필수 헤더가 없습니다: " + ", ".join(missing))
        with transaction.atomic(using=alias):
            if import_type == "invoice":
                created, errors = _import_invoices(alias, ws, mapping, request)
            else:
                created, errors = _import_transactions(alias, ws, mapping, request)
        wb.close()
    except Exception as exc:
        messages.error(request, f"Excel 가져오기에 실패했습니다: {exc}")
        return redirect("tenant:finance_import")

    messages.success(request, f"{created}건을 가져왔습니다.")
    if errors:
        request.session["finance_import_errors"] = errors[:100]
        messages.warning(request, f"{len(errors)}건은 가져오지 못했습니다. 아래 오류 목록을 확인하세요.")
    return redirect("tenant:finance_import")
