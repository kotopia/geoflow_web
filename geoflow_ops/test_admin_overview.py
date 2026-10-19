from datetime import date, timedelta
from types import SimpleNamespace as Row
from unittest.mock import Mock, patch
from django.test import SimpleTestCase, RequestFactory
from geoflow_ops.services.dashboard import filter_records, summary_card, visible_projects
from geoflow_ops.views_calendar import calendar_events


class OverviewTests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026,10,19)
        self.projects = []
        self.states = {}
        for i, offset in enumerate([-1,0,30,31,50,51,None]):
            contract = Row(id=i, end_date=self.today+timedelta(days=offset) if offset is not None else None)
            self.projects.append(Row(pk=i, contract=contract))
            self.states[str(i)] = {'filter_key': 'active', 'is_complete': False}

    def test_boundaries_sort_missing_past_and_completed(self):
        params = {'ending_days':'30'}
        self.assertEqual([p.pk for p in filter_records(self.projects[::-1], self.states, params, projects=True, today=self.today)], [1,2])
        self.states['2']['is_complete'] = True
        self.assertEqual([p.pk for p in filter_records(self.projects, self.states, {'ending_days':'50'}, projects=True, today=self.today)], [1,3,4])

    def test_contract_date_is_authoritative_and_edit_reflected(self):
        self.projects[0].end_date = self.today
        self.projects[0].contract.end_date = self.today+timedelta(days=50)
        self.assertEqual(len(filter_records(self.projects[:1], self.states, {'ending_days':30}, projects=True,today=self.today)),0)
        self.projects[0].contract.end_date = self.today
        self.assertEqual(len(filter_records(self.projects[:1], self.states, {'ending_days':30}, projects=True,today=self.today)),1)

    def test_card_links_match_same_list_filter_without_merging_other_states(self):
        self.states['1']={'filter_key':'pause','is_complete':False}
        self.states['2']={'filter_key':'complete','is_complete':True}
        card=summary_card('프로젝트','/projects/',self.projects,self.states,projects=True)
        for metric in card['metrics']:
            if metric['url']:
                key=metric['url'].split('overview_status=')[1]
                self.assertEqual(metric['value'],len(filter_records(self.projects,self.states,{'overview_status':key},projects=True)))
        self.assertEqual([m['label'] for m in card['metrics']], ['전체', '진행', '완료'])
        self.assertEqual(card['other'],1)

    @patch('geoflow_ops.services.dashboard.Project')
    @patch('geoflow_ops.services.dashboard.project_access_policy')
    @patch('geoflow_ops.services.dashboard.gf_has_perm')
    def test_visibility_uses_current_alias_and_memberships(self, perm, policy, model):
        query=model.objects.using.return_value.select_related.return_value
        perm.return_value=False
        visible_projects(object(),'tenant_a')
        query.none.assert_called_once()
        policy.assert_not_called()
        perm.return_value=True
        policy.return_value.visible_project_ids.return_value=['allowed']
        visible_projects(object(),'tenant_b')
        model.objects.using.assert_called_with('tenant_b')
        query.filter.assert_called_with(pk__in=['allowed'])

    @patch('geoflow_ops.views_calendar.require_tenant_context',return_value='tenant_a')
    def test_invalid_month_rejected_before_query(self, context):
        request=RequestFactory().get('/calendar/events/',{'overview':'1','start':'2026-02-31','end':'2026-04-01'})
        request.user=Row(is_authenticated=True)
        self.assertEqual(calendar_events(request).status_code,400)

    def test_calendar_keeps_tenant_and_event_scope_and_hides_employee_ids(self):
        import json
        event = Row(id='event1', title='Allowed', event_type='work_report',
                    scope_type='project', scope_id='project1', stage='execution',
                    assignee_employee_id='private-employee', status='done',
                    due_at=self.today, occurred_at=self.today, payload={})
        denied = Row(**{**event.__dict__, 'id':'denied'})
        request = RequestFactory().get('/calendar/events/', {
            'overview':'1', 'start':'2026-10-01', 'end':'2026-11-01'})
        request.user=Row(is_authenticated=True)
        with patch('geoflow_ops.views_calendar.require_tenant_context', return_value='tenant_b'), \
             patch('geoflow_ops.views_calendar.ProcessEvent') as model, \
             patch('geoflow_ops.views_calendar.can_read_event', side_effect=lambda r,a,e:e.id=='event1') as access, \
             patch('geoflow_ops.views_calendar._display_policy_from_payload', return_value={'calendar_enabled':True,'end_at':None}), \
             patch('geoflow_ops.views_calendar.reverse', return_value='/project/'), \
             patch('geoflow_ops.views_calendar.Contract') as contracts, \
             patch('geoflow_ops.views_calendar.Project') as projects, \
             patch('geoflow_ops.views_calendar.gf_has_perm', return_value=False):
            model.objects.using.return_value.filter.return_value.exclude.return_value.order_by.return_value.__getitem__.return_value=[event,denied]
            contracts.objects.using.return_value.filter.return_value.values_list.return_value=[]
            projects.objects.using.return_value.filter.return_value.values_list.return_value=[('project1','Allowed project')]
            response=calendar_events(request)
            rows=json.loads(response.content)
            self.assertEqual([r['id'] for r in rows],['event1'])
            self.assertEqual(rows[0]['extendedProps']['assignee'],'열람 제한')
            self.assertNotIn('private-employee',response.content.decode())
            self.assertTrue(rows[0]['extendedProps']['history'])
            model.objects.using.assert_called_once_with('tenant_b')
            self.assertEqual(access.call_count,2)
            projects.objects.using.return_value.filter.assert_called_once_with(pk__in=['project1'])
            self.assertEqual(response['Cache-Control'],'private, no-store')
