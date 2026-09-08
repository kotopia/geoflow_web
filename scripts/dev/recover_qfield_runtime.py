"""Back up one QField project; optionally restore only a zero-byte QML runtime."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import tempfile


def adb(*args, check=True):
    return subprocess.run(['adb', *args], check=check, capture_output=True).stdout


def validate_restore(current, backup):
    if current != b'':
        raise ValueError('Runtime is not empty; refusing to overwrite it.')
    if not backup or b'GeoFlow' not in backup or b'import QtQuick' not in backup:
        raise ValueError('Backup is empty or is not recognizable GeoFlow QML.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', required=True)
    parser.add_argument('--backup-dir', required=True)
    parser.add_argument('--restore-empty', action='store_true')
    args = parser.parse_args()
    project = PurePosixPath(args.project_dir)
    base = PurePosixPath('/storage/emulated/0/Android/data/ch.opengis.qfield/files/Imported Projects')
    if project.parent != base or any(c in args.project_dir for c in "'\"\n\r\\"):
        parser.error('Select one direct child of the QField Imported Projects directory.')
    if adb('get-state').strip() != b'device':
        raise RuntimeError('Authorize exactly one ADB device first.')
    if adb('shell', 'pidof', 'ch.opengis.qfield', check=False).strip():
        raise RuntimeError('Save edits and stop QField before running recovery.')
    root = Path(args.backup_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix='qfield-recovery-', dir=root))
    # Copy the whole selected project before considering any phone mutation.
    adb('pull', str(project), str(saved))
    folder = saved / project.name
    runtime = folder / 'geoflow-field.qml'
    backup = folder / 'geoflow-field.qml.before-launcher.bak'
    if not (folder / 'geoflow-field.qgs').is_file():
        raise RuntimeError('Project backup verification failed; no phone changes made.')
    print('Project backup:', saved)
    print('Runtime bytes:', runtime.stat().st_size if runtime.exists() else 'missing')
    print('Backup bytes:', backup.stat().st_size if backup.exists() else 'missing')
    if not args.restore_empty:
        print('Inspection only; no phone files changed.')
        return
    validate_restore(runtime.read_bytes(), backup.read_bytes())
    remote = str(project / runtime.name)
    # Recheck immediately before overwrite: never replace a recovered/nonempty file.
    if adb('shell', 'pidof', 'ch.opengis.qfield', check=False).strip():
        raise RuntimeError('QField restarted; recovery stopped.')
    validate_restore(adb('exec-out', 'cat', "'" + remote + "'"), backup.read_bytes())
    adb('push', str(backup), remote)
    restored = adb('exec-out', 'cat', "'" + remote + "'")
    if hashlib.sha256(restored).digest() != hashlib.sha256(backup.read_bytes()).digest():
        raise RuntimeError('Restore verification failed; retain the PC backup and report this error.')
    print('Restored and verified only geoflow-field.qml; original backup retained.')


if __name__ == '__main__':
    main()
