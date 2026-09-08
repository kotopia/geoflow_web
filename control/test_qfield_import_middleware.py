from types import SimpleNamespace
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from control.middleware import (
    TenantMembershipFreshnessGuardMiddleware, TenantMiddleware,
    _is_native_qfield_import_request,
)
from geoflow_ops.gis.qfield_auth import hydrate_qfield_package_import_request


class QFieldImportMiddlewareTests(SimpleTestCase):
    path = '/gis/projects/11111111-1111-4111-8111-111111111401/api/qfield/package-import/'

    def request(self, path=None, token='invalid-ticket'):
        request = RequestFactory().get(path or self.path, {'token': token})
        request.session = {'tenant_db_alias': 'cheonan_db', 'group_id': 'old-group'}
        request.user = SimpleNamespace(is_authenticated=False)
        return request

    def test_import_defers_stale_browser_session_to_token_validator(self):
        request = self.request()
        def view(req):
            self.assertIsNone(hydrate_qfield_package_import_request(
                req, project_id='11111111-1111-4111-8111-111111111401'))
            return JsonResponse({'error': 'invalid_qfield_package_import'}, status=401)
        stack = TenantMembershipFreshnessGuardMiddleware(TenantMiddleware(view))
        with patch('control.middleware.ensure_tenant_connection_for_session') as connect:
            response = stack(request)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)
        connect.assert_not_called()

    def test_only_exact_import_get_with_token_is_deferred(self):
        self.assertTrue(_is_native_qfield_import_request(self.request()))
        self.assertFalse(_is_native_qfield_import_request(self.request(token='')))
        for path in [self.path + 'extra/', self.path.replace('package-import', 'package'),
                     self.path.replace('package-import', 'install-status'),
                     self.path.replace('package-import', 'changesets'), '/contracts/']:
            self.assertFalse(_is_native_qfield_import_request(self.request(path)))
        request = self.request()
        request.method = 'POST'
        self.assertFalse(_is_native_qfield_import_request(request))
