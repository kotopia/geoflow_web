"""DB-free request boundary tests; business deletes remain covered by PostGIS rehearsal."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, RequestFactory
from . import survey_views, reference_views


class SurveyInspectionContractTests(SimpleTestCase):
    def test_legacy_and_unknown_delete_requests_never_execute(self):
        for query in ('?mode=source_only', '?mode=source_and_points', '?mode=unknown'):
            request = RequestFactory().delete('/'+query)
            request.user = SimpleNamespace(is_authenticated=True)
            with patch.object(survey_views, '_context', return_value=('tenant', SimpleNamespace(id='project'), {})), patch.object(survey_views, 'delete_survey_source') as delete:
                response = survey_views.project_survey_source_api(request, 'project', 'source')
                self.assertIn(response.status_code, (400, 409))
                delete.assert_not_called()

    def test_acknowledged_delete_preserves_existing_service_boundary(self):
        request = RequestFactory().delete('/?mode=source_and_points&deletion_policy=source_and_points_soft_delete_v1')
        request.user = SimpleNamespace(is_authenticated=True)
        with patch.object(survey_views, '_context', return_value=('tenant', SimpleNamespace(id='project'), {})), patch.object(survey_views, '_actor_ref', return_value='actor'), patch.object(survey_views, 'delete_survey_source', return_value={'ok': True}) as delete:
            self.assertEqual(survey_views.project_survey_source_api(request, 'project', 'source').status_code, 200)
            delete.assert_called_once_with('tenant', project_id='project', source_id='source', actor_ref='actor')

    def test_points_truncation_and_retained_filter_are_explicit(self):
        request = RequestFactory().get('/?source_state=retained&source_id=source')
        request.user = SimpleNamespace(is_authenticated=True)
        cursor = MagicMock()
        cursor.fetchall.return_value = [tuple([None]*28)] * 5001
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(survey_views, '_context', return_value=('tenant', SimpleNamespace(id='project'), {})), patch.object(survey_views, 'connections', {'tenant': conn}):
            response = survey_views.project_survey_points_api(request, 'project')
        payload = json.loads(response.content)
        self.assertTrue(payload['truncated'])
        self.assertEqual(len(payload['points']), 5000)
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params, ['project', 'source'])
        self.assertIn('s.deleted_at IS NULL', sql)
        self.assertIn('src.id IS NULL OR src.deleted_at IS NOT NULL', sql)
        self.assertIn('src.project_id=s.project_id', sql)

    def test_l2_is_resolved_from_project_plan_not_survey(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [('l2-id', '업무')]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(reference_views, 'project_reference_catalog', return_value={'ok': True}), patch.object(reference_views, 'connections', {'default': conn}):
            response = reference_views._catalog_response('tenant', {'capabilities': [
                {'catalog_level': 2, 'catalog_item_id': 'l2-id'},
                {'catalog_level': 3, 'catalog_item_id': 'excluded'}]})
        self.assertEqual(json.loads(response.content)['business_types'], [{'code':'l2-id','label':'업무'}])
        self.assertEqual(cursor.execute.call_args.args[1], [['l2-id']])
