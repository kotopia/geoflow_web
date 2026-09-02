from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from python_calamine import CalamineWorkbook

from control.gf_authz.permissions import gf_has_perm
from .finance_import_views_v2 import (
    HEADER_ALIASES as BASE_HEADER_ALIASES,
    INVOICE_FIELDS,
    TRANSACTION_FIELDS as BASE_TRANSACTION_FIELDS,
    _account_id,
    _cell,
    _commit_preview,
    _contract_id,
    _date,
    _default_project_id,
    _existing_transaction,
    _hash,
    _invoice_preview,
    _money,
    _norm,
    _norm_company,
    _partner_indexes,
    _partner_match,
    _ref_code,
    _render,
    _system_code,
)
from .services.entity_access import require_tenant_context


HEADER_ALIASES = {key: set(values) for key, values in BASE_HEADER_ALIASES.items()}
# '구분' is often only a row-number column in bank exports. It is mapped back to
# transaction_type only for files that do not have split deposit/withdrawal columns.
HEADER_ALIASES["transaction_type"] = set(HEADER_ALIASES["transaction_type"]) - {"구분"}
HEADER_ALIASES.update({
    "withdraw_amount": {"출금", "출금액", "출금금액", "출금금액원", "지급금액", "찾으신금액"},
    "deposit_amount": {"입금", "입금액", "입금금액", "입금금액원", "맡기신금액"},
    "counterparty_name": {"상대계좌예금주명", "상대예금주명", "상대예금주", "거래상대방", "상대방", "받는분", "보낸분"},
    "counterparty_bank": {"상대은행", "상대은행명"},
    "record_detail": {"거래기록사항", "기록사항", "거래기록"},
    "transfer_memo": {"이체메모", "송금메모"},
})

TRANSACTION_FIELDS = set(BASE_TRANSACTION_FIELDS) | {
    "withdraw_amount", "deposit_amount", "counterparty_name", "counterparty_bank", "record_detail", "transfer_memo",
}


class _WorksheetRows:
    """Small worksheet adapter so the existing preview logic can read Calamine rows."""

    def __init__(self, rows):
        self._rows = [tuple(row or []) for row in (rows or [])]
        self.max_row = len(self._rows)

    def iter_rows(self, min_row=1, max_row=None, values_only=True):
        start = max(int(min_row or 1), 1) - 1
        end = self.max_row if max_row is None else min(int(max_row), self.max_row)
        for row in self._rows[start:end]:
            yield row


def _headers(row):
    normalized = {_norm(value): idx for idx, value in enumerate(row) if value not in (None, "")}
    result = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _norm(alias)
            if key in normalized:
                result[field] = normalized[key]
                break

    has_split_amount = "withdraw_amount" in result or "deposit_amount" in result
    if not has_split_amount and "transaction_type" not in result:
        generic = normalized.get(_norm("구분"))
        if generic is not None:
            result["transaction_type"] = generic
    return result


def _find_header(ws, import_type, manual_row=None):
    relevant = INVOICE_FIELDS if import_type == "invoice" else TRANSACTION_FIELDS
    if manual_row:
        row = next(ws.iter_rows(min_row=manual_row, max_row=manual_row, values_only=True), None) or []
        mapping = _headers(row)
        return manual_row, mapping, list(row)

    best = None
    max_row = min(int(ws.max_row or 1), 30)
    for row_no, row in enumerate(ws.iter_rows(min_row=1, max_row=max_row, values_only=True), start=1):
        mapping = _headers(row)
        score = len(set(mapping).intersection(relevant))
        # Split deposit/withdrawal layouts are a strong bank-statement signal.
        if "transaction_date" in mapping:
            score += 2
        if "withdraw_amount" in mapping or "deposit_amount" in mapping:
            score += 3
        if best is None or score > best[0]:
            best = (score, row_no, mapping, list(row))
    if not best or best[0] < 2:
        raise ValueError("상단 30행에서 헤더를 자동으로 찾지 못했습니다. 헤더 행 번호를 직접 입력해 주세요.")
    return best[1], best[2], best[3]


def _is_summary_row(row):
    tokens = {_norm(value) for value in row if value not in (None, "")}
    return bool(tokens.intersection({_norm("합계"), _norm("소계"), "total"}))


def _split_direction_amount(row, mapping, incoming_code, outgoing_code):
    """Derive in/out and amount from bank-style separate deposit/withdrawal columns."""
    has_split = "withdraw_amount" in mapping or "deposit_amount" in mapping
    if not has_split:
        return None, None, None

    withdrawal = _money(_cell(row, mapping, "withdraw_amount")) or Decimal("0")
    deposit = _money(_cell(row, mapping, "deposit_amount")) or Decimal("0")

    if deposit > 0 and withdrawal <= 0:
        return incoming_code, deposit, None
    if withdrawal > 0 and deposit <= 0:
        return outgoing_code, withdrawal, None
    if deposit <= 0 and withdrawal <= 0:
        return None, None, "입금액/출금액이 없습니다."
    return None, None, "한 행에 입금액과 출금액이 동시에 있어 방향을 판정할 수 없습니다."


def _transaction_preview(alias, ws, mapping, header_row):
    by_biz, by_name = _partner_indexes(alias)
    incoming_code = _system_code(alias, "finance.value.transaction_type.in") or "in"
    outgoing_code = _system_code(alias, "finance.value.transaction_type.out") or "out"
    rows = []

    for row_no, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
        if not any(value not in (None, "") for value in row):
            continue
        if _is_summary_row(row) and not _cell(row, mapping, "transaction_date"):
            continue
        if len(rows) >= 1000:
            break

        warnings = []
        errors = []
        try:
            tx_date = _date(_cell(row, mapping, "transaction_date"))
        except ValueError as exc:
            tx_date = None
            errors.append(str(exc))
        if not tx_date:
            errors.append("거래일자가 없습니다.")

        split_type = split_amount = split_error = None
        try:
            split_type, split_amount, split_error = _split_direction_amount(
                row, mapping, incoming_code, outgoing_code
            )
        except ValueError as exc:
            split_error = str(exc)

        if "withdraw_amount" in mapping or "deposit_amount" in mapping:
            tx_type = split_type
            amount = split_amount
            if split_error:
                errors.append(split_error)
        else:
            tx_type = _ref_code(alias, "finance.transaction_type", _cell(row, mapping, "transaction_type"))
            if not tx_type:
                errors.append("입금/출금 구분을 찾을 수 없습니다.")
            try:
                amount = _money(_cell(row, mapping, "amount"))
            except ValueError as exc:
                amount = None
                errors.append(str(exc))
            if amount is None:
                errors.append("금액이 없습니다.")

        if amount is None:
            amount = Decimal("0")

        explicit_partner = str(_cell(row, mapping, "partner") or "").strip()
        counterparty = str(_cell(row, mapping, "counterparty_name") or "").strip()
        record_detail = str(_cell(row, mapping, "record_detail") or "").strip()
        partner_name = explicit_partner or counterparty
        partner_id = _partner_match(by_biz, by_name, partner_name, "") if partner_name else None
        if not partner_id and record_detail:
            candidate_id = _partner_match(by_biz, by_name, record_detail, "")
            if candidate_id:
                partner_id = candidate_id
                partner_name = record_detail
        if partner_name and not partner_id:
            warnings.append("GeoFlow 거래처와 자동 매칭되지 않았습니다.")

        direct_description = str(_cell(row, mapping, "description") or "").strip()
        description = record_detail or direct_description
        transfer_memo = str(_cell(row, mapping, "transfer_memo") or "").strip()
        counterparty_bank = str(_cell(row, mapping, "counterparty_bank") or "").strip()
        memo_parts = [part for part in [transfer_memo] if part]
        if record_detail and direct_description and record_detail != direct_description:
            memo_parts.append(f"거래내용: {direct_description}")
        if counterparty_bank:
            memo_parts.append(f"상대은행: {counterparty_bank}")
        memo = " / ".join(memo_parts)

        contract_id = _contract_id(alias, _cell(row, mapping, "contract"))
        project_id = _default_project_id(alias, contract_id)
        account_id = _account_id(alias, _cell(row, mapping, "account"))
        category = _ref_code(alias, "finance.transaction_category", _cell(row, mapping, "category"))
        evidence = _ref_code(alias, "finance.evidence_type", _cell(row, mapping, "evidence_type"))

        payload = {
            "transaction_date": tx_date.isoformat() if tx_date else "",
            "transaction_type": tx_type or "",
            "amount": str(amount),
            "partner_id": partner_id or "",
            "source_partner_name": partner_name,
            "source_partner_biz_no": "",
            "account_id": account_id or "",
            "description": description,
            "contract_id": contract_id or "",
            "project_id": project_id or "",
            "category_code": category or "",
            "evidence_type": evidence or "",
            "memo": memo,
        }
        payload["fingerprint"] = _hash([
            payload["transaction_date"], tx_type, amount, _norm_company(partner_name), description
        ])
        duplicate = _existing_transaction(alias, payload) if not errors else None
        status_key = "error" if errors else ("duplicate" if duplicate else ("warning" if warnings else "new"))
        rows.append({
            "index": len(rows),
            "row_no": row_no,
            "status": status_key,
            "status_label": {"new": "신규", "warning": "확인", "duplicate": "중복 의심", "error": "저장 불가"}[status_key],
            "message": " / ".join(errors or warnings),
            "duplicate": duplicate,
            "payload": payload,
            "display": {
                "date": payload["transaction_date"],
                "partner": partner_name or "-",
                "contract": str(_cell(row, mapping, "contract") or "-"),
                "description": description or "-",
                "amount": str(amount),
            },
            "selectable": not errors,
            "default_selected": not errors and not duplicate,
        })
    return rows


def _read_excel(upload):
    upload.file.seek(0)
    workbook = CalamineWorkbook.from_object(upload.file)
    try:
        sheet = workbook.get_sheet_by_index(0)
        data = sheet.to_python(skip_empty_area=False)
        return _WorksheetRows(data)
    finally:
        workbook.close()


@login_required
@require_http_methods(["GET", "POST"])
def finance_import(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    can_write = gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create")

    if request.method == "GET":
        request.session.pop("finance_import_preview", None)
        return _render(request, can_write=can_write)
    if not can_write:
        raise PermissionDenied("Permission denied")

    action = str(request.POST.get("action") or "preview").strip()
    if action == "commit":
        preview = request.session.get("finance_import_preview") or {}
        selected = set(request.POST.getlist("selected"))
        if not preview or not selected:
            messages.warning(request, "저장할 행을 선택해 주세요.")
            return _render(request, can_write=can_write, preview=preview or None, import_type=preview.get("import_type", "invoice"))
        created, skipped = _commit_preview(alias, preview, selected, request)
        request.session.pop("finance_import_preview", None)
        messages.success(request, f"선택한 {created}건을 Finance에 저장했습니다.")
        if skipped:
            messages.info(request, f"선택하지 않은 항목 또는 저장 불가 항목 {skipped}건은 반영하지 않았습니다.")
        return redirect("tenant:finance_import")

    if action == "clear":
        request.session.pop("finance_import_preview", None)
        return redirect("tenant:finance_import")

    upload = request.FILES.get("file")
    import_type = str(request.POST.get("import_type") or "invoice").strip()
    invoice_direction = str(request.POST.get("invoice_direction") or "auto").strip()
    header_row_text = str(request.POST.get("header_row") or "").strip()
    if import_type not in {"invoice", "transaction"}:
        messages.error(request, "가져오기 유형을 확인하세요.")
        return _render(request, can_write=can_write)

    extension = str(getattr(upload, "name", "") or "").lower().rsplit(".", 1)[-1] if upload else ""
    if not upload or extension not in {"xlsx", "xls"}:
        messages.error(request, "XLSX 또는 XLS 파일을 선택해 주세요.")
        return _render(request, can_write=can_write, import_type=import_type, invoice_direction=invoice_direction, header_row=header_row_text)

    try:
        manual_row = int(header_row_text) if header_row_text else None
        if manual_row is not None and manual_row < 1:
            raise ValueError("헤더 행은 1 이상의 숫자여야 합니다.")
        ws = _read_excel(upload)
        detected_row, mapping, _ = _find_header(ws, import_type, manual_row)
        if import_type == "invoice":
            rows = _invoice_preview(alias, ws, mapping, detected_row, invoice_direction)
        else:
            rows = _transaction_preview(alias, ws, mapping, detected_row)
        matched = sorted(set(mapping).intersection(INVOICE_FIELDS if import_type == "invoice" else TRANSACTION_FIELDS))
        preview = {
            "import_type": import_type,
            "invoice_direction": invoice_direction,
            "header_row": detected_row,
            "matched_fields": matched,
            "file_name": str(upload.name),
            "rows": rows,
        }
        request.session["finance_import_preview"] = preview
        request.session.modified = True
        return _render(
            request,
            can_write=can_write,
            preview=preview,
            import_type=import_type,
            invoice_direction=invoice_direction,
            header_row=str(detected_row),
        )
    except Exception as exc:
        messages.error(request, f"Excel 미리보기에 실패했습니다: {exc}")
        return _render(request, can_write=can_write, import_type=import_type, invoice_direction=invoice_direction, header_row=header_row_text)
