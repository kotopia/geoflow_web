from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from scripts.qgis.build_plugin_repository import (
    PACKAGE_DIR,
    build_xml,
    build_zip,
    metadata,
)


class BuildPluginRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "geoflow_connector"
        self.source.mkdir()
        (self.source / "metadata.txt").write_text(
            "[general]\nname=GeoFlow Connector\nversion=1.2.3\n"
            "qgisMinimumVersion=3.28\nqgisMaximumVersion=4.99\n"
            "description=GeoFlow test\nauthor=GeoFlow\nexperimental=True\n",
            encoding="utf-8",
        )
        (self.source / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.source / "test_hidden.py").write_text("SECRET = False\n", encoding="utf-8")
        cache = self.source / "__pycache__"
        cache.mkdir()
        (cache / "hidden.pyc").write_bytes(b"compiled")

    def tearDown(self):
        self.temp.cleanup()

    def test_zip_is_deterministic_and_has_single_plugin_root(self):
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        self.assertEqual(build_zip(self.source, first), build_zip(self.source, second))
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(
                archive.namelist(),
                ["geoflow_connector/__init__.py", "geoflow_connector/metadata.txt"],
            )

    def test_xml_matches_metadata_package_and_hash(self):
        values = metadata(self.source)
        package = self.root / "plugin.zip"
        digest = build_zip(self.source, package)
        xml = build_xml(
            values,
            "https://geoflow.co.kr/gis/qgis/plugins/releases/geoflow_connector-1.2.3.zip",
            "geoflow_connector-1.2.3.zip",
            digest,
        )
        plugin = ET.fromstring(xml).find("pyqgis_plugin")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.attrib["experimental"], "true")
        self.assertEqual(plugin.findtext("version"), "1.2.3")
        self.assertEqual(plugin.findtext("file_name"), "geoflow_connector.zip")
        self.assertEqual(
            plugin.findtext("file_name").partition(".")[0],
            PACKAGE_DIR,
        )
        self.assertEqual(plugin.findtext("experimental"), "true")
        self.assertEqual(plugin.findtext("deprecated"), "false")
        self.assertEqual(plugin.findtext("trusted"), "false")
        self.assertTrue(
            plugin.findtext("download_url").endswith(
                "/geoflow_connector-1.2.3.zip"
            )
        )
        self.assertEqual(plugin.findtext("sha256_sum"), hashlib.sha256(package.read_bytes()).hexdigest())

    def test_xml_rejects_download_url_filename_mismatch(self):
        values = metadata(self.source)
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_xml(
                values,
                "https://geoflow.co.kr/gis/qgis/plugins/releases/other.zip",
                "geoflow_connector-1.2.3.zip",
                "0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
