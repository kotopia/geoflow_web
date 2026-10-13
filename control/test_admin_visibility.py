from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.template import Context, Engine
from django.test import RequestFactory, SimpleTestCase

from control import views_groups_admin, views_users_admin
from control.services import service_menu_visibility as menus
from control.services.central_account_erasure_service import SqlCentralAccountErasureRepository
from geoflow_ops.services.finance_access import can_edit_finance, can_view_finance


class AdminVisibilityTests(SimpleTestCase):
    def request(self, **query):
        request = RequestFactory().get("/", query)
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {"scope": "tenant", "tenant_db_alias": "tenant-a", "group_id": str(uuid4())}
        request._gf_perms_cache = {"contracts.view", "contracts.edit"}
        return request

    def test_group_default_hides_deleted_but_keeps_inactive(self):
        rows = [("live", "", "", "inactive", None, None, "", False),
                ("deleted", "", "", "active", None, None, "", True)]
        with patch.object(views_groups_admin.C, "list_groups_admin", return_value=rows), patch.object(views_groups_admin, "render", side_effect=lambda r, t, c: c):
            self.assertEqual(unwrap(views_groups_admin.group_list_admin)(self.request())["rows"], rows[:1])
            self.assertEqual(unwrap(views_groups_admin.group_list_admin)(self.request(include_deleted="1"))["rows"], rows)

    def test_user_filter_precedes_limit_and_never_uses_inactive_as_deleted(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("id", "pending@example.invalid", False, False, None, 0, False)]
        with patch("control.services.central_repo._column_exists", return_value=True), patch.object(views_users_admin, "connections", {"default": connection}), patch.object(views_users_admin, "render", side_effect=lambda r,t,c:c):
            context = unwrap(views_users_admin.users_list_admin)(self.request())
            sql = cursor.execute.call_args.args[0]
            self.assertLess(sql.index("WHERE u.deleted_at IS NULL"), sql.index("LIMIT"))
            self.assertNotIn("WHERE u.is_active", sql)
            self.assertEqual(len(context["users"]), 1)
            unwrap(views_users_admin.users_list_admin)(self.request(include_deleted="1"))
            self.assertNotIn("WHERE u.deleted_at IS NULL", cursor.execute.call_args.args[0])

    def test_anonymization_records_explicit_marker_with_existing_identity_cleanup(self):
        cursor = MagicMock(rowcount=1)
        with patch("control.services.central_repo._column_exists", return_value=True):
            result = SqlCentralAccountErasureRepository()._anonymize(cursor, user_id=str(uuid4()), unusable_password_hash="!disabled")
        sql, params = cursor.execute.call_args.args
        self.assertEqual(result.mode, "anonymized")
        self.assertIn("deleted_at=COALESCE(deleted_at, now())", sql)
        self.assertIn("is_active=FALSE", sql)
        self.assertEqual(params[1], "!disabled")

    def test_no_settings_row_and_pre_migration_preserve_menu_defaults(self):
        self.assertTrue(all(menus.get_service_menus(uuid4(), available=False).values()))
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with patch.object(menus, "connections", {"default": connection}):
            self.assertTrue(all(menus.get_service_menus(uuid4(), available=True).values()))

    def test_group_switch_reloads_and_preferences_never_grant_finance(self):
        request = self.request()
        with patch("control.middleware.current_db_alias", return_value="tenant-a"), patch.object(menus, "get_service_menus", side_effect=[dict(bids=True,gis=False,finance=True),dict(bids=False,gis=True,finance=False)]) as read:
            self.assertTrue(menus.service_menu_context(request)["service_menus"]["finance"])
            self.assertFalse(can_view_finance(request))
            self.assertFalse(can_edit_finance(request))
            menus.service_menu_context(request)
            self.assertEqual(read.call_count, 1)
            request.session["group_id"] = str(uuid4())
            self.assertFalse(menus.service_menu_context(request)["service_menus"]["finance"])
            self.assertEqual(read.call_count, 2)
            request._gf_perms_cache.update({"finance.view", "finance.edit"})
            self.assertTrue(can_edit_finance(request))

    def test_missing_or_mismatched_tenant_never_loads_group_preferences(self):
        request = self.request()
        with patch("control.middleware.current_db_alias", return_value="other-tenant"), patch.object(menus, "get_service_menus") as read:
            self.assertFalse(any(menus.service_menu_context(request)["service_menus"].values()))
            read.assert_not_called()

    def test_settings_write_is_one_central_row_without_permission_mutation(self):
        connection = MagicMock()
        group = uuid4()
        with patch.object(menus, "connections", {"default": connection}):
            menus.save_service_menus(group, dict(bids=False,gis=True,finance=False))
        sql, params = connection.cursor.return_value.__enter__.return_value.execute.call_args.args
        self.assertEqual(params, [str(group), False, True, False])
        self.assertIn("ON CONFLICT (group_id)", sql)
        self.assertNotIn("role_permissions", sql)

    def test_non_admin_cannot_change_group_menu_settings(self):
        with patch("control.decorators.lookup_user_id_from_request", return_value=None), patch.object(menus, "save_service_menus") as save:
            self.assertEqual(views_groups_admin.group_edit_admin(self.request(), uuid4()).status_code, 403)
            save.assert_not_called()

    def test_sidebar_requires_both_menu_preference_and_finance_permission(self):
        template = Engine(libraries={
            "acl_tags": "control.templatetags.acl_tags",
            "static": "django.templatetags.static",
        }).from_string((Path(__file__).resolve().parents[1] / "geoflow_ops/templates/geoflow_ops/partials/sidebar.html").read_text())
        request = self.request()
        for preference, permission, expected in ((True, False, False), (False, True, False), (True, True, True)):
            request._gf_perms_cache = {"finance.view"} if permission else set()
            with patch("django.urls.reverse", return_value="/"):
                rendered = template.render(Context({"request": request, "service_menus": dict(finance=preference, bids=False, gis=False)}))
            self.assertEqual('id="finance-menu"' in rendered, expected)
            self.assertNotIn('id="gis-menu"', rendered)
            self.assertNotIn('id="bid-menu"', rendered)

    def test_group_save_preserves_preferences_from_old_forms(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (str(uuid4()),)
        request = RequestFactory().post("/", {"name": "Example", "status": "active"})
        with patch.object(menus, "settings_available", return_value=True), patch.object(views_groups_admin, "connections", {"default": connection}), patch.object(views_groups_admin.transaction, "atomic"), patch.object(menus, "save_service_menus") as save, patch.object(views_groups_admin.messages, "success"), patch.object(views_groups_admin, "redirect", return_value=None):
            unwrap(views_groups_admin.group_edit_admin)(request, uuid4())
            save.assert_not_called()
            request.POST = request.POST.copy()
            request.POST["service_menus_present"] = "1"
            request.POST["service_menu_gis"] = "on"
            unwrap(views_groups_admin.group_edit_admin)(request, uuid4())
            self.assertEqual(save.call_args.args[1], dict(bids=False, gis=True, finance=False))
