"""Isolated policy/auth/UI regressions, no production settings or connections."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from django.conf import settings
settings.configure(SECRET_KEY='isolated-project-policy',INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','django.contrib.humanize','control','control.catalog','geoflow_ops'],DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}},CENTRAL_DB_ALIAS='default',USE_TZ=True,ROOT_URLCONF='geoflow_project.urls',STATIC_URL='/static/',TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','APP_DIRS':True}])
import django;django.setup()
names=['geoflow_ops.test_list_event_badge_and_project_contract_parity','geoflow_ops.test_contract_workflow_stage_completion','geoflow_ops.test_project_policy','geoflow_ops.test_admin_overview','control.test_contract_project_atomic_create_contract','geoflow_ops.test_tenant_route_authorization_contract','geoflow_ops.test_phase4_contract_workboard_compat','geoflow_ops.test_phase4_settings_workflow_fixes','geoflow_ops.test_phase4_cross_department_workboard']
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names));sys.exit(not r.wasSuccessful())
