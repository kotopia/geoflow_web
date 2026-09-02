from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.shortcuts import render
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from .services.entity_access import require_tenant_context


@login_required
@require_GET
def finance_documents(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    with connections[alias].cursor() as cur:
        cur.execute("""
            SELECT i.id::text, COALESCE(i.issued_date,i.written_date), i.invoice_type,
                   COALESCE(p.name,i.source_partner_name,''), COALESCE(c.name,''), i.total_amount,
                   i.attachment_id::text, COALESCE(a.original_name,'')
              FROM fin.tax_invoices i
              LEFT JOIN ctr.partners p ON p.id=i.partner_id
              LEFT JOIN ctr.contracts c ON c.id=i.contract_id
              LEFT JOIN ops.attachments a ON a.id=i.attachment_id AND a.active=true AND a.is_deleted=false
             WHERE i.is_deleted=false
             ORDER BY COALESCE(i.issued_date,i.written_date) DESC NULLS LAST, i.created_at DESC
             LIMIT 500
        """)
        invoices = [{
            "id":r[0],"date":r[1],"type":r[2],"partner":r[3],"contract":r[4],"amount":r[5],
            "attachment_id":r[6] or "","attachment_name":r[7] or ""
        } for r in cur.fetchall()]
        cur.execute("""
            SELECT t.id::text, t.transaction_date, t.transaction_type, COALESCE(p.name,t.source_partner_name,''),
                   COALESCE(c.name,''), t.amount, t.evidence_attachment_id::text, COALESCE(a.original_name,'')
              FROM fin.transactions t
              LEFT JOIN ctr.partners p ON p.id=t.partner_id
              LEFT JOIN ctr.contracts c ON c.id=t.contract_id
              LEFT JOIN ops.attachments a ON a.id=t.evidence_attachment_id AND a.active=true AND a.is_deleted=false
             WHERE t.is_deleted=false
             ORDER BY t.transaction_date DESC, t.created_at DESC
             LIMIT 500
        """)
        transactions = [{
            "id":r[0],"date":r[1],"type":r[2],"partner":r[3],"contract":r[4],"amount":r[5],
            "attachment_id":r[6] or "","attachment_name":r[7] or ""
        } for r in cur.fetchall()]
    return render(request, "geoflow_ops/finance/finance_documents.html", {
        "invoices": invoices,
        "transactions": transactions,
        "can_write": gf_has_perm(request, "contracts.edit") or gf_has_perm(request, "contracts.create"),
    })
