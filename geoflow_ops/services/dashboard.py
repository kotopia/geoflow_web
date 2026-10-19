"""Read-only overview using the same lifecycle and visibility as existing lists."""
from collections import Counter
from datetime import timedelta
from django.utils import timezone
from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from .project_access import project_access_policy
from .workflow_state import contract_workflow_summaries


def period_days(value):
    return 50 if str(value) == '50' else 30


def visible_projects(request, alias):
    qs = Project.objects.using(alias).select_related('contract')
    if not gf_has_perm(request, 'projects.view'):
        return qs.none()
    ids = project_access_policy(request, alias).visible_project_ids()
    return qs if ids is None else qs.filter(pk__in=ids)


def workflow_map(request, alias, contracts):
    # One shared batch for both cards and the due-project table.
    return contract_workflow_summaries(alias, contracts, request=request)


def filter_records(rows, summaries, params, *, projects=False, today=None):
    """Dashboard links and the destination list use this exact predicate."""
    today = today or timezone.localdate()
    selected = params.get('overview_status')
    due = params.get('ending_days') if projects else None
    result = []
    for row in rows:
        contract = row.contract if projects else row
        state = summaries.get(str(contract.id), {}) if contract else {}
        if selected in {'active', 'complete', 'planned', 'pause'} and state.get('filter_key') != selected:
            continue
        if due:
            end = contract.end_date if contract else None
            if not end or state.get('is_complete') or not today <= end <= today + timedelta(days=period_days(due)):
                continue
        result.append(row)
    if due:
        result.sort(key=lambda row: (row.contract.end_date, str(row.pk)))
    return result


def summary_card(label, url, rows, summaries, *, projects=False):
    counts = Counter()
    for row in rows:
        contract = row.contract if projects else row
        state = summaries.get(str(contract.id), {}) if contract else {}
        counts[state.get('filter_key', 'other')] += 1
    metrics = []
    for key, name in [('all', '전체'), ('active', '진행'), ('complete', '완료')]:
        metrics.append({'label': name, 'value': len(rows) if key == 'all' else counts[key],
                        'url': url + '?overview=1&overview_status=' + key})
    return {'label': label, 'metrics': metrics, 'other': sum(v for k,v in counts.items() if k not in {'active','complete'})}
