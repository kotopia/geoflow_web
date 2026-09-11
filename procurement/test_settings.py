"""Isolated test runtime; never reads production env files or tenant secrets."""
import os

SECRET_KEY = "isolated-procurement-tests-only"
INSTALLED_APPS = ["django.contrib.contenttypes", "procurement"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
if os.environ.get("PROCUREMENT_TEST_POSTGRES") == "1":
    DATABASES["default"] = {"ENGINE": "django.db.backends.postgresql", "NAME": "procurement_test",
                            "USER": "postgres", "PASSWORD": "postgres", "HOST": "127.0.0.1", "PORT": "5432"}
CENTRAL_DB_ALIAS = "default"
for alias in ("company_a", "company_b"):
    DATABASES[alias] = dict(DATABASES["default"])
    DATABASES[alias]["NAME"] = alias if os.environ.get("PROCUREMENT_TEST_POSTGRES") == "1" else ":memory:"
USE_TZ = True
TIME_ZONE = "Asia/Seoul"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
G2B_API_SERVICE_KEY = "test-key-never-used-on-network"
