"""Compact tenant overview; does not grant any new business permissions."""
import logging
from datetime import date
from django.db import DatabaseError
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from control.gf_authz.permissions import gf_has_perm
from .models import Contract
from .services.entity_access import require_tenant_context
from .services.dashboard import visible_projects, workflow_map, filter_records, summary_card, period_days

logger = logging.getLogger(__name__)


def tenant_dashboard(request):
    alias = require_tenant_context(request)
    context = {'today': timezone.localdate(), 'days': period_days(request.GET.get('ending_days')),
               'can_view_projects': gf_has_perm(request, 'projects.view'),
               'can_view_contracts': gf_has_perm(request, 'contracts.view'),
               'can_view_directory': gf_has_perm(request, 'directory.view')}
    try:
        projects = list(visible_projects(request, alias).only('id','name','contract_id','contract__id','contract__end_date'))
        contracts = list(Contract.objects.using(alias).only('id','end_date')) if context['can_view_contracts'] else []
        all_contracts = {str(c.id): c for c in contracts}
        all_contracts.update({str(p.contract_id): p.contract for p in projects if p.contract_id})
        summaries = workflow_map(request, alias, all_contracts.values())
        cards = []
        if context['can_view_contracts']:
            cards.append(summary_card('계약', reverse('tenant:contract_list'), contracts, summaries))
        if context['can_view_projects']:
            cards.append(summary_card('프로젝트', reverse('tenant:project_list'), projects, summaries, projects=True))
        ending = filter_records(projects, summaries, {'ending_days': context['days']}, projects=True, today=context['today'])
        managers = _project_managers(alias, [str(p.id) for p in ending[:5]]) if context['can_view_directory'] else {}
        context.update(cards=cards, ending_count=len(ending), ending_rows=[{
            'manager': managers.get(str(p.id), '미지정') if context['can_view_directory'] else '열람 제한',
            'id': p.id, 'name': p.name or '프로젝트', 'end_date': p.contract.end_date,
            'days_left': (p.contract.end_date-context['today']).days,
            'workflow': summaries.get(str(p.contract_id), {}),
        } for p in ending[:5]])
    except DatabaseError:
        logger.exception('Dashboard overview query failed')
        context['overview_error'] = True
    return render(request, 'geoflow_ops/home.html', context)


def _project_managers(alias, ids):
    from django.db import connections
    if not ids:
        return {}
    with connections[alias].cursor() as cursor:
        cursor.execute("SELECT to_regclass('prj.project_members') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return {}
        cursor.execute("""SELECT m.project_id::text, COALESCE(e.name, m.invite_name, '')
            FROM prj.project_members m LEFT JOIN hr.employee_profile e
              ON e.id=m.employee_id AND e.is_deleted=false
            WHERE m.project_id=ANY(%s::uuid[]) AND m.membership_status='active'
              AND m.member_role='project_manager' ORDER BY m.project_id, m.id""", [ids])
        names = {}
        for pid, name in cursor.fetchall():
            if name:
                names.setdefault(pid, []).append(name)
        return {pid: ', '.join(values) for pid, values in names.items()}
