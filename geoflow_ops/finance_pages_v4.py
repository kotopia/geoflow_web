from __future__ import annotations

from django.core.paginator import Paginator

from django.db import connections
from django.http import JsonResponse
from django.shortcuts import render

from control.gf_authz.permissions import gf_has_role

from . import finance_pages_v2 as v2
from .services.entity_access import require_tenant_context
from .services.finance_access import can_edit_finance


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


def balance_totals(alias, org_id="", contract_id=""):
    totals = {}
    for key, table, amount, link, cancelled in (
        ("receivable", "claims", "total_amount", "claim_id", "claim_status"),
        ("payable", "payment_requests", "amount", "payment_request_id", "payment_status"),
    ):
        code = v2.legacy._semantic_code(alias, f"finance.value.{cancelled}.cancelled", "cancelled")
        with connections[alias].cursor() as cur:
            cur.execute(f"""SELECT COALESCE(sum(greatest(t.{amount}-coalesce(s.settled,0),0)),0)
                FROM fin.{table} t LEFT JOIN fin.settlements s ON s.{link}=t.id
                WHERE NOT t.is_deleted AND t.status IS DISTINCT FROM %s
                AND (%s='' OR t.my_org_unit_id::text=%s) AND (%s='' OR t.contract_id::text=%s)""",
                [code,org_id,org_id,contract_id,contract_id])
            totals[key] = cur.fetchone()[0]
    return totals


def finance_section(request, section="claims"):
    alias = require_tenant_context(request)
    org_units, contracts, partners, accounts, cards = v2._master_data(alias)
    selected_org = _selected_org(request, org_units)
    claims, invoices, payments, transactions = v2._rows(alias, section)
    claims = _filter_rows(claims, selected_org)
    invoices = _filter_rows(invoices, selected_org)
    payments = _filter_rows(payments, selected_org)
    transactions = _filter_rows(transactions, selected_org)
    outstanding = request.GET.get("outstanding") == "1"
    if outstanding:
        for key, items in (("claim_status", claims), ("payment_status", payments)):
            cancelled = v2.legacy._semantic_code(alias, f"finance.value.{key}.cancelled", "cancelled")
            items[:] = [r for r in items if r["balance"] > 0 and r["status"] != cancelled]
    if request.GET.get("id"):
        invoices = [r for r in invoices if r["id"] == request.GET["id"]]
    if selected_org:
        accounts = [a for a in accounts if str(a.get("org_unit_id") or "") == selected_org]
        cards = [c for c in cards if str(c.get("org_unit_id") or "") == selected_org]
    listing = {"claims":claims, "payments":payments, "ledger":transactions, "invoices":invoices}
    size = 30 if request.GET.get("size") == "30" else 15
    page = Paginator(listing[section], size).get_page(request.GET.get("page"))
    listing[section] = page.object_list
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "geoflow_ops/finance/finance_section.html", {
        "finance_section": section,
        "outstanding": outstanding,
        "org_units": org_units,
        "finance_selected_org": selected_org,
        "contracts": contracts,
        "partners": partners,
        "accounts": accounts,
        "cards": cards,
        **listing,
        "page":page,
        "query":query.urlencode(),
        "refs": v2._refs(alias),
        "can_write": can_edit_finance(request),
        "can_hard_delete": can_edit_finance(request) and gf_has_role(request, "tenant_admin"),
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
