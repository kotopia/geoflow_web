from pathlib import Path
from unittest import TestCase


class IroomsngMinimalRuntimeRecoveryContractTests(TestCase):
    def test_recovery_is_narrow_gated_and_rollback_capable(self):
        path = Path('.github/workflows/iroomsng-minimal-runtime-recovery.yml')
        text = path.read_text(encoding='utf-8')

        required = (
            'environment: production',
            'ref: ${{ github.sha }}',
            "primary='geoflow.service'",
            "duplicate='gunicorn.service'",
            "stable='geoflow-stabilized.service'",
            "Django==5.0.6",
            '--system-site-packages',
            'legacy-user-site.pth',
            'SELECT 1',
            'rollback() {',
            '90-iroomsng-django50-recovery.conf',
            'upload_file_to_s3',
            "Image.new('RGB'",
            's3.head_object(',
            's3.delete_object(',
            'iroomsng_recovery_web_complete=yes',
            'iroomsng_recovery_complete=yes',
        )
        for token in required:
            self.assertIn(token, text)

        forbidden = (
            'manage.py migrate',
            ' migrate ',
            'makemigrations',
            'psql ',
            'DROP TABLE',
            'ALTER TABLE',
            'UPDATE ',
            'INSERT INTO',
            'DELETE FROM',
            'git pull',
            'git checkout',
            'git reset',
            'git clean',
            'apt install',
            'apt-get install',
            'systemctl restart nginx',
            'systemctl reload nginx',
            '/etc/nginx/',
            '.put_bucket_policy(',
            '.delete_bucket_policy(',
            '.put_public_access_block(',
            '.put_bucket_encryption(',
            '.put_bucket_ownership_controls(',
            '.attach_user_policy(',
            '.put_user_policy(',
            '.create_access_key(',
            '.delete_access_key(',
            '.put_object(',
            '.upload_file(',
            '.upload_fileobj(',
            '.copy_object(',
            '.delete_objects(',
            'print(settings.AWS_ACCESS_KEY_ID',
            'print(settings.AWS_SECRET_ACCESS_KEY',
            'print(settings.AWS_STORAGE_BUCKET_NAME',
            'echo "$exec_raw"',
            'echo "$wd"',
            'echo "$user_home"',
        )
        for token in forbidden:
            self.assertNotIn(token, text)

        # Only the isolated venv receives pip changes; never the legacy/global runtime.
        self.assertIn('"$venv/bin/python" -m pip install', text)
        self.assertNotIn('"$runtime_python" -m pip install', text)

        # Nginx remains untouched; public health is verification only.
        self.assertIn('https://iroomsng.kr/', text)
        self.assertNotIn('nginx -s', text)

        # App source is not edited by the recovery workflow.
        self.assertNotIn('sed -i', text)
        self.assertNotIn('perl -pi', text)
        self.assertNotIn('apply_patch', text)
