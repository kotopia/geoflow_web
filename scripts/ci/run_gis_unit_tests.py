"""Run DB-free GIS contract tests with Django initialized.

The suite mocks persistence boundaries and must not create, migrate, or connect
to a live database. GitHub CI installs real GDAL/GEOS before invoking it.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "ci-gis-unit-key-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
os.environ.setdefault("DJANGO_DEBUG", "0")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost")
os.environ.setdefault("CENTRAL_DB_NAME", "ci-central")
os.environ.setdefault("CENTRAL_DB_USER", "ci")
os.environ.setdefault("CENTRAL_DB_PASSWORD", "ci-placeholder")
os.environ.setdefault("CENTRAL_DB_HOST", "127.0.0.1")
os.environ.setdefault("CENTRAL_DB_PORT", "5432")
os.environ.setdefault("TENANT_DB_NAME", "ci-tenant")
os.environ.setdefault("TENANT_DB_USER", "ci")
os.environ.setdefault("TENANT_DB_PASSWORD", "ci-placeholder")
os.environ.setdefault("TENANT_DB_HOST", "127.0.0.1")
os.environ.setdefault("TENANT_DB_PORT", "5432")
os.environ.setdefault("USE_SMTP_EMAIL", "0")
os.environ.setdefault("AWS_S3_BUCKET", "ci-nonexistent")

if os.getenv("GEOFLOW_GIS_TEST_ALLOW_GEOS_STUB") == "1":
    # Local container fallback only. Release CI intentionally leaves this unset
    # and loads the real GDAL/GEOS libraries installed by release-preflight.
    geos = types.ModuleType("django.contrib.gis.geos")

    class GEOSGeometry:  # pragma: no cover - local dependency fallback
        pass

    geos.GEOSGeometry = GEOSGeometry
    sys.modules["django.contrib.gis.geos"] = geos

from django.conf import settings  # noqa: E402


settings.DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

import django  # noqa: E402


django.setup()


def main() -> int:
    gis_suite = unittest.defaultTestLoader.discover(
        str(ROOT / "geoflow_ops" / "gis"),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )
    qgis_suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name)
        for name in (
            "integrations.qgis.geoflow_connector.test_cache_lifecycle",
            "integrations.qgis.geoflow_connector.test_snapshot_cache",
        )
    )
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestSuite((gis_suite, qgis_suite))
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
