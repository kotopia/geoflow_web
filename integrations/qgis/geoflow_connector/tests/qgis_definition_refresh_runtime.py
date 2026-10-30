"""Manifest-pinned definition refresh, including stale callbacks and tenant scope."""
import sys
from pathlib import Path
from types import SimpleNamespace
from qgis.core import QgsApplication
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from geoflow_connector.api.definitions import DefinitionService
app=QgsApplication.instance() or QgsApplication([],False)
queue=[]
def submit(work,done):
    queue.append((work,done))
    return SimpleNamespace(cancel=lambda:None)
def finish():
    work,done=queue.pop(0)
    try:value=work()
    except Exception as exc:done(exc);return
    done(None,value)
url='/definition/'
manifest={'project':{'id':'project-a'},'transport':{'form_definition_url':url,'form_definition_revision':'old'}}
revision=['old'];project=['project-a']
def get(path):
    if path==url:return {'version':'gis-final-form-v3','revision':revision[0],'fields':[],'rules':[]}
    assert path=='/gis/projects/project-a/api/qgis-manifest/'
    return {'project':{'id':project[0]},'transport':{'form_definition_url':url,'form_definition_revision':revision[0]}}
client=SimpleNamespace(base_url='https://example.test',readonly_session_copy=lambda:SimpleNamespace(get_json=get))
service=DefinitionService(submit=submit)
service.open(manifest,client);finish();assert service.state=='ready'
revision[0]='new';service.refresh(revalidate_revision=True);finish()
assert service.state=='ready' and service.definition['revision']=='new'
assert manifest['transport']['form_definition_revision']=='new'
service.open(manifest,client);assert not queue
project[0]='project-b';service.refresh(revalidate_revision=True);finish()
assert service.state=='error' and service.definition['revision']=='new'
project[0]='project-a';service.refresh(revalidate_revision=True);service.clear();finish()
assert service.state=='idle' and service.scope is None
print('Definition revision refresh, project mismatch and stale callback guards: OK')
