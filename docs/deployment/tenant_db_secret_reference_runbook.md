# Tenant database credential secret-reference runbook

Status: implementation prepared; live credential migration still requires an approved runtime with access to AWS Secrets Manager and the central database.

## Goal

`group_db_config.db_password` must stop carrying reusable tenant database passwords in plaintext. The existing column is retained to avoid a schema migration; after cutover it stores only an external secret reference.

Supported reference format:

```text
aws-secretsmanager:<secret-id>#<json-key>
```

Examples must use non-secret identifiers only. The secret value itself must never be copied into source, logs, screenshots, tickets, or command output.

## Runtime behavior

- `control.services.tenant_db_secret_resolver` recognizes the reference format and resolves it through AWS Secrets Manager only when a tenant connection is actually needed.
- `control.tenant_connections` places only the resolved in-memory value into Django's dynamic connection dictionary.
- No secret value is logged on resolution failure.
- Before cutover, legacy plaintext remains readable only while `TENANT_DB_REQUIRE_SECRET_REFERENCES` is disabled.
- After all rows are converted, set `TENANT_DB_REQUIRE_SECRET_REFERENCES=1`; a plaintext or malformed value then fails closed.

## Read-only audit

After central DB access is available, run:

```text
python manage.py check_tenant_db_secret_refs --strict
```

The command does not resolve AWS secrets and does not print stored values. It reports counts only. Strict mode fails when any configured row remains plaintext or malformed.

## Ordered live migration

1. Inventory active `group_db_config` rows without printing `db_password` values.
2. For each tenant DB credential, create or identify an AWS Secrets Manager secret in `ap-northeast-2` using the least-privilege application IAM role.
3. Put the actual DB password only in Secrets Manager. Prefer a JSON secret with a `password` key when rotation metadata may later be added.
4. Verify the application role can call `secretsmanager:GetSecretValue` only for the intended tenant credential secret ARNs.
5. In a non-production tenant first, replace `group_db_config.db_password` with the corresponding `aws-secretsmanager:...#password` reference.
6. Exercise tenant selection and a read-only tenant request. Confirm failures are generic and no secret is logged.
7. Repeat for production tenant rows during the approved change window.
8. Run `python manage.py check_tenant_db_secret_refs --strict` and require zero legacy/invalid rows.
9. Set `TENANT_DB_REQUIRE_SECRET_REFERENCES=1` in the public application runtime.
10. Run `python manage.py check_release_preflight --strict`.
11. Re-test tenant selection and representative read-only tenant pages.
12. Only after successful cutover, rotate any historical DB passwords that were previously stored in plaintext. Do not rotate blindly before the application uses the corresponding secret reference.

## Rollback

If secret resolution fails during cutover, restore the prior application configuration window rather than exposing the password in logs or source. A temporary rollback to a legacy stored credential must be treated as an incident-limited compatibility step and followed by a new secret migration and password rotation.

## Remaining infrastructure requirements

Repository code alone cannot verify:

- existing central DB row contents;
- Secrets Manager secret existence or values;
- IAM permissions and resource policies;
- DB credential rotation state;
- EC2 task/instance-role attachment.

Those require live AWS/DB access. Passing repository preflight is not evidence that the external secret migration is complete.
