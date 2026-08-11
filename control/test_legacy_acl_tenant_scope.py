import unittest
from types import SimpleNamespace
from unittest.mock import patch

from control.templatetags import acl_tags


class LegacyAclTenantScopeTests(unittest.TestCase):
    def _request(self, session, *, user_uuid="user-a"):
        return SimpleNamespace(session=session, _user_uuid=user_uuid)

    def _settings(self):
        return SimpleNamespace(CENTRAL_DB_ALIAS="default")

    def test_central_scope_rejects_stale_tenant_permission_cache(self):
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "default",
                "scope": "central",
                "perms": ["directory.edit"],
            }
        )
        with patch.object(acl_tags, "settings", self._settings()), patch.object(
            acl_tags.C,
            "list_permissions_for_user_in_group",
            side_effect=AssertionError("central scope must not query tenant permissions"),
        ):
            self.assertFalse(acl_tags.has_perm({"request": request}, "directory.edit"))

    def test_non_tenant_scope_marker_rejects_noncentral_alias(self):
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "cheonan_db",
                "scope": "central",
                "perms": ["directory.edit"],
            }
        )
        with patch.object(acl_tags, "settings", self._settings()):
            self.assertFalse(acl_tags.has_perm({"request": request}, "directory.edit"))

    def test_missing_tenant_alias_rejects_stale_group_and_permission_cache(self):
        request = self._request(
            {
                "group_id": "group-a",
                "scope": "tenant",
                "perms": ["directory.edit"],
            }
        )
        with patch.object(acl_tags, "settings", self._settings()):
            self.assertFalse(acl_tags.has_perm({"request": request}, "directory.edit"))

    def test_valid_tenant_scope_can_use_legacy_permission_cache(self):
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "cheonan_db",
                "scope": "tenant",
                "perms": ["directory.edit"],
            }
        )
        with patch.object(acl_tags, "settings", self._settings()):
            self.assertTrue(acl_tags.has_perm({"request": request}, "directory.edit"))
            self.assertFalse(acl_tags.has_perm({"request": request}, "contracts.edit"))

    def test_valid_tenant_scope_queries_group_scoped_permissions_when_cache_empty(self):
        request = self._request(
            {
                "group_id": "group-a",
                "tenant_db_alias": "cheonan_db",
                "scope": "tenant",
            }
        )
        with patch.object(acl_tags, "settings", self._settings()), patch.object(
            acl_tags.C,
            "list_permissions_for_user_in_group",
            return_value=["directory.view", "directory.edit"],
        ) as permission_lookup:
            self.assertTrue(acl_tags.has_perm({"request": request}, "directory.edit"))

        permission_lookup.assert_called_once_with("user-a", "group-a")
        self.assertEqual(request.session["perms"], ["directory.edit", "directory.view"])


if __name__ == "__main__":
    unittest.main()
