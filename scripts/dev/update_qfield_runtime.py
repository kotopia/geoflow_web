"""Back up a stopped QField project and update only its generated QML runtime."""
import argparse
from pathlib import Path, PurePosixPath
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.dev.recover_qfield_runtime import adb, read_device_file


def render_runtime():
    from django.conf import settings
    root = Path(__file__).resolve().parents[2]
    if not settings.configured:
        settings.configure(BASE_DIR=root)
    from geoflow_ops.gis.qfield_package import _render_qfield_plugin
    from geoflow_ops.gis.qfield_persistent import _inject_qml_persistent_session
    from geoflow_ops.gis.qfield_runtime_finalize import _finalize_qml
    text = _finalize_qml(_inject_qml_persistent_session(_render_qfield_plugin(root / 'integrations/qfield/geoflow-field.qml')))
    if len(text) < 10000 or 'function expireStalledChangeset' not in text:
        raise RuntimeError('Generated runtime validation failed.')
    return text.encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', required=True)
    parser.add_argument('--backup-dir', required=True)
    args = parser.parse_args()
    project = PurePosixPath(args.project_dir)
    base = PurePosixPath('/storage/emulated/0/Android/data/ch.opengis.qfield/files/Imported Projects')
    if project.parent != base or any(c in args.project_dir for c in "'\"\n\r\\"):
        parser.error('Select one direct child of Imported Projects.')
    if adb('get-state').strip() != b'device':
        raise RuntimeError('Authorize exactly one device.')
    if adb('shell', 'pidof', 'ch.opengis.qfield', check=False).strip():
        raise RuntimeError('Save edits and stop QField first.')
    content = render_runtime()
    root = Path(args.backup_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix='qfield-runtime-', dir=root))
    adb('pull', str(project), str(saved))
    folder = saved / project.name
    if not (folder / 'geoflow-field.qgs').is_file():
        raise RuntimeError('Project backup is missing; stopped.')
    runtime = folder / 'geoflow-field.qml'
    before = runtime.read_bytes()
    if b'GeoFlow' not in before:
        raise RuntimeError('Existing runtime is not recognizable; stopped.')
    candidate = saved / 'updated-runtime.qml'
    candidate.write_bytes(content)
    remote = str(project / runtime.name)
    if adb('shell', 'pidof', 'ch.opengis.qfield', check=False).strip() or read_device_file(remote) != before:
        raise RuntimeError('Project changed or QField restarted; stopped.')
    adb('push', str(candidate), remote)
    if read_device_file(remote) != content:
        raise RuntimeError('Verification failed; retain the PC backup.')
    print('Project backup:', saved)
    from geoflow_ops.gis.qfield_package import QFIELD_PLUGIN_RUNTIME_VERSION
    print('Runtime ' + QFIELD_PLUGIN_RUNTIME_VERSION + ' updated and verified; project data and outbox retained.')


if __name__ == '__main__':
    main()
