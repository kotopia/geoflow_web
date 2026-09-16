from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from control import views_gis_admin
from control.services import gis_admin
from geoflow_ops.gis import form_definition_views


class FormAdminAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.rf=RequestFactory()

    def request(self,method="get"):
        request=getattr(self.rf,method)("/",{"action":"item","tenant":str(uuid4())})
        request.session={}
        request.user=SimpleNamespace(is_authenticated=True)
        return request

    def test_no_identity_cannot_access_tenant_catalog(self):
        with patch("control.decorators.lookup_user_id_from_request",return_value=None), patch.object(views_gis_admin,"tenant_cursor") as tenant:
            response=views_gis_admin.dashboard(self.request())
        self.assertEqual(response.status_code,403)
        tenant.assert_not_called()

    def test_nonstaff_cannot_write(self):
        central=MagicMock()
        central.__getitem__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
        with patch("control.decorators.lookup_user_id_from_request",return_value=str(uuid4())), patch("control.decorators.connections",central), patch.object(views_gis_admin,"tenant_cursor") as tenant:
            response=views_gis_admin.dashboard(self.request("post"))
        self.assertEqual(response.status_code,403)
        tenant.assert_not_called()

    def test_project_viewer_cannot_mutate_definition(self):
        project=SimpleNamespace(id=uuid4())
        with patch.object(form_definition_views,"_require_gis_view",return_value="test_tenant"), patch.object(form_definition_views,"_require_project_gis_access",return_value=(project,{})), patch.object(form_definition_views,"project_access_policy") as policy, patch.object(form_definition_views,"connections") as db:
            policy.return_value.can_edit_project.return_value=False
            with self.assertRaises(PermissionDenied):
                form_definition_views.project_configuration(self.request("post"),project.id)
            db.__getitem__.assert_not_called()

    def test_api_project_denial_precedes_definition_read(self):
        with patch.object(form_definition_views,"_require_qgis_context",return_value="test_tenant"), patch.object(form_definition_views,"_require_project",side_effect=PermissionDenied), patch.object(form_definition_views,"connections") as db:
            with self.assertRaises(PermissionDenied):
                form_definition_views.definition_api(self.request(),uuid4())
            db.__getitem__.assert_not_called()

    def test_unrecognized_write_is_rejected(self):
        cur=MagicMock()
        with patch.object(views_gis_admin.definitions,"ready",return_value=True):
            with self.assertRaises(views_gis_admin.definitions.DefinitionError):
                views_gis_admin._mutate(cur,{"action":"delete_all"})
        cur.execute.assert_not_called()

    def config(self):
        return SimpleNamespace(db_alias="tenant_test",db_name="tenant_test",db_host="localhost",db_port=5432,
                               db_user="test",db_password="test-reference")

    def test_admin_connection_uses_resolver_and_rolls_back_on_error(self):
        conn=MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value=("tenant_test",)
        with patch.object(gis_admin,"GroupDBConfig") as configs, patch.object(gis_admin,"resolve_tenant_db_password",return_value="test-secret") as resolver, patch.object(gis_admin.psycopg2,"connect",return_value=conn):
            configs.objects.using.return_value.select_related.return_value.filter.return_value.first.return_value=self.config()
            with self.assertRaises(ValueError):
                with gis_admin.tenant_cursor(uuid4(),write=True):
                    raise ValueError("validation failed")
            resolver.assert_called_once_with("test-reference")
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_read_only_admin_request_never_commits(self):
        conn=MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value=("tenant_test",)
        with patch.object(gis_admin,"GroupDBConfig") as configs, patch.object(gis_admin,"resolve_tenant_db_password",return_value="test-secret"), patch.object(gis_admin.psycopg2,"connect",return_value=conn):
            configs.objects.using.return_value.select_related.return_value.filter.return_value.first.return_value=self.config()
            with gis_admin.tenant_cursor(uuid4()):
                pass
        conn.set_session.assert_called_once_with(readonly=True,autocommit=False)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
