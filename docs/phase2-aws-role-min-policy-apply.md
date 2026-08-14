# Phase 2 guarded minimum runtime IAM policy apply

This one-time production-gated operation exists only to close Phase 2 issue #10 when the EC2 instance role is valid but lacks the reviewed runtime authorization.

It derives the exact active tenant Secrets Manager ARNs and configured private S3 bucket scope in memory using the already-existing fallback credentials. Those identifiers and credential values are never printed or committed. It then attempts exactly one inline policy on the already-attached EC2 role with the same minimum contract documented in `phase2-runtime-iam-policy-template.json`: `secretsmanager:GetSecretValue` for the active tenant secret resources, `s3:ListBucket` constrained to `tenants/*`, and `s3:GetObject`/`s3:PutObject` under `tenants/*`.

The operation does not create roles, change the EC2 instance profile, modify Secrets Manager data, modify S3 objects, change databases, or alter the application service. If the existing fallback principal lacks `iam:PutRolePolicy`, the operation fails before IAM mutation. After a successful policy write, verification switches back to instance-role credentials only. If that verification fails, the workflow attempts to delete the one inline policy it just created.

The workflow is triggered only by the reviewed release merge and remains behind the protected GitHub `production` Environment. The existing long-lived fallback credential remains untouched until the separate reviewed role-only runtime cutover succeeds.