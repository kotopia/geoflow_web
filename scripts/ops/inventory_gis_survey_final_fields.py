"""Read-only aggregate Survey contract inventory; never prints business records."""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoflow_project.settings')
import django
django.setup()
from django.db import connections
from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor

FIELDS = ['survey_no','type','raw_x','raw_y','raw_z','x','y','z','latitude','longitude','antenna_height','survey_date']
for config in GroupDBConfig.objects.using('default').filter(group__status='active').exclude(db_alias='default').order_by('group_id'):
    with tenant_cursor(config.group_id, write=False) as c:
        c.execute("SELECT column_name,data_type,udt_name,column_default,is_nullable FROM information_schema.columns WHERE table_schema='gis' AND table_name='survey' AND column_name=ANY(%s) ORDER BY ordinal_position", [FIELDS])
        cols=c.fetchall()
        print('survey_schema='+json.dumps(cols))
        names={r[0] for r in cols}
        print('survey_missing_columns='+json.dumps(sorted(set(FIELDS)-names)))
        if 'survey_no' in names:
            c.execute("SELECT count(*) FILTER (WHERE survey_no IS NULL OR btrim(survey_no)='') FROM gis.survey")
            print('survey_missing_number_count='+str(c.fetchone()[0]))
            c.execute("SELECT count(*) FROM (SELECT project_id,survey_no FROM gis.survey WHERE survey_no IS NOT NULL GROUP BY project_id,survey_no HAVING count(*)>1) duplicates")
            print('survey_duplicate_number_groups='+str(c.fetchone()[0]))
        c.execute("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN ('gis.survey'::regclass,'gis.survey_source'::regclass) AND contype IN ('c','u')")
        print('survey_constraints='+json.dumps(c.fetchall()))
        c.execute("SELECT source_type,count(*) FROM gis.survey_source GROUP BY source_type ORDER BY source_type")
        print('survey_source_type_counts='+json.dumps(c.fetchall()))
        c.execute("SELECT type,count(*) FROM gis.survey GROUP BY type ORDER BY type")
        print('survey_type_counts='+json.dumps(c.fetchall()))
        c.execute("SELECT count(*),count(*) FILTER (WHERE raw_x IS NOT NULL AND (x IS NULL OR x=0)),count(*) FILTER (WHERE raw_y IS NOT NULL AND (y IS NULL OR y=0)),count(*) FILTER (WHERE raw_z IS NOT NULL AND (z IS NULL OR z=0)),count(*) FILTER (WHERE type IS NULL),count(*) FILTER (WHERE survey_date IS NULL) FROM gis.survey")
        print('survey_backfill_counts='+json.dumps(c.fetchone()))
        c.execute("SELECT raw_crs,count(*) FROM gis.survey GROUP BY raw_crs ORDER BY raw_crs")
        print('survey_raw_crs_counts='+json.dumps(c.fetchall()))
        c.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='gis' AND table_name='project_definition'")
        print('project_definition_schema='+json.dumps(c.fetchall()))
with connections['default'].cursor() as c:
    c.execute("SELECT f.physical_name,f.storage_data_type FROM gis.definition_field f JOIN gis.definition_layer l ON l.id=f.source_layer_id WHERE l.physical_name='survey' ORDER BY f.physical_name")
    print('survey_definition_fields='+json.dumps(c.fetchall()))
    c.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='gis' AND (table_name='definition_field' OR table_name='definition_layer') ORDER BY table_name,ordinal_position")
    print('central_definition_schema='+json.dumps(c.fetchall()))
print('survey_inventory_complete=yes')
