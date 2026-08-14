from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from control.views_auth import (
    _candidate_is_selectable,
    _configured_static_tenant_aliases,
    _static_tenant_database_config_is_ready,
)


class StaticTenantAliasSelectionTests(SimpleTestCase):
    def _candidate(self, alias="tenant-a"):
        return {
            "id": "group-a",
            "code": "workspace",
            "name": "Workspace",
            "db_alias": alias,
        }

    def _membership(self, alias="tenant-a", **overrides):
        config = {
            "db_alias": alias,
            "db_name": "dynamic-db",
            "db_host": "dynamic-host",
            "db_port": 5432,
            "db_user": "dynamic-user",
            "db_password": "dynamic-password",
        }
        config.update(overrides)
        return SimpleNamespace(
            group_id="group-a",
            status="active",
            group=SimpleNamespace(
                status="active",
                groupdbconfig=SimpleNamespace(**config),
            ),
        )

    def _static_database(self, **overrides):
        database = {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": "static-db",
            "HOST": "static-host",
            "PORT": "5432",
            "USER": "static-user",
            "PASSWORD": "static-password",
        }
        database.update(overrides)
        return database

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="tenant-a",
        STATIC_TENANT_DB_ALIASES=("tenant-a",),
        DATABASES={
            "default": {"ENGINE": "django.db.backends.postgresql"},
            "tenant-a": {
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "static-db",
                "HOST": "static-host",
                "PORT": "5432",
                "USER": "static-user",
                "PASSWORD": "static-password",
            },
        },
    )
    def test_default_static_alias_uses_complete_static_database_config(self):
        membership = self._membership(
            db_name="",
            db_host="",
            db_port=None,
            db_user="",
            db_password="",
        )

        self.assertEqual(_configured_static_tenant_aliases(), {"tenant-a"})
        self.assertTrue(_static_tenant_database_config_is_ready("tenant-a"))
        self.assertTrue(
            _candidate_is_selectable(self._candidate(), membership)
        )

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="tenant-a",
        STATIC_TENANT_DB_ALIASES=("tenant-a",),
        DATABASES={
            "default": {"ENGINE": "django.db.backends.postgresql"},
            "tenant-a": {
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "static-db",
                "HOST": "static-host",
                "PORT": "5432",
                "USER": "static-user",
                "PASSWORD": "",
            },
        },
    )
    def test_incomplete_static_alias_fails_closed(self):
        self.assertFalse(_static_tenant_database_config_is_ready("tenant-a"))
        self.assertFalse(
            _candidate_is_selectable(
                self._candidate(),
                self._membership(),
            )
        )

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="tenant-a",
        STATIC_TENANT_DB_ALIASES=("tenant-a",),
        DATABASES={
            "default": {"ENGINE": "django.db.backends.postgresql"},
            "tenant-a": {
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "static-db",
                "HOST": "static-host",
                "PORT": "5432",
                "USER": "static-user",
                "PASSWORD": "static-password",
            },
        },
    )
    def test_static_alias_still_requires_active_membership_group_and_alias_match(self):
        inactive_membership = self._membership()
        inactive_membership.status = "inactive"
        inactive_group = self._membership()
        inactive_group.group.status = "inactive"

        self.assertFalse(
            _candidate_is_selectable(self._candidate(), inactive_membership)
        )
        self.assertFalse(
            _candidate_is_selectable(self._candidate(), inactive_group)
        )
        self.assertFalse(
            _candidate_is_selectable(
                self._candidate(),
                self._membership(alias="tenant-b"),
            )
        )

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="tenant-a",
        STATIC_TENANT_DB_ALIASES=("tenant-a",),
        DATABASES={
            "default": {"ENGINE": "django.db.backends.postgresql"},
            "tenant-a": {
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "static-db",
                "HOST": "static-host",
                "PORT": "5432",
                "USER": "static-user",
                "PASSWORD": "static-password",
            },
        },
    )
    def test_dynamic_alias_still_requires_complete_central_config(self):
        candidate = self._candidate(alias="tenant-dynamic")
        membership = self._membership(
            alias="tenant-dynamic",
            db_password="",
        )

        self.assertNotIn(
            "tenant-dynamic",
            _configured_static_tenant_aliases(),
        )
        self.assertFalse(_candidate_is_selectable(candidate, membership))

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="tenant-a",
        STATIC_TENANT_DB_ALIASES=("tenant-b",),
        DATABASES={
            "default": {"ENGINE": "django.db.backends.postgresql"},
            "tenant-b": {
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "static-db",
                "HOST": "static-host",
                "PORT": "5432",
                "USER": "static-user",
                "PASSWORD": "static-password",
            },
        },
    )
    def test_explicit_static_allowlist_overrides_default_alias(self):
        self.assertEqual(_configured_static_tenant_aliases(), {"tenant-b"})
        self.assertTrue(
            _candidate_is_selectable(
                self._candidate(alias="tenant-b"),
                self._membership(
                    alias="tenant-b",
                    db_name="",
                    db_host="",
                    db_port=None,
                    db_user="",
                    db_password="",
                ),
            )
        )

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="default",
        STATIC_TENANT_DB_ALIASES=(),
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "central-db",
                "HOST": "central-host",
                "PORT": "5432",
                "USER": "central-user",
                "PASSWORD": "central-password",
            },
        },
    )
    def test_central_alias_can_never_be_selected_as_tenant(self):
        self.assertFalse(_static_tenant_database_config_is_ready("default"))
        self.assertFalse(
            _candidate_is_selectable(
                self._candidate(alias="default"),
                self._membership(alias="default"),
            )
        )
