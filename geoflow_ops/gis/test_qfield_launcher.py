import io
from pathlib import Path
import unittest
import zipfile
from django.test import RequestFactory, override_settings
from .qfield_launcher import launcher_download
from scripts.dev.recover_qfield_runtime import validate_restore


class LauncherRecoveryTests(unittest.TestCase):
    def test_archive_only_contains_registration_plugin(self):
        with override_settings(BASE_DIR=Path(__file__).resolve().parents[2]):
            response = launcher_download(RequestFactory().get('/gis/qfield/launcher.zip'))
            with zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content))) as archive:
                self.assertEqual(set(archive.namelist()), {'main.qml', 'metadata.txt'})
                qml = archive.read('main.qml').decode()
                self.assertNotIn('writeFileContent', qml)
                self.assertNotIn('readFileContent', qml)
                self.assertIn('version=0.1.2', archive.read('metadata.txt').decode())
            response.close()

    def test_restore_rejects_existing_runtime_and_bad_backups(self):
        good = b'import QtQuick\n// GeoFlow'
        validate_restore(b'', good)
        for current, backup in [(good, good), (b'', b''), (b'', b'unrelated')]:
            with self.subTest(current=current, backup=backup):
                with self.assertRaises(ValueError):
                    validate_restore(current, backup)

    def test_database_diagnostics_do_not_log_exception_text(self):
        from .qfield_db_diagnostics import log_changeset_database_error
        from types import SimpleNamespace
        cause = Exception('SECRET row value and SQL')
        cause.sqlstate = '23502'
        cause.diag = SimpleNamespace(schema_name='gis', table_name='doro', column_name='id', constraint_name=None, message_primary='invalid input syntax for type uuid: SECRET')
        exc = Exception('SECRET request')
        exc.__cause__ = cause
        with self.assertLogs('geoflow_ops.gis.qfield_db_diagnostics', level='ERROR') as logs:
            log_changeset_database_error(exc)
        self.assertIn('23502', logs.output[0])
        self.assertIn('column=id', logs.output[0])
        self.assertIn('target_type=uuid', logs.output[0])
        self.assertNotIn('SECRET', logs.output[0])
