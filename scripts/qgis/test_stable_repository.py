"""Release-lock, channel isolation and reversible index publication regressions."""
import configparser
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from botocore.exceptions import ClientError
from scripts.qgis.build_plugin_repository import build_xml, build_zip, metadata, release_payloads
from scripts.ops import publish_qgis_plugin_repository as publisher

ROOT=Path(__file__).resolve().parents[2]


class MemoryS3:
    def __init__(self):
        self.objects={publisher.repository_object_key('test'):b'<plugins />'}
        self.writes=[]

    def get_object(self,*,Bucket,Key):
        if Key not in self.objects:
            raise ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
        return {'Body':io.BytesIO(self.objects[Key])}

    def put_object(self,*,Bucket,Key,Body,**kwargs):
        if kwargs.get('IfNoneMatch')=='*' and Key in self.objects:
            raise ClientError({'Error':{'Code':'PreconditionFailed'}},'PutObject')
        self.objects[Key]=Body
        self.writes.append(Key)
        return {}


class StableRepositoryTests(unittest.TestCase):
    def test_direct_publisher_execution_finds_project_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Stop at Django setup: exercise the real entry point without DB/S3.
            root.joinpath('django.py').write_text(
                "def setup():\n"
                "    import importlib.util\n"
                "    assert importlib.util.find_spec('geoflow_project') is not None\n"
                "    print('project_importable')\n"
                "    raise SystemExit(0)\n"
            )
            env = dict(os.environ, PYTHONPATH=directory)
            result = subprocess.run(
                [sys.executable, str(ROOT/'scripts/ops/publish_qgis_plugin_repository.py'),
                 '--channel', 'stable', '--confirm', 'bootstrap-only'],
                cwd=directory, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('project_importable', result.stdout)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'geoflow_connector';self.source.mkdir()
        self.source.joinpath('__init__.py').write_text('VALUE = 1\n')
        self.source.joinpath('metadata.txt').write_text('[general]\nname=GeoFlow Connector\nversion=1.2.3\nqgisMinimumVersion=3.28\nqgisMaximumVersion=4.99\ndescription=한글 & <XML>\nabout=About\nauthor=GeoFlow\nhomepage=https://geoflow.co.kr\ntracker=https://github.com/kotopia/geoflow_web/issues\nrepository=https://github.com/kotopia/geoflow_web\nexperimental=False\ndeprecated=False\n',encoding='utf-8')
        self.package=self.root/'geoflow_connector-1.2.3.zip'
        self.hash=build_zip(self.source,self.package)
        self.xml=build_xml(metadata(self.source),publisher.SITE+'packages/'+self.package.name,self.package.name,self.hash)
        self.index=self.root/'plugins.xml';self.index.write_bytes(self.xml)
        self.client=MemoryS3()
        self.patches=[patch.object(publisher,'get_s3_client',return_value=self.client),patch.object(publisher,'get_sse_config',return_value={})]
        for p in self.patches:p.start()
        self.confirm='PUBLISH_QGIS_PLUGIN:stable:geoflow-upload:qgis-plugins'

    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()

    def test_stable_publish_keeps_test_bytes_and_uses_separate_package_prefix(self):
        publisher.publish('stable',self.index,self.package,self.confirm)
        self.assertEqual(self.client.objects['qgis-plugins/test/plugins.xml'],b'<plugins />')
        self.assertEqual(self.client.objects['qgis-plugins/stable/packages/'+self.package.name],self.package.read_bytes())
        self.assertEqual(self.client.objects['qgis-plugins/stable/plugins.xml'],self.xml)
        self.assertFalse(any(key.startswith('qgis-plugins/releases/') or key.startswith('tenants/') for key in self.client.writes))

    def test_hash_mismatch_stops_before_any_write(self):
        self.package.write_bytes(self.package.read_bytes()+b'changed')
        with self.assertRaisesRegex(SystemExit,'package_sha256_mismatch'):
            publisher.publish('stable',self.index,self.package,self.confirm)
        self.assertEqual(self.client.writes,[])

    def test_test_download_url_cannot_enter_stable_index(self):
        self.index.write_bytes(self.xml.replace(b'/packages/',b'/releases/'))
        with self.assertRaisesRegex(SystemExit,'download_url_invalid'):
            publisher.publish('stable',self.index,self.package,self.confirm)
        self.assertEqual(self.client.writes,[])

    def test_immutable_collision_does_not_replace_index(self):
        self.client.objects['qgis-plugins/stable/packages/'+self.package.name]=b'other'
        with self.assertRaisesRegex(SystemExit,'immutable_package_collision'):
            publisher.publish('stable',self.index,self.package,self.confirm)
        self.assertNotIn('qgis-plugins/stable/plugins.xml',self.client.objects)

    def test_history_index_restores_previous_version_and_retains_packages(self):
        publisher.publish('stable',self.index,self.package,self.confirm)
        history='qgis-plugins/stable/history/plugins-'+publisher.digest(self.xml)+'.xml'
        values=metadata(self.source);values['version']='1.2.4'
        self.source.joinpath('metadata.txt').write_text(self.source.joinpath('metadata.txt').read_text().replace('version=1.2.3','version=1.2.4'))
        newer=self.root/'geoflow_connector-1.2.4.zip';sha=build_zip(self.source,newer)
        self.index.write_bytes(build_xml(values,publisher.SITE+'packages/'+newer.name,newer.name,sha))
        publisher.publish('stable',self.index,newer,self.confirm)
        publisher.rollback_index(history,self.confirm,False)
        self.assertEqual(self.client.objects['qgis-plugins/stable/plugins.xml'],self.xml)
        self.assertIn('qgis-plugins/stable/packages/'+newer.name,self.client.objects)
        self.assertEqual(self.client.objects['qgis-plugins/test/plugins.xml'],b'<plugins />')

    def test_xml_special_characters_metadata_and_update_identity(self):
        filename,sha,data=publisher.validate_package(self.xml,self.package,'stable')
        self.assertEqual(sha,self.hash)
        plugin=ET.fromstring(self.xml).find('pyqgis_plugin')
        self.assertEqual(plugin.findtext('description'),'한글 & <XML>')
        self.assertEqual(plugin.findtext('file_name'),'geoflow_connector.zip')
        self.assertGreater(tuple(map(int,'1.4.3'.split('.'))),tuple(map(int,'1.4.2'.split('.'))))

    def test_approved_143_archive_is_byte_exact_on_this_platform(self):
        source=ROOT/'integrations/qgis/geoflow_connector'
        manifest=source/'release/geoflow_connector-release.json'
        inventory=source/'release/package-files.json'
        output=self.root/'geoflow_connector-1.4.3.zip'
        sha=build_zip(source,output,release_manifest=manifest,inventory=inventory)
        self.assertEqual(sha,'8576b07bedd7649d45be3bdcebd2ae8cba84d0327d2eef29ed5676ffd883aac5')
        self.assertEqual(output.stat().st_size,5221008)
        with zipfile.ZipFile(output) as z:
            self.assertEqual(sum(not i.is_dir() for i in z.infolist()),5600)
            self.assertEqual(z.testzip(),None)

    def test_release_inventory_rejects_changed_file_bytes(self):
        source=ROOT/'integrations/qgis/geoflow_connector'
        manifest=source/'release/geoflow_connector-release.json'
        records=json.loads((source/'release/package-files.json').read_text())
        records[0]['sha256']='0'*64
        invalid=self.root/'inventory.json';invalid.write_text(json.dumps(records))
        with self.assertRaisesRegex(ValueError,'file bytes differ'):
            release_payloads(source,manifest,invalid)


if __name__=='__main__':unittest.main()
