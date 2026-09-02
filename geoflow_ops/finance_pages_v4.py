from __future__ import annotations

from decimal import Decimal

from django.db import connections
from django.http import JsonResponse
from django.shortcuts import render

from control.gf_authz.permissions import gf_has_perm, gf_has_role

from . import finance_pages_v2 as v2
from .services.entity_access import require_tenant_context


SESSION_KEY = "finance_org_filter"


def _selected_org(request, org_units):
    valid = {str(item["id"]): item for item in org_units}
    if "org" in request.GET:
        value = str(request.GET.get("org") or "").strip()
        if value and value.lower() not in {"all", "*"} and value in valid:
            request.session[SESSION_KEY] = value
            request.session.modified = True
            return value
        request.session.pop(SESSION_KEY, None)
        request.session.modified = True
        return ""
    value = str(request.session.get(SESSION_KEY) or "").strip()
    if value in valid:
        return value
    if value:
        request.session.pop(SESSION_KEY, None)
        request.session.modified = True
    return ""


def _filter_rows(rows, org_id):
    if not org_id:
        return rows
    return [row for row in rows if str(row.get("org_unit_id") or "") == str(org_id)]


def _dashboard_for_org(alias, org_id):
    if not org_id:
        return v2.legacy._dashboard(alias)
    in_code = v2.legacy._semantic_code(alias, "finance.value.transaction_type.in", "in")
    out_code = v2.legacy._semantic_code(alias, "finance.value.transaction_type.out", "out")
    cancelled_claim = v2.legacy._semantic_code(alias, "finance.value.claim_status.cancelled", "cancelled")
    cancelled_payment = v2.legacy._semantic_code(alias, "finance.value.payment_status.cancelled", "cancelled")
    with connections[alias].cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM ctr.contracts WHERE org_unit_id=%s", [org_id])
        contract_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(total_amount),0) FROM fin.claims WHERE is_deleted=false AND my_org_unit_id=%s AND COALESCE(status,'')<>%s", [org_id, cancelled_claim])
        claim_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE is_deleted=false AND my_org_unit_id=%s AND transaction_type=%s", [org_id, in_code])
        received_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.payment_requests WHERE is_deleted=false AND my_org_unit_id=%s AND COALESCE(status,'')<>%s", [org_id, cancelled_payment])
        payment_total = cur.fetchone()[0] or 0
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM fin.transactions WHERE is_deleted=false AND my_org_unit_id=%s AND transaction_type=%s", [org_id, out_code])
        paid_total = cur.fetchone()[0] or 0
    return {
        "contract_total": contract_total,
        "claim_total": claim_total,
        "received_total": received_total,
        "unclaimed_total": max(Decimal(contract_total) - Decimal(claim_total), Decimal("0")),
        "receivable_total": max(Decimal(claim_total) - Decimal(received_total), Decimal("0")),
        "payment_total": payment_total,
        "paid_total": paid_total,
        "payable_total": max(Decimal(payment_total) - Decimal(paid_total), Decimal("0")),
    }


def finance_section(request, section="dashboard"):
    alias = require_tenant_context(request)
    org_units, contracts, partners, accounts, cards = v2._master_data(alias)
    selected_org = _selected_org(request, org_units)
    claims, invoices, payments, transactions = v2._rows(alias)
    claims = _filter_rows(claims, selected_org)
    invoices = _filter_rows(invoices, selected_org)
    payments = _filter_rows(payments, selected_org)
    transactions = _filter_rows(transactions, selected_org)
    if selected_org:
        accounts = [a for a in accounts if str(a.get("org_unit_id") or "") == selected_org]
        cards = [c for c in cards if str(c.get("org_unit_id") or "") == selected_org]
    return render(request, "geoflow_ops/finance/finance_section.html", {
        "finance_section": section,
        "finance": _dashboard_for_org(alias, selected_org),
        "org_units": org_units,
        "finance_selected_org": selected_org,
        "contracts": contracts,
        "partners": partners,
        "accounts": accounts,
        "cards": cards,
        "claims": claims,
        "invoices": invoices,
        "payments": payments,
        "transactions": transactions,
        "trash": v2.legacy._trash(alias),
        "refs": v2._refs(alias),
        "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
        "can_hard_delete": gf_has_role(request, "tenant_admin"),
    })


def org_options(request):
    alias = require_tenant_context(request)
    org_units, _, _, _, _ = v2._master_data(alias)
    selected_org = _selected_org(request, org_units)
    return JsonResponse({
        "selected": selected_org,
        "options": [
            {"id": str(item["id"]), "name": item["name"], "type": item.get("type") or "", "biz_no": item.get("biz_no") or ""}
            for item in org_units
        ],
    })
