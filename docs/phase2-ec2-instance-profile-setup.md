# GeoFlow Phase 2: EC2 instance profile setup gate

## Purpose

This is the infrastructure step required before the existing read-only `Phase 2 AWS role readiness diagnostic` can pass. The application already uses the standard boto3 credential provider chain. This step adds an EC2 role credential source without removing the current production credential fallback.

Do not remove, rotate, disable, or print the existing long-lived AWS credentials during this setup step.

## Prepared templates

- `docs/phase2-ec2-trust-policy-template.json`
- `docs/phase2-runtime-iam-policy-template.json`

The runtime policy deliberately contains placeholders instead of production identifiers. Before creating the role, replace only the following placeholders in a private AWS administration context:

- `${AWS_REGION}`
- `${ACCOUNT_ID}`
- `${TENANT_SECRET_NAME_PREFIX}`
- `${GEOFLOW_BUCKET_NAME}`

Do not commit the substituted production policy back to the repository.

## Minimum role contract

The role is limited to:

- `secretsmanager:GetSecretValue` for the tenant database secret namespace;
- `s3:ListBucket` constrained to the `tenants/*` prefix;
- `s3:GetObject` under `tenants/*`;
- `s3:PutObject` under `tenants/*`.

The base policy intentionally excludes `s3:DeleteObject`, IAM administration, EC2 administration, RDS administration, and Secrets Manager mutation actions.

If production uses a customer-managed KMS key, add only the exact KMS permissions required for that key. S3 SSE-KMS reads normally need decrypt capability and writes normally need data-key generation; Secrets Manager may also require decrypt capability for a customer-managed secret key. Do not add wildcard KMS resources.

## Attach sequence

1. Create an IAM role whose trust relationship is restricted to the EC2 service using the reviewed trust template.
2. Create or attach the minimum runtime policy after privately substituting the production placeholders.
3. Attach the resulting instance profile to the production GeoFlow EC2 instance.
4. Do **not** edit `.env`, systemd, application files, Secrets Manager data, S3 objects, or databases in this step.
5. Confirm the instance remains healthy.
6. Run `.github/workflows/phase2-aws-role-readiness-diagnostic.yml` from `release/stabilized-deploy`.

The diagnostic itself removes static/profile credential sources only inside its own process. It must report role credentials plus successful active-tenant secret resolution and S3 read readiness before any role-only cutover is attempted.

## Stop conditions

Stop before cutover if any of these is true:

- no instance/container role credentials are detected;
- any active tenant secret reference cannot resolve through the role;
- S3 bucket/list/read readiness fails;
- the service is unhealthy;
- the role requires permissions broader than the documented contract without a reviewed technical reason.

The old access key must remain available until the separate role-only cutover and post-cutover tenant/S3 validation are complete.
