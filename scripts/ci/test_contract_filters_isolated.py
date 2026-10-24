"""Run focused contract tests without loading deployment settings or credentials."""
from pathlib import Path
import sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from django.conf import settings
settings.configure(SECRET_KEY='isolated-contract-filter-tests-only',INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','control','control.catalog','geoflow_ops'],DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}},CENTRAL_DB_ALIAS='default',USE_TZ=True)
import django
django.setup()
suite=unittest.defaultTestLoader.loadTestsFromNames(['geoflow_ops.test_contract_filters','geoflow_ops.test_tenant_route_authorization_contract'])
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
