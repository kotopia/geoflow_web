from pathlib import Path
from unittest import TestCase


class IroomsngS3PolicyShapeContractTests(TestCase):
    def test_diagnostic_is_bounded_and_read_only(self):
        path = Path('.github/workflows/iroomsng-s3-policy-shape-diagnostic.yml')
        text = path.read_text(encoding='utf-8')

        self.assertIn('environment: production', text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertIn('get_bucket_encryption', text)
        self.assertIn('get_bucket_ownership_controls', text)
        self.assertIn('get_public_access_block', text)
        self.assertIn('get_bucket_policy', text)
        self.assertIn('list_attached_user_policies', text)
        self.assertIn('list_user_policies', text)

        forbidden = (
            '.put_object(',
            '.upload_file(',
            '.upload_fileobj(',
            '.copy_object(',
            '.delete_object(',
            '.delete_objects(',
            'systemctl restart',
            'systemctl start',
            'systemctl stop',
            'systemctl enable',
            'systemctl disable',
            'systemctl reload',
            'manage.py migrate',
            'aws_secret_access_key=',
            'print(access_key',
            'print(secret_key',
            'print(bucket',
            'print(identity_arn',
            'print(raw)',
            'print(bucket_policy',
        )
        for token in forbidden:
            self.assertNotIn(token, text)

        self.assertIn('iroomsng_s3_policy_shape_diagnostic_complete=yes', text)
