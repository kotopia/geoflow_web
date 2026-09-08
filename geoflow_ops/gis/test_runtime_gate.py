from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .qfield_auth import qfield_ticket_runtime_enabled
from .qgis_sync import sync_runtime_enabled


class GISRuntimeGateTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    def test_production_requires_global_gate_and_exact_database_allowlist(self):
        connection = SimpleNamespace(settings_dict={"NAME": "pilot_tenant"})
        with patch("geoflow_ops.gis.qgis_sync.connections", {"tenant": connection}):
            with patch.dict("os.environ", {}, clear=True):
                self.assertFalse(sync_runtime_enabled("tenant"))
            with patch.dict("os.environ", {"GEOFLOW_GIS_PILOT_ENABLED": "1"}, clear=True):
                self.assertFalse(sync_runtime_enabled("tenant"))
            with patch.dict(
                "os.environ",
                {
                    "GEOFLOW_GIS_PILOT_ENABLED": "1",
                    "GEOFLOW_GIS_PILOT_DATABASES": "other,pilot_tenant",
                },
                clear=True,
            ):
                self.assertTrue(sync_runtime_enabled("tenant"))

    @override_settings(DEBUG=True)
    def test_strict_development_still_requires_dev_or_test_database_name(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}, clear=True):
            with patch(
                "geoflow_ops.gis.qgis_sync.connections",
                {"tenant": SimpleNamespace(settings_dict={"NAME": "geoflow_dev"})},
            ):
                self.assertTrue(sync_runtime_enabled("tenant"))
            with patch(
                "geoflow_ops.gis.qgis_sync.connections",
                {"tenant": SimpleNamespace(settings_dict={"NAME": "production"})},
            ):
                self.assertFalse(sync_runtime_enabled("tenant"))

    @override_settings(DEBUG=False)
    def test_qfield_ticket_signing_is_fail_closed_outside_explicit_pilot(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(qfield_ticket_runtime_enabled())
        with patch.dict("os.environ", {"GEOFLOW_GIS_PILOT_ENABLED": "1"}, clear=True):
            self.assertTrue(qfield_ticket_runtime_enabled())
