# Phase 2 runtime IAM policy template

This is a placeholder-only policy shape for the GeoFlow EC2 runtime role. Replace placeholders in AWS before use. Do not commit real account IDs, ARNs, bucket names, secret identifiers, or KMS key identifiers to this repository.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadTenantDatabaseSecrets",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "<TENANT_DB_SECRET_NAMESPACE_ARN>"
    },
    {
      "Sid": "ListGeoFlowPrivateObjects",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "<GEOFLOW_BUCKET_ARN>",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "tenants/*"
          ]
        }
      }
    },
    {
      "Sid": "ReadWriteGeoFlowPrivateObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "<GEOFLOW_BUCKET_ARN>/tenants/*"
    }
  ]
}
```

`S3:DeleteObject` is intentionally excluded because the current application soft-deletes attachment metadata and does not delete the backing object.

If the production bucket or tenant secrets use a customer-managed KMS key, add only the KMS permissions required by the actual encryption path and scope them to the exact key. Do not add broad IAM, EC2, RDS inventory, Secrets Manager mutation, or S3 administration permissions to the runtime role.

After the instance profile is attached, run `.github/workflows/phase2-aws-role-readiness-diagnostic.yml` before removing any existing runtime credential variables.
