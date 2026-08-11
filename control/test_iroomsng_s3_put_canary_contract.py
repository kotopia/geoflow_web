from pathlib import Path
from unittest import TestCase


class IroomsngS3PutCanaryContractTests(TestCase):
    def test_canary_is_minimal_bounded_and_gated(self):
        path = Path('.github/workflows/iroomsng-s3-put-canary.yml')
        text = path.read_text(encoding='utf-8')

        self.assertIn('environment: production', text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertIn('s3.put_object(', text)
        self.assertIn('Body=b""', text)
        self.assertIn('__iroomsng_diagnostic__/zero-byte-put-canary-', text)
        self.assertIn('s3.delete_object(', text)
        self.assertIn('iroomsng_s3_canary_cleanup_required=', text)
        self.assertIn('iroomsng_s3_zero_byte_put_canary_complete=yes', text)

        forbidden = (
            '.upload_file(',
            '.upload_fileobj(',
            '.copy_object(',
            '.delete_objects(',
            'ACL=',
            'ServerSideEncryption=',
            'SSEKMSKeyId=',
            'systemctl restart',
            'systemctl start',
            'systemctl stop',
            'systemctl enable',
            'systemctl disable',
            'systemctl reload',
            'manage.py migrate',
            'print(access_key',
            'print(secret_key',
            'print(bucket',
            'print(key',
        )
        for token in forbidden:
            self.assertNotIn(token, text)

        self.assertEqual(text.count('s3.put_object('), 1)
        self.assertEqual(text.count('s3.delete_object('), 1)
