"""Back up a stopped QField project and replace only its install claim credential."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

try:
    from .recover_qfield_runtime import adb, read_device_file
except ImportError:
    from recover_qfield_runtime import adb, read_device_file


def replace_claim(data, connection):
    if connection.get('format') != 'geoflow_qfield_claim_recovery_v1':
        raise ValueError('Not a GeoFlow connection recovery file.')
    root = ET.fromstring(data)
    props = root.find('./properties/GeoFlow')
    if props is None:
        raise ValueError('GeoFlow project properties are missing.')
    for name in ('project_id', 'server_url'):
        expected = str(connection.get(name) or '').rstrip('/')
        if not expected or (props.findtext(name) or '').rstrip('/') != expected:
            raise ValueError('Connection file does not match the selected project/server.')
    token = connection.get('claim_token')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_.:\-]{32,8192}', token):
        raise ValueError('Connection credential format is invalid.')
    # Preserve all original XML bytes outside the one exact property value.
    pattern = rb'(<qfield_claim_token\b[^>]*>)([^<]*)(</qfield_claim_token>)'
    matches = list(re.finditer(pattern, data))
    if len(matches) != 1 or props.findtext('qfield_claim_token') is None:
        raise ValueError('Expected exactly one existing claim property; stopped.')
    result = re.sub(pattern, lambda m: m[1] + escape(token).encode('ascii') + m[3], data)
    ET.fromstring(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection-file', required=True)
    parser.add_argument('--project-dir', required=True)
    parser.add_argument('--backup-dir', required=True)
    args = parser.parse_args()
    project = PurePosixPath(args.project_dir)
    base = PurePosixPath('/storage/emulated/0/Android/data/ch.opengis.qfield/files/Imported Projects')
    if project.parent != base or any(c in args.project_dir for c in "'\"\n\r\\"):
        parser.error('Select one direct child of Imported Projects.')
    if adb('get-state').strip() != b'device':
        raise RuntimeError('Authorize exactly one ADB device first.')
    if adb('shell', 'pidof', 'ch.opengis.qfield', check=False).strip():
        raise RuntimeError('Save edits and stop QField first.')
    connection = json.loads(Path(args.connection_file).read_text(encoding='utf-8-sig'))
    root = Path(args.backup_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix='qfield-reconnect-', dir=root))
    adb('pull', str(project), str(saved))
    original = saved / project.name / 'geoflow-field.qgs'
    before = original.read_bytes()
    after = replace_claim(before, connection)
    candidate = saved / 'reconnected-project.qgs'
    candidate.write_bytes(after)
    remote = str(project / 'geoflow-field.qgs')
    if adb('shell', 'pidof', 'ch.opengis.qfield', check=False).strip():
        raise RuntimeError('QField restarted; stopped before writing.')
    if read_device_file(remote) != before:
        raise RuntimeError('Project changed after backup; stopped before writing.')
    adb('push', str(candidate), remote)
    if read_device_file(remote) != after:
        raise RuntimeError('Verification failed; retain the PC backup and report this error.')
    print('Project backup:', saved)
    print('Claim credential replaced and verified. Open this project, then use GeoFlow Open in QField.')


if __name__ == '__main__':
    main()
