from pathlib import Path
import unittest


class IroomsngS3ReadonlyContractTests(unittest.TestCase):
    def test_workflow_is_read_only_and_secret_safe(self):
        path = Path('.github/workflows/iroomsng-s3-readonly-diagnostic.yml')
        text = path.read_text(encoding='utf-8')

        self.assertIn('environment: production', text)
        self.assertIn('Checkout exact triggering release SHA', text)
        self.assertIn('sts.get_caller_identity()', text)
        self.assertIn('s3.head_bucket(Bucket=bucket)', text)
        self.assertIn('s3.get_bucket_location(Bucket=bucket)', text)
        self.assertIn('s3.list_objects_v2(Bucket=bucket, MaxKeys=1)', text)
        self.assertIn('iam.simulate_principal_policy(', text)
        self.assertIn('cloudtrail.lookup_events(', text)
        self.assertIn('iroomsng_s3_readonly_diagnostic_complete=yes', text)

        forbidden = (
            '.put_object(',
            '.upload_file(',
            '.upload_fileobj(',
            '.delete_object(',
            '.delete_objects(',
            '.copy_object(',
            '.create_bucket(',
            '.put_bucket_',
            'systemctl restart',
            'systemctl start',
            'systemctl stop',
            'systemctl enable',
            'systemctl disable',
            'systemctl daemon-reload',
            'nginx -s',
            'service nginx',
            'manage.py migrate',
            'git -C',
        )
        for token in forbidden:
            self.assertNotIn(token, text)

        self.assertNotIn('print(access_key)', text)
        self.assertNotIn('print(secret_key)', text)
        self.assertNotIn('print(bucket)', text)
        self.assertNotIn('print(identity_arn)', text)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY=', text)
        self.assertNotIn('AWS_ACCESS_KEY_ID=', text)


if __name__ == '__main__':
    unittest.main()
