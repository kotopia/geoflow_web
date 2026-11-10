"""Compact tenant overview; does not grant any new business permissions."""
import logging
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
        projects = list(visible_projects(request, alias).only('id', 'status'))
        contracts = []
        if context['can_view_contracts']:
            contracts = list(Contract.objects.using(alias).select_related('client', 'org_unit').only(
                'id', 'name', 'end_date', 'client__name', 'org_unit__label', 'org_unit__name',
            ))
        summaries = workflow_map(request, alias, contracts)
        cards = []
        if context['can_view_contracts']:
            cards.append(summary_card('계약', reverse('tenant:contract_list'), contracts, summaries))
        if context['can_view_projects']:
            cards.append(summary_card('프로젝트', reverse('tenant:project_list'), projects, summaries, projects=True))

        ending = filter_records(contracts, summaries, {'ending_days': context['days']}, today=context['today'])
        context.update(cards=cards, ending_count=len(ending), ending_rows=[{
            'id': contract.id,
            'name': contract.name,
            'client': contract.client.name if contract.client else None,
            'company': (contract.org_unit.label or contract.org_unit.name) if contract.org_unit else None,
            'end_date': contract.end_date,
            'days_left': (contract.end_date - context['today']).days,
            'status_label': summaries[str(contract.id)]['major_label'],
        } for contract in ending[:5]])
    except DatabaseError:
        logger.exception('Dashboard overview query failed')
        context['overview_error'] = True
    return render(request, 'geoflow_ops/home.html', context)
