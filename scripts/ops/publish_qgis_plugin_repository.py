#!/usr/bin/env python3
"""Publish reviewed immutable QGIS artifacts to one explicitly approved channel."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import os
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

from botocore.exceptions import ClientError

QGIS_PLUGIN_BUCKET = 'geoflow-upload'
QGIS_PLUGIN_PREFIX = 'qgis-plugins'
QGIS_PLUGIN_REPOSITORY_FILE_NAME = 'geoflow_connector.zip'
PACKAGE_RE = re.compile(r'\Ageoflow_connector-[0-9]+\.[0-9]+\.[0-9]+\.zip\Z')
HISTORY_RE = re.compile(r'\Aqgis-plugins/stable/history/plugins-[0-9a-f]{64}\.xml\Z')
SITE = 'https://geoflow.co.kr/gis/qgis/plugins/'
UNREADABLE_INDEX = object()


def fail(reason):
    raise SystemExit('qgis_plugin_repository_blocker='+reason)


def get_s3_client():
    from geoflow_ops.services.s3_service import get_s3_client as client
    return client()


def get_sse_config():
    from geoflow_ops.services.s3_service import get_sse_config as config
    return config()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def repository_object_key(channel):
    if channel not in {'test','stable'}:
        fail('unsupported_channel')
    return f'{QGIS_PLUGIN_PREFIX}/{channel}/plugins.xml'


def package_object_key(filename, channel='test'):
    if not PACKAGE_RE.fullmatch(filename):
        fail('repository_package_name_invalid')
    repository_object_key(channel)
    folder = 'stable/packages' if channel == 'stable' else 'releases'
    return f'{QGIS_PLUGIN_PREFIX}/{folder}/{filename}'


def repository_package(repository, channel='test'):
    data = repository.read_bytes() if isinstance(repository,Path) else repository
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        fail('repository_xml_invalid')
    plugins = root.findall('pyqgis_plugin')
    if root.tag != 'plugins' or len(plugins) != 1:
        fail('repository_plugin_invalid')
    plugin = plugins[0]
    if plugin.attrib.get('name') != 'GeoFlow Connector':
        fail('repository_plugin_invalid')
    if plugin.findtext('file_name') != QGIS_PLUGIN_REPOSITORY_FILE_NAME:
        fail('repository_plugin_id_invalid')
    version = plugin.attrib.get('version','')
    if plugin.findtext('version') != version:
        fail('repository_version_invalid')
    filename = f'geoflow_connector-{version}.zip'
    package_object_key(filename, channel)
    prefix = 'packages/' if channel == 'stable' else 'releases/'
    if plugin.findtext('download_url') != SITE+prefix+filename:
        fail('repository_download_url_invalid')
    expected_hash = plugin.findtext('sha256_sum','')
    if not re.fullmatch('[0-9a-f]{64}',expected_hash):
        fail('repository_sha256_invalid')
    if channel == 'stable' and (plugin.attrib.get('experimental','').lower() != 'false'
            or plugin.findtext('experimental','').lower() != 'false'
            or plugin.findtext('deprecated','').lower() != 'false'):
        fail('stable_flags_invalid')
    return filename,expected_hash


def validate_package(xml, package, channel):
    filename, expected_hash = repository_package(xml,channel)
    data = package.read_bytes()
    if package.name != filename:
        fail('package_filename_mismatch')
    if digest(data) != expected_hash:
        fail('package_sha256_mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if archive.testzip() or len(names) != len(set(names)):
                fail('zip_crc_or_duplicate_invalid')
            for name in names:
                parts = name.rstrip('/').split('/')
                if parts[0] != 'geoflow_connector' or '\\' in name or any(p in ('','..','.') for p in parts):
                    fail('zip_root_or_path_invalid')
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(archive.read('geoflow_connector/metadata.txt').decode('utf-8'))
            values = dict(parser.items('general'))
    except (zipfile.BadZipFile,KeyError,UnicodeError,configparser.Error):
        fail('zip_metadata_invalid')
    plugin = ET.fromstring(xml).find('pyqgis_plugin')
    mapping = {'name':'name','version':'version','description':'description','about':'about',
               'author_name':'author','homepage':'homepage','tracker':'tracker','repository':'repository',
               'qgis_minimum_version':'qgisminimumversion','qgis_maximum_version':'qgismaximumversion',
               'experimental':'experimental','deprecated':'deprecated'}
    for tag,key in mapping.items():
        left,right = plugin.findtext(tag,''), values.get(key,'')
        if tag in ('experimental','deprecated'):
            left,right=left.lower(),right.lower()
        if left != right:
            fail('xml_metadata_mismatch_'+tag)
    return filename,expected_hash,data


def s3_failure(reason, operation, key, exc):
    # Log only controlled object paths and AWS error identifiers, never messages
    # containing account/principal details or request/credential information.
    code = str(exc.response.get('Error', {}).get('Code', 'Unknown'))
    code = re.sub(r'[^A-Za-z0-9_]', '_', code)[:80]
    status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 'unknown')
    fail(f'{reason}:operation={operation}:key={key}:code={code}:status={status}')


def read_object(client,key, *, allow_create_only=False):
    try:
        result=client.get_object(Bucket=QGIS_PLUGIN_BUCKET,Key=key)
    except ClientError as exc:
        code=str(exc.response.get('Error',{}).get('Code',''))
        if code in {'404','NoSuchKey','NotFound'}:
            return None
        if allow_create_only and code in {'403', 'AccessDenied'}:
            # Without ListBucket, S3 can return 403 for a nonexistent key.
            # This is NOT proof of absence. Only an atomic create is allowed.
            print('qgis_plugin_index_read=denied:create_only:key='+key)
            return UNREADABLE_INDEX
        s3_failure('object_read_failed', 'GetObject', key, exc)
    try:
        return result['Body'].read()
    finally:
        result['Body'].close()


def put_immutable(client,key,data,content_type):
    try:
        client.put_object(Bucket=QGIS_PLUGIN_BUCKET,Key=key,Body=data,
                          ContentType=content_type,CacheControl='public,max-age=31536000,immutable',
                          Metadata={'sha256':digest(data)},IfNoneMatch='*',**get_sse_config())
    except ClientError as exc:
        code=str(exc.response.get('Error',{}).get('Code',''))
        if code not in {'PreconditionFailed','412','ConditionalRequestConflict'}:
            s3_failure('immutable_put_failed', 'PutObject', key, exc)
    # Verify the full object, not just caller-controlled metadata.
    if read_object(client,key) != data:
        fail('immutable_package_collision')


def http_bytes(url, content_type):
    with urlopen(url,timeout=60) as response:
        if response.status != 200 or response.geturl() != url:
            fail('public_http_status_or_redirect')
        if response.headers.get_content_type() != content_type:
            fail('public_content_type_invalid')
        return response.read()


def publish(channel, repository, package, confirmation, *, verify_http=False):
    if confirmation != f'PUBLISH_QGIS_PLUGIN:{channel}:{QGIS_PLUGIN_BUCKET}:qgis-plugins':
        fail('confirmation_mismatch')
    xml=repository.read_bytes()
    filename, expected_hash, data=validate_package(xml,package,channel)
    package_key, index_key=package_object_key(filename,channel),repository_object_key(channel)
    if package_key.startswith('tenants/') or index_key.startswith('tenants/'):
        fail('tenant_prefix_forbidden')
    client=get_s3_client()
    test_key=repository_object_key('test')
    test_before=read_object(client,test_key) if channel=='stable' else None
    if channel=='stable' and test_before is None:
        fail('existing_test_repository_missing')
    test_http_before=http_bytes(SITE+'test/plugins.xml','application/xml') if verify_http else None
    previous=read_object(client,index_key,allow_create_only=channel=='stable')
    if previous is UNREADABLE_INDEX:
        print('qgis_plugin_previous_index=unknown:create_only')
    elif previous is not None and channel=='stable':
        history_key=f'{QGIS_PLUGIN_PREFIX}/stable/history/plugins-{digest(previous)}.xml'
        put_immutable(client,history_key,previous,'application/xml; charset=utf-8')
        print('qgis_plugin_previous_index='+history_key)
    else:
        print('qgis_plugin_previous_index=none')
    put_immutable(client,package_key,data,'application/zip')
    # Archive each published index so rollback never relies on S3 bucket versioning.
    if channel=='stable':
        put_immutable(client,f'{QGIS_PLUGIN_PREFIX}/stable/history/plugins-{digest(xml)}.xml',xml,'application/xml; charset=utf-8')
    create_only = previous is None or previous is UNREADABLE_INDEX
    try:
        client.put_object(Bucket=QGIS_PLUGIN_BUCKET,Key=index_key,Body=xml,
                          ContentType='application/xml; charset=utf-8',CacheControl='no-cache,no-store,must-revalidate',
                          Metadata={'package-sha256':expected_hash,'xml-sha256':digest(xml)},
                          **({'IfNoneMatch': '*'} if create_only else {}), **get_sse_config())
    except ClientError as exc:
        s3_failure('repository_put_failed', 'PutObject', index_key, exc)
    if read_object(client,index_key) != xml:
        fail('repository_verification_hash_mismatch')
    if channel=='stable' and read_object(client,test_key) != test_before:
        fail('test_repository_changed')
    if verify_http:
        public_index=SITE+('plugins.xml' if channel=='stable' else 'test/plugins.xml')
        if http_bytes(public_index,'application/xml') != xml:
            fail('public_repository_bytes_mismatch')
        public_data=http_bytes(ET.fromstring(xml).find('pyqgis_plugin').findtext('download_url'),'application/zip')
        if len(public_data)!=len(data) or digest(public_data)!=expected_hash:
            fail('public_package_hash_mismatch')
        if http_bytes(SITE+'test/plugins.xml','application/xml') != test_http_before:
            fail('public_test_repository_changed')
        print('qgis_plugin_public_xml=200:valid_utf8_xml')
        print('qgis_plugin_public_zip=200:sha256_verified')
        print('qgis_plugin_public_test=200:unchanged')
    print('qgis_plugin_channel='+channel)
    print('qgis_plugin_package_key='+package_key)
    print('qgis_plugin_repository_key='+index_key)
    print('qgis_plugin_sha256='+expected_hash)
    print(f'RESULT qgis_plugin_{channel}_repository=SUCCESS')


def rollback_index(key, confirmation, verify_http):
    if not HISTORY_RE.fullmatch(key):
        fail('rollback_key_outside_stable_history')
    client=get_s3_client()
    xml=read_object(client,key)
    if xml is None or digest(xml) not in key:
        fail('rollback_index_missing_or_corrupt')
    filename,expected_hash=repository_package(xml,'stable')
    data=read_object(client,package_object_key(filename,'stable'))
    if data is None or digest(data)!=expected_hash:
        fail('rollback_package_missing_or_corrupt')
    with tempfile.TemporaryDirectory(prefix='qgis-stable-rollback-') as directory:
        root=Path(directory);(root/'plugins.xml').write_bytes(xml);(root/filename).write_bytes(data)
        publish('stable',root/'plugins.xml',root/filename,confirmation,verify_http=verify_http)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--channel',choices=('test','stable'),required=True)
    parser.add_argument('--repository',type=Path)
    parser.add_argument('--package',type=Path)
    parser.add_argument('--confirm',required=True)
    parser.add_argument('--verify-http',action='store_true')
    parser.add_argument('--rollback-index-key')
    args=parser.parse_args()
    # Direct file execution sets sys.path[0] to scripts/ops, not the project.
    # Resolve from this file so deployment and rollback work from any directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','geoflow_project.settings')
    import django
    django.setup()
    if args.rollback_index_key:
        if args.channel!='stable': fail('rollback_channel_invalid')
        rollback_index(args.rollback_index_key,args.confirm,args.verify_http)
    else:
        if not args.repository or not args.package: fail('repository_and_package_required')
        publish(args.channel,args.repository,args.package,args.confirm,verify_http=args.verify_http)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
