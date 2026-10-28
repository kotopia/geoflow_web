"""Isolated tests: no deployment settings, secrets, or live database discovery.

--postgres uses only the disposable GitHub Actions service on localhost and
rehearses migration 0049 forwards/backwards against synthetic legacy tables.
"""
from pathlib import Path
import os, sys, unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
POSTGRES = '--postgres' in sys.argv
if POSTGRES and os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('PostgreSQL rehearsal is restricted to disposable GitHub Actions services.')
from django.conf import settings
DB = {'ENGINE':'django.db.backends.postgresql','NAME':'company_test','HOST':'127.0.0.1','PORT':'5432','USER':'postgres','PASSWORD':'company-ci-only'} if POSTGRES else {'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}
settings.configure(SECRET_KEY='isolated-company-tests-only',INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','django.contrib.humanize','control','control.catalog','geoflow_ops'],DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'},'company_test':DB},CENTRAL_DB_ALIAS='default',DEFAULT_TENANT_DB_ALIAS='company_test',USE_TZ=True,TIME_ZONE='Asia/Seoul',GEOFLOW_COMPANY_OVERVIEW_ENABLED=True,GEOFLOW_COMPANY_OVERVIEW_TENANTS=('company_test',),ROOT_URLCONF='geoflow_ops.test_company_overview',STATIC_URL='/static/',TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','OPTIONS':{'loaders':[('django.template.loaders.locmem.Loader',{'geoflow_ops/partials/sidebar.html':'','geoflow_ops/partials/topbar.html':'','control/partials/sidebar_layout_init.html':''}),'django.template.loaders.app_directories.Loader']}}])
import django
django.setup()
from geoflow_ops import test_company_overview
names = ['control.test_company_overview_activation','geoflow_ops.test_company_overview.CompanyRulesTests','geoflow_ops.test_company_overview.CompanyBoundaryTests','geoflow_ops.test_company_overview.CompanyTemplateTests','geoflow_ops.test_event_timeline_order']
if POSTGRES:
    names.append('geoflow_ops.test_company_overview.CompanyDatabaseTests')
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
sys.exit(not result.wasSuccessful())
