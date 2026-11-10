"""Read-only overview using the same lifecycle and visibility as existing lists."""
from collections import Counter
from datetime import timedelta
from django.utils import timezone
from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from .project_access import project_access_policy
from .project_status import status_key
from .workflow_state import contract_workflow_summaries


def period_days(value):
    return 50 if str(value) == '50' else 30


def visible_projects(request, alias):
    qs = Project.objects.using(alias)
    if not gf_has_perm(request, 'projects.view'):
        return qs.none()
    ids = project_access_policy(request, alias).visible_project_ids()
    return qs if ids is None else qs.filter(pk__in=ids)


def workflow_map(request, alias, contracts):
    # The contract card, deadlines and list share the event-derived workflow.
    return contract_workflow_summaries(alias, contracts, request=request)


def _record_state(row, summaries, projects):
    if projects:
        return {'filter_key': status_key(row.status), 'is_complete': row.status == 'complete'}
    return summaries.get(str(row.id), {})


def filter_records(rows, summaries, params, *, projects=False, today=None):
    """Dashboard links and the destination list use this exact predicate."""
    today = today or timezone.localdate()
    selected = params.get('overview_status')
    due = params.get('ending_days')
    last_day = today + timedelta(days=period_days(due)) if due else None
    result = []
    for row in rows:
        state = _record_state(row, summaries, projects)
        if selected in {'active', 'complete', 'planned', 'pause'} and state.get('filter_key') != selected:
            continue
        if due:
            end = row.end_date
            if not end or state.get('is_complete') or not today <= end <= last_day:
                continue
        result.append(row)
    if due:
        result.sort(key=lambda row: (row.end_date, str(row.pk)))
    return result


def summary_card(label, url, rows, summaries, *, projects=False):
    counts = Counter()
    for row in rows:
        state = _record_state(row, summaries, projects)
        counts[state.get('filter_key', 'other')] += 1
    metrics = []
    for key, name in [('all', '전체'), ('active', '진행'), ('complete', '완료')]:
        metrics.append({'label': name, 'value': len(rows) if key == 'all' else counts[key],
                        'url': url + '?overview=1&overview_status=' + key})
    return {'label': label, 'metrics': metrics, 'other': sum(v for k,v in counts.items() if k not in {'active','complete'})}
