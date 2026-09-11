from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from django.http import Http404
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase

from .qgis_plugin_repository import (
    QGIS_PLUGIN_TEST_PACKAGE,
    package_object_key,
    repository_object_key,
)
from .qgis_plugin_repository_views import (
    qgis_plugin_package,
    qgis_plugin_repository_xml,
)


class _Body(io.BytesIO):
    pass


class QgisPluginRepositoryTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/gis/qgis/plugins/test/plugins.xml")

    def test_keys_are_confined_outside_tenants(self):
        self.assertEqual(
            repository_object_key("test"), "qgis-plugins/test/plugins.xml"
        )
        self.assertEqual(
            repository_object_key("stable"), "qgis-plugins/stable/plugins.xml"
        )
        self.assertEqual(
            package_object_key("geoflow_connector-0.7.3.zip"),
            "qgis-plugins/releases/geoflow_connector-0.7.3.zip",
        )
        for key in (
            repository_object_key("test"),
            repository_object_key("stable"),
            package_object_key("geoflow_connector-0.7.3.zip"),
        ):
            self.assertFalse(key.startswith("tenants/"))

    def test_arbitrary_channels_and_filenames_are_rejected(self):
        with self.assertRaises(ValueError):
            repository_object_key("tenants")
        with self.assertRaises(ValueError):
            package_object_key("../tenants/private.zip")
        with self.assertRaises(ValueError):
            package_object_key("geoflow_connector-latest.zip")

    @patch(
        "geoflow_ops.gis.qgis_plugin_repository_views._private_plugin_object",
        return_value={"Body": _Body(b"<plugins />")},
    )
    def test_repository_xml_is_publicly_streamed_without_storage_redirect(self, mocked):
        response = qgis_plugin_repository_xml(self.request, "test")
        self.assertEqual(b"".join(response.streaming_content), b"<plugins />")
        self.assertEqual(response["Cache-Control"], "no-cache, no-store, must-revalidate")
        mocked.assert_called_once_with("qgis-plugins/test/plugins.xml")

    @patch(
        "geoflow_ops.gis.qgis_plugin_repository_views._private_plugin_object",
        return_value={"Body": _Body(b"PK\x03\x04")},
    )
    def test_versioned_package_is_streamed_from_exact_release_key(self, mocked):
        response = qgis_plugin_package(
            self.request, "geoflow_connector-0.7.3.zip"
        )
        self.assertEqual(b"".join(response.streaming_content), b"PK\x03\x04")
        self.assertIn("immutable", response["Cache-Control"])
        mocked.assert_called_once_with(
            "qgis-plugins/releases/geoflow_connector-0.7.3.zip"
        )

    def test_url_contract_exposes_only_fixed_repository_routes(self):
        urls = (Path(__file__).resolve().parent / "urls.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('qgis/plugins/<str:channel>/plugins.xml', urls)
        self.assertIn('qgis/plugins/releases/<str:filename>', urls)

    def test_project_page_contains_repository_install_flow(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "templates/geoflow_ops/gis/project_dashboard.html"
        )
        source = template_path.read_text(encoding="utf-8")
        self.assertIn("QGIS 플러그인 설치", source)
        self.assertIn("실험적 플러그인도 표시", source)
        self.assertIn("qgis_plugin_test_package", source)
        self.assertEqual(QGIS_PLUGIN_TEST_PACKAGE, "geoflow_connector-0.7.6.zip")
        get_template("geoflow_ops/gis/project_dashboard.html")
