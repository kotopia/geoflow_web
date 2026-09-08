import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts.dev import recover_qfield_runtime as recovery


class DeviceFileReadTests(unittest.TestCase):
    def test_file_bytes_are_used_instead_of_adb_output(self):
        remote = '/storage/emulated/0/Imported Projects/project/runtime.qml'
        for content in (b'', b'import QtQuick\n// GeoFlow'):
            with self.subTest(content=content):
                def pull(*args):
                    self.assertEqual(args[:2], ('pull', remote))
                    Path(args[2]).write_bytes(content)
                    return b'adb transfer status or diagnostics'
                with patch.object(recovery, 'adb', side_effect=pull):
                    self.assertEqual(recovery.read_device_file(remote), content)

    def test_failed_transfer_cannot_be_interpreted_as_empty_file(self):
        with patch.object(recovery, 'adb', side_effect=subprocess.CalledProcessError(1, ['adb'])):
            with self.assertRaises(subprocess.CalledProcessError):
                recovery.read_device_file('/missing')

    def test_missing_local_file_fails_closed(self):
        with patch.object(recovery, 'adb', return_value=b'error'):
            with self.assertRaises(FileNotFoundError):
                recovery.read_device_file('/missing')

    def test_nonempty_runtime_still_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):
            recovery.validate_restore(b'current runtime', b'import QtQuick\n// GeoFlow')
