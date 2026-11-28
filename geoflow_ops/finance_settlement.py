"""Tenant finance source reconciliation and printable document snapshots."""

import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import connections, transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .services.finance_access import can_edit_finance, require_finance_access
from .views_finance import _semantic_code

SOURCES = {
    "invoice": ("fin.tax_invoices", "total_amount", "invoice_type", "written_date"),
    "transaction": (
        "fin.transactions",
        "amount",
        "transaction_type",
        "transaction_date",
    ),
}
TARGETS = {
    "claim": ("fin.claims", "total_amount", "claim_date", "claim_id"),
    "payment": ("fin.payment_requests", "amount", "request_date", "payment_request_id"),
}


def rows(cursor):
    fields = [field[0] for field in cursor.description]
    return [dict(zip(fields, record)) for record in cursor.fetchall()]


def source_record(cur, kind, pk, lock):
    table, amount, direction, date = SOURCES[kind]
    invoice_fields = (
        ",s.approval_no,s.issued_date,s.supply_amount,s.vat_amount,s.attachment_id, "
        "COALESCE(p.name,s.source_partner_name) AS partner,o.name AS org"
        if kind == "invoice"
        else ""
    )
    cur.execute(
        f"""SELECT s.id,s.{amount} AS amount,s.{direction} AS direction,s.{date} AS date,
        s.partner_id,s.my_org_unit_id,s.contract_id,c.name AS contract,s.updated_at {invoice_fields}
        FROM {table} s LEFT JOIN ctr.contracts c ON c.id=s.contract_id
        LEFT JOIN ctr.partners p ON p.id=s.partner_id LEFT JOIN ops.my_org_units o ON o.id=s.my_org_unit_id
        WHERE s.id=%s AND NOT s.is_deleted {"FOR UPDATE OF s" if lock else ""}""",
        [pk],
    )
    records = rows(cur)
    if not records:
        raise Http404
    return records[0]


def target_kind(alias, source_kind, direction):
    field, positive, negative = (
        ("invoice_type", "sales", "purchase")
        if source_kind == "invoice"
        else ("transaction_type", "in", "out")
    )
    for code, target in ((positive, "claim"), (negative, "payment")):
        if direction == _semantic_code(alias, f"finance.value.{field}.{code}", code):
            return target
    return None


def candidates(cur, kind, source_kind, source):
    table, amount, date, key = TARGETS[kind]
    cur.execute(
        f"""SELECT t.id,t.title,t.{date} AS date,c.name AS contract,p.name AS partner,
          t.{amount} AS total, COALESCE(a.amount,0) AS assigned,
          t.partner_id=%s AS partner_match,t.contract_id=%s AS contract_match,
          t.{amount}=%s AS amount_match,t.{date}=%s AS date_match
        FROM {table} t LEFT JOIN ctr.contracts c ON c.id=t.contract_id
        LEFT JOIN ctr.partners p ON p.id=t.partner_id
        LEFT JOIN fin.confirmed_links a ON a.{key}=t.id AND a.{source_kind}_id=%s
        WHERE NOT t.is_deleted AND t.my_org_unit_id=%s
        ORDER BY (a.amount IS NOT NULL) DESC,contract_match DESC NULLS LAST,
          partner_match DESC NULLS LAST,amount_match DESC,date_match DESC NULLS LAST,t.title,t.id""",
        [
            source["partner_id"],
            source["contract_id"],
            source["amount"],
            source["date"],
            source["id"],
            source["my_org_unit_id"],
        ],
    )
    return rows(cur)


def parse_allocations(post):
    result = {}
    for name in post:
        if not name.startswith("allocate_"):
            continue
        value = post[name].strip()
        if not value or value == "0":
            continue
        if not value.isascii() or not value.isdigit() or len(value) > 18:
            raise ValueError("배분액은 원 단위 양수로 입력하세요.")
        result[UUID(name[9:])] = int(value)
    return result


@login_required
@require_http_methods(["GET", "POST"])
def reconcile(request, kind, record_id):
    write = request.method == "POST"
    alias = require_finance_access(request, write=write)
    if kind not in SOURCES:
        raise Http404
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        source = source_record(cur, kind, record_id, write)
        target = target_kind(alias, kind, source["direction"])
        if not target:
            return HttpResponseBadRequest("입출금 또는 매출·매입 구분을 확인하세요.")
        options = candidates(cur, target, kind, source)
        version = source["updated_at"].isoformat()
        if write:
            if version != request.POST.get("version"):
                return HttpResponseBadRequest(
                    "자료가 변경되었습니다. 새로고침 후 다시 확인하세요."
                )
            try:
                amounts = parse_allocations(request.POST)
            except ValueError:
                return HttpResponseBadRequest("연결 대상과 배분액을 확인하세요.")
            table, total, date, key = TARGETS[target]
            if request.POST.get("start"):
                if (
                    kind != "invoice"
                    or amounts
                    or any(o["assigned"] for o in options)
                    or not source["contract_id"]
                    or not source["my_org_unit_id"]
                    or source["amount"] <= 0
                ):
                    return HttpResponseBadRequest(
                        "계약과 귀속회사를 지정한 미연결 계산서를 선택하세요."
                    )
                extras = ",supply_amount,vat_amount" if target == "claim" else ""
                cur.execute(
                    f"""INSERT INTO {table}(title,contract_id,project_id,partner_id,my_org_unit_id,{date},{total}{extras})
                    SELECT %s,contract_id,project_id,partner_id,my_org_unit_id,written_date,total_amount{extras}
                    FROM fin.tax_invoices WHERE id=%s RETURNING id""",
                    [source["contract"], record_id],
                )
                amounts = {cur.fetchone()[0]: source["amount"]}
            if amounts:
                cur.execute(
                    f"""SELECT id FROM {table} WHERE id=ANY(%s::uuid[]) AND NOT is_deleted
                    AND my_org_unit_id=%s ORDER BY id FOR UPDATE""",
                    [list(map(str, amounts)), source["my_org_unit_id"]],
                )
                if {r[0] for r in cur.fetchall()} != set(amounts) or sum(
                    amounts.values()
                ) > source["amount"]:
                    return HttpResponseBadRequest(
                        "귀속회사와 원본 금액 범위를 확인하세요."
                    )
                cur.execute(
                    f"""SELECT t.id,t.{total}-COALESCE(sum(l.amount),0) FROM {table} t
                    LEFT JOIN fin.confirmed_links l ON l.{key}=t.id AND l.{kind}_id IS NOT NULL AND l.{kind}_id<>%s
                    WHERE t.id=ANY(%s::uuid[]) GROUP BY t.id""",
                    [record_id, list(map(str, amounts))],
                )
                if any(amounts[pk] > available for pk, available in cur.fetchall()):
                    return HttpResponseBadRequest(
                        "대상 건의 남은 배분 가능액을 초과했습니다."
                    )
            cur.execute(f"DELETE FROM fin.allocations WHERE {kind}_id=%s", [record_id])
            cur.execute(
                f"UPDATE {SOURCES[kind][0]} SET claim_id=NULL,payment_request_id=NULL,updated_at=now() WHERE id=%s",
                [record_id],
            )
            cur.executemany(
                f"INSERT INTO fin.allocations({kind}_id,{key},amount) VALUES(%s,%s,%s)",
                [(record_id, pk, value) for pk, value in amounts.items()],
            )
            return redirect("tenant:finance_reconcile", kind=kind, record_id=record_id)
    return render(
        request,
        "geoflow_ops/finance/reconcile.html",
        {
            "source": source,
            "kind": kind,
            "target": target,
            "options": options,
            "version": version,
            "assigned": sum(o["assigned"] for o in options),
            "can_write": can_edit_finance(request),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def claim_document(request, record_id, kind):
    write = request.method == "POST"
    alias = require_finance_access(request, write=write)
    if kind not in ("bill", "statement"):
        raise Http404
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        cur.execute(
            """SELECT c.title,c.claim_date AS date,k.name AS contract,p.name AS recipient,
            o.name AS issuer,o.biz_no,c.my_org_unit_id,c.supply_amount AS supply,c.vat_amount AS vat,c.total_amount AS total
            FROM fin.claims c LEFT JOIN ctr.contracts k ON k.id=c.contract_id
            LEFT JOIN ctr.partners p ON p.id=c.partner_id LEFT JOIN ops.my_org_units o ON o.id=c.my_org_unit_id
            WHERE c.id=%s AND NOT c.is_deleted FOR UPDATE OF c""",
            [record_id],
        )
        data = rows(cur)
        if not data:
            raise Http404
        company = data[0].pop("my_org_unit_id")
        accounts = []
        if kind == "bill":
            cur.execute(
                """SELECT id,bank_name,account_name,account_number,holder FROM fin.accounts
                WHERE my_org_unit_id=%s AND active AND NOT is_deleted ORDER BY bank_name,account_name""",
                [company],
            )
            accounts = rows(cur)
        if write and request.POST.get("account"):
            account = next(
                (a for a in accounts if str(a["id"]) == request.POST["account"]), None
            )
            if not account:
                return HttpResponseBadRequest("같은 귀속회사의 입금 계좌를 선택하세요.")
            data[0]["bank_account"] = {
                key: value for key, value in account.items() if key != "id"
            }
        if write:
            if request.POST.get("submit") and kind == "bill":
                cur.execute(
                    "UPDATE fin.claim_documents SET submitted_at=COALESCE(submitted_at,now()) WHERE claim_id=%s AND kind=%s",
                    [record_id, kind],
                )
            else:
                cur.execute(
                    """INSERT INTO fin.claim_documents(claim_id,kind,contents) VALUES(%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    [record_id, kind, json.dumps(data[0], default=str)],
                )
            return redirect(
                "tenant:finance_claim_document", record_id=record_id, kind=kind
            )
        cur.execute(
            "SELECT contents::text,issued_at,submitted_at FROM fin.claim_documents WHERE claim_id=%s AND kind=%s",
            [record_id, kind],
        )
        saved = cur.fetchone()
    return render(
        request,
        "geoflow_ops/finance/claim_document.html",
        {
            "data": json.loads(saved[0]) if saved else data[0],
            "kind": kind,
            "accounts": accounts,
            "issued": saved and saved[1],
            "submitted": saved and saved[2],
            "can_write": can_edit_finance(request),
        },
    )


def save_record(request, alias, kind, save):
    """Serialize ordinary edits with reconciliation and preserve existing links."""
    pk = request.POST.get("record_id")
    if not pk:
        if request.POST.get("claim_id") or request.POST.get("payment_request_id"):
            return HttpResponseBadRequest("저장한 원본의 연결 화면에서 확정하세요.")
        return save(request)
    try:
        pk = UUID(pk)
    except ValueError:
        return HttpResponseBadRequest("대상을 확인하세요.")
    is_source = kind in SOURCES
    table, amount, _, _ = (SOURCES if is_source else TARGETS)[kind]
    key = f"{kind}_id" if is_source else TARGETS[kind][3]
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        cur.execute(
            f"SELECT * FROM {table} WHERE id=%s AND NOT is_deleted FOR UPDATE", [pk]
        )
        records = rows(cur)
        if not records:
            raise Http404
        record = records[0]
        cur.execute(f"SELECT 1 FROM fin.confirmed_links WHERE {key}=%s LIMIT 1", [pk])
        linked = bool(cur.fetchone())
        if is_source:
            post = request.POST.copy()
            for field in ("claim_id", "payment_request_id"):
                post[field] = str(record[field] or "")
            request._post = post
        if linked:
            from .views_finance import _money

            value = (
                _money(request.POST.get("supply_amount"))
                + _money(request.POST.get("vat_amount"))
                if amount == "total_amount"
                else _money(request.POST.get("amount"))
            )
            fields = ["my_org_unit_id", "contract_id"]
            if is_source:
                fields.append(SOURCES[kind][2])
            if value != record[amount] or any(
                str(record[f] or "") != (request.POST.get(f) or "") for f in fields
            ):
                return HttpResponseBadRequest(
                    "금액·구분·귀속을 수정하려면 연결 내역에서 기존 배분을 먼저 해제하세요."
                )
        return save(request)


@login_required
@require_http_methods(["GET"])
def claim_detail(request, record_id):
    alias = require_finance_access(request)
    with connections[alias].cursor() as cur:
        cur.execute(
            """SELECT c.title,k.name AS contract,p.name AS partner,c.total_amount,
                c.expected_receipt_date AS expected,COALESCE(s.settled,0) AS received,
                c.total_amount-COALESCE(s.settled,0) AS balance
            FROM fin.claims c LEFT JOIN ctr.contracts k ON k.id=c.contract_id
            LEFT JOIN ctr.partners p ON p.id=c.partner_id LEFT JOIN fin.settlements s ON s.claim_id=c.id
            WHERE c.id=%s AND NOT c.is_deleted""",
            [record_id],
        )
        claims = rows(cur)
        if not claims:
            raise Http404
        cur.execute(
            """SELECT l.invoice_id,l.transaction_id,l.amount,
                COALESCE(i.issued_date,i.written_date,t.transaction_date) AS date,i.approval_no
            FROM fin.confirmed_links l LEFT JOIN fin.tax_invoices i ON i.id=l.invoice_id
            LEFT JOIN fin.transactions t ON t.id=l.transaction_id WHERE l.claim_id=%s
            ORDER BY date DESC NULLS LAST""",
            [record_id],
        )
        links = rows(cur)
        cur.execute(
            "SELECT kind,issued_at,submitted_at FROM fin.claim_documents WHERE claim_id=%s",
            [record_id],
        )
        documents = {r["kind"]: r for r in rows(cur)}
    return render(
        request,
        "geoflow_ops/finance/claim_detail.html",
        {
            "claim": claims[0],
            "id": record_id,
            "links": links,
            "documents": documents,
        },
    )
