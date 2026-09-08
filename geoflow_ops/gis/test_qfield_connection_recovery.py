from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from . import qfield_connection_views as views
from .qfield_auth import parse_qfield_claim_token
from django.test import override_settings
import json


class ConnectionRecoveryTests(TestCase):
    def request(self):
        request = RequestFactory().get('/recovery/', HTTP_HOST='192.168.0.6:8000')
        request.user = SimpleNamespace(is_authenticated=True, pk=1, email='test@example.invalid')
        request.session = {'group_id': 'g'}
        return request

    def test_permission_denied(self):
        with patch.object(views, 'require_tenant_context', return_value='tenant'), patch.object(views, 'gf_has_perm', return_value=False):
            with self.assertRaises(PermissionDenied):
                views.qfield_connection_recovery_api(self.request(), '11111111-1111-4111-8111-111111111401')

    @override_settings(DEBUG=True, ALLOWED_HOSTS=['192.168.0.6'])
    def test_claim_is_scoped_and_response_not_cached(self):
        import os
        project = SimpleNamespace(id='11111111-1111-4111-8111-111111111401')
        policy = SimpleNamespace(can_webgis_write=lambda _: True)
        with patch.dict(os.environ, {'GEOFLOW_DEV_RUNTIME_STRICT':'1'}), patch.object(views, 'require_tenant_context', return_value='tenant'), patch.object(views, 'gf_has_perm', return_value=True), patch.object(views, '_project_identity', return_value=(project,dict(project_id='11111111-1111-4111-8111-111111111401',alias='tenant',group_id='g',user_id='1',email='test@example.invalid'))), patch.object(views, 'changeset_runtime_enabled', return_value=True):
            response = views.qfield_connection_recovery_api(self.request(), '11111111-1111-4111-8111-111111111401')
            data = json.loads(response.content)
            claim = parse_qfield_claim_token(data['claim_token'], project_id='11111111-1111-4111-8111-111111111401')
            self.assertEqual(claim['alias'], 'tenant')
            self.assertEqual(claim['user_id'], '1')
            self.assertIsNone(parse_qfield_claim_token(data['claim_token'], project_id='other'))
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertNotIn('auth', data)

    def test_disabled_outside_dev(self):
        with patch.object(views, 'require_tenant_context', return_value='tenant'), patch.object(views, 'gf_has_perm', return_value=True), patch.object(views, 'qfield_ticket_runtime_enabled', return_value=False):
            self.assertEqual(views.qfield_connection_recovery_api(self.request(), '11111111-1111-4111-8111-111111111401').status_code,403)
