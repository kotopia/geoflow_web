import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from geoflow_ops.gis import form_definitions as forms


class DefinitionValidationTests(unittest.TestCase):
    def test_boolean_remains_nullable_definition(self):
        self.assertEqual(forms.validate_config("scalar",{"data_type":"boolean"}),{"data_type":"boolean"})

    def test_invalid_or_unrecognized_config_rejected(self):
        for kind,config in [("photo",{"min_count":4,"max_count":2}),
                            ("photo",{"min_count":True,"max_count":2}),
                            ("scalar",{"data_type":"uuid"}),
                            ("survey_relation",{"table":"hr.employee_profile"}),
                            ("sql",{}),("scalar",{"data_type":"text","sql":"SELECT 1"})]:
            with self.subTest(kind=kind,config=config), self.assertRaises(forms.DefinitionError):
                forms.validate_config(kind,config)

    def test_bad_identifiers_rejected(self):
        for value in [None,"", "DROP TABLE x", "project-1"]:
            with self.assertRaises(forms.DefinitionError):
                forms.identifier(value)

    def test_empty_scope_never_queries_catalog(self):
        class NoQueries:
            def execute(self,*args):
                raise AssertionError("must not query")
        result=forms.resolve(NoQueries(),project_id=uuid4(),profile_id=uuid4(),feature_ids=[])
        self.assertEqual(result["items"],[])


@unittest.skipUnless(os.environ.get("GEOFLOW_FORMS_ISOLATED_PG")=="1", "isolated PostgreSQL opt-in only")
class DefinitionPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        # Fixed disposable service. Never consume deployment connection variables.
        self.conn=psycopg2.connect(host="127.0.0.1",port=55440,dbname="geoflow_forms_test",
                                   user="geoflow_test",password="geoflow_test",connect_timeout=5)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur=self.conn.cursor()
        self.addCleanup(self.cur.close)
        self.cur.execute("SELECT current_database()")
        self.assertEqual(self.cur.fetchone()[0],"geoflow_forms_test")
        self.cur.execute("""CREATE SCHEMA gis; CREATE SCHEMA prj;
            CREATE TABLE prj.projects(id uuid PRIMARY KEY);
            CREATE TABLE gis.meta_feature_type(id uuid PRIMARY KEY,physical_name text,standard_name text,
                label text,active boolean,sort_order int);
            CREATE TABLE gis.profile(id uuid PRIMARY KEY,active boolean);
            CREATE TABLE gis.ref_code_group(id uuid PRIMARY KEY,group_key text UNIQUE,active boolean);
            CREATE TABLE gis.test_feature(id uuid PRIMARY KEY,ext_data jsonb);
        """)
        self.cur.execute("""ALTER TABLE gis.ref_code_group ADD COLUMN name text;
            CREATE TABLE gis.ref_code_value(id uuid PRIMARY KEY,group_id uuid,code text,label text,
                sort_order integer,active boolean,valid_from date,valid_to date);""")
        ddl=Path(__file__).resolve().parents[2]/"docs/architecture/gis-form-definitions-v1.sql"
        self.cur.execute(ddl.read_text())
        self.project,self.other,self.profile,self.feature=map(lambda _:str(uuid4()),range(4))
        self.cur.execute("INSERT INTO prj.projects VALUES (%s),(%s)",[self.project,self.other])
        self.cur.execute("INSERT INTO gis.profile VALUES (%s,true)",[self.profile])
        self.cur.execute("INSERT INTO gis.meta_feature_type VALUES (%s,'test_feature','TEST','시험',true,1)",[self.feature])

    def item(self,private=False,kind="scalar"):
        return forms.add_item(self.cur,feature_id=self.feature,label="추락방지시설" if kind=="scalar" else "사진",
                              kind=kind,config={"data_type":"boolean"} if kind=="scalar" else {"min_count":0,"max_count":20},
                              project_id=self.project if private else None)

    def resolved(self,project=None,features=None):
        return forms.resolve(self.cur,project_id=project or self.project,profile_id=self.profile,
                             feature_ids=features if features is not None else [self.feature])

    def test_project_addition_does_not_change_profile_or_other_project(self):
        item=self.item()
        forms.attach_project(self.cur,item_id=item,project_id=self.project)
        self.assertEqual(len(self.resolved()["items"]),1)
        self.assertEqual(self.resolved(self.other)["items"],[])
        self.cur.execute("SELECT count(*) FROM gis.profile_form_item")
        self.assertEqual(self.cur.fetchone()[0],0)

    def test_private_item_cannot_be_attached_to_other_project(self):
        item=self.item(private=True)
        with self.assertRaises(forms.DefinitionError):
            forms.attach_project(self.cur,item_id=item,project_id=self.other)

    def test_profile_display_and_required_input_are_separate(self):
        item=self.item()
        forms.attach_profile(self.cur,item_id=item,profile_id=self.profile,required=False)
        value=self.resolved()["items"][0]
        self.assertTrue(value["required_display"])
        self.assertFalse(value["required_on_complete"])
        self.assertEqual(len(self.resolved(self.other)["items"]),1)

    def test_promotion_preserves_id_and_deduplicates(self):
        item=self.item(private=True)
        forms.attach_project(self.cur,item_id=item,project_id=self.project)
        with self.assertRaises(forms.DefinitionError):
            forms.attach_profile(self.cur,item_id=item,profile_id=self.profile)
        forms.attach_profile(self.cur,item_id=item,profile_id=self.profile,promote=True)
        self.assertEqual([v["id"] for v in self.resolved()["items"]],[item])
        self.assertEqual([v["id"] for v in self.resolved(self.other)["items"]],[item])

    def test_layer_filter_cannot_leak_other_features(self):
        item=self.item()
        forms.attach_profile(self.cur,item_id=item,profile_id=self.profile)
        self.assertEqual(self.resolved(features=[str(uuid4())])["items"],[])

    def test_private_item_remains_hidden_even_with_inconsistent_profile_link(self):
        item=self.item(private=True)
        self.cur.execute("INSERT INTO gis.profile_form_item(profile_id,item_id) VALUES (%s,%s)",[self.profile,item])
        self.assertEqual(self.resolved(self.other)["items"],[])

    def test_photo_reuses_attachment_storage_and_revision_changes(self):
        before=self.resolved()["revision"]
        item=self.item(kind="photo")
        forms.attach_project(self.cur,item_id=item,project_id=self.project)
        result=self.resolved()
        self.assertNotEqual(before,result["revision"])
        self.assertEqual(result["items"][0]["storage"]["kind"],"ops.attachments")

    def test_reference_values_scoped_to_selected_items(self):
        group=str(uuid4())
        self.cur.execute("INSERT INTO gis.ref_code_group VALUES (%s,'TEST.YESNO',true,'유무')",[group])
        self.cur.execute("INSERT INTO gis.ref_code_value VALUES (%s,%s,'01','있음',1,true,NULL,NULL)",[str(uuid4()),group])
        item=forms.add_item(self.cur,feature_id=self.feature,label="참조",kind="scalar",
                            config={"data_type":"text"},code_group_key="TEST.YESNO")
        forms.attach_project(self.cur,item_id=item,project_id=self.project)
        self.assertEqual(self.resolved()["groups"][0]["values"][0]["code"],"01")
        self.assertEqual(self.resolved(self.other)["groups"],[])


if __name__=="__main__":
    unittest.main()
