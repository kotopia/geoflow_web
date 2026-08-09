# GeoFlow Phase 2: AWS IAM role and release-branch hardening

## Current status — 2026-08-10

Confirmed without exposing production identifiers or credentials:

- Secrets Manager client construction uses the standard boto3 credential provider chain; static AWS credentials are not passed directly to boto3.
- S3 client construction uses the standard boto3 credential provider chain; static AWS credentials are not passed directly to boto3.
- A real pull request targeting `release/stabilized-deploy` emitted and passed all three release checks: `release-preflight`, `migration-rehearsal`, and `public-https-smoke`.
- Repository rulesets are currently absent, so Stage B protection is not yet enforced through a repository ruleset.
- The existing read-only IAM-role readiness diagnostic previously failed with `phase2_role_diag_blocker=no_role_credentials` after static/profile AWS credential sources were removed only inside the diagnostic process. This confirms the next AWS infrastructure dependency is an EC2 instance profile/runtime role credential source; it does not indicate an application credential-chain defect.

Next infrastructure action before role cutover:

1. Attach the minimum-permission EC2 instance profile to the production GeoFlow instance.
2. Re-run `.github/workflows/phase2-aws-role-readiness-diagnostic.yml`.
3. Continue only when it reports role credentials, active tenant secret resolution, and S3 read readiness as successful.

## Scope

This plan removes the application's dependency on long-lived AWS access keys and prepares `release/stabilized-deploy` for enforced CI-based protection. It intentionally contains no credential values, tenant identifiers, account IDs, ARNs, endpoints, database identifiers, or secret identifiers.

## 1. Application credential behavior

The application must use the standard boto3 credential provider chain. Application code must not pass `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or `AWS_SESSION_TOKEN` directly to boto3 clients.

The production cutover sequence is:

1. Attach an EC2 instance profile with the minimum runtime permissions.
2. Run the read-only role-readiness diagnostic with static/profile credentials removed only inside the diagnostic process.
3. Require all active tenant DB secret references to resolve through the role.
4. Require S3 bucket/list/read probes to succeed through the role.
5. Deploy the reviewed default-chain application code.
6. Remove long-lived AWS credential variables from the production runtime configuration.
7. Restart the application service.
8. Verify tenant login/DB resolution, object-storage read/upload behavior, and public HTTPS/legal endpoints.
9. Only after successful validation, deactivate the superseded IAM user's access keys using a separate controlled AWS change.

Rollback before key deactivation is to restore the prior runtime credential variables and restart the service. The old keys must not be deleted until the role-only runtime has been proven healthy.

## 2. Minimum runtime IAM permissions

The runtime role should be restricted to the production GeoFlow bucket and the tenant DB secret namespace. Do not carry forward diagnostic or migration permissions such as RDS inventory, secret creation, IAM administration, EC2 administration, or secret mutation.

Required runtime actions:

- `secretsmanager:GetSecretValue` for tenant DB credential secrets only.
- `s3:ListBucket` on the private application bucket, preferably constrained to the `tenants/` prefix where practical.
- `s3:GetObject` for private application objects under `tenants/*`.
- `s3:PutObject` for private application objects under `tenants/*`.

The current application soft-deletes attachment metadata and does not delete the backing S3 object, so `s3:DeleteObject` is not part of the minimum runtime role.

If the bucket uses a customer-managed KMS key, add only the KMS actions actually required by S3/Secrets Manager for that key. For S3 SSE-KMS uploads this normally includes data-key generation; reads require decrypt capability. Scope KMS access to the exact key and services where possible.

## 3. Role-readiness acceptance criteria

`.github/workflows/phase2-aws-role-readiness-diagnostic.yml` is read-only and protected by the GitHub `production` environment. It must not change `.env`, systemd, IAM, Secrets Manager, S3 objects, RDS, or application databases.

The diagnostic is accepted only when:

- boto3 obtains credentials from an instance/container role rather than a static/profile source;
- every active tenant DB secret reference resolves successfully through the role;
- S3 bucket and prefix listing succeeds through the role;
- a one-byte range read succeeds when at least one private object exists;
- no credential value, secret identifier, object key, bucket name, tenant identifier, DB identifier, account ID, or ARN is printed.

A live S3 PUT probe is intentionally excluded because the diagnostic is read-only. PUT is validated after cutover through the application upload flow.

## 4. Release branch protection rollout

Current release checks are:

- `release-preflight`
- `migration-rehearsal`
- `public-https-smoke`

The release preflight workflow must run on pull requests targeting `release/stabilized-deploy` before any status check is made mandatory.

Recommended rollout:

### Stage A — low-disruption protection

- block force pushes;
- block branch deletion;
- keep direct fast-forward pushes temporarily available while the PR path is being proven;
- retain the existing protected `production` environment for operational workflows.

### Stage B — PR and CI enforcement

After a real test PR proves all three checks are emitted and pass on `pull_request`:

- require a pull request before merging to `release/stabilized-deploy`;
- require `release-preflight`, `migration-rehearsal`, and `public-https-smoke`;
- require the branch to be up to date before merge if the repository's merge cadence supports it;
- continue blocking force pushes and deletion;
- do not allow administrators to bypass unless an explicit break-glass policy is created.

Because the repository previously used direct pushes, Stage B changes the operational development flow and should be enabled only after the test PR succeeds.

## 5. Validation and rollback

Repository validation:

- open a feature-branch PR targeting `release/stabilized-deploy`;
- verify all three release checks are created by the PR event and complete successfully;
- review the changed-file set;
- merge only after checks pass.

Production role cutover validation:

- role-readiness diagnostic passes;
- reviewed code is deployed;
- static AWS runtime variables are removed without printing values;
- service restart succeeds;
- active tenant secret resolution and DB connectivity succeed;
- private S3 download and upload flows succeed;
- public HTTPS/legal endpoints remain healthy.

Rollback immediately if any role-only secret resolution, tenant DB connection, S3 access, or service-health check fails. Do not deactivate old IAM access keys until the entire post-cutover validation set passes.
