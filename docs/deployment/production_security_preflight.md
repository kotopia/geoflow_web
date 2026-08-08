# GeoFlow production security preflight

Status date: 2026-08-09

This checklist separates repository-level safeguards that are already implemented
from changes that require a real deployment environment, database, S3 bucket,
mail provider, reverse proxy, or scheduler.

## 0. Required execution order

Keep release validation in this order so a later operational action cannot hide an
earlier repository/configuration failure.

### A. Repository/runtime-shape checks — no live infrastructure access

1. Use an isolated non-production Python environment.
2. Install the exact versions in `requirements.txt`.
3. Run `python manage.py check_release_preflight --strict`.
4. Treat every `FAIL` as a release blocker. `WARN` items for SSL redirect, HSTS, or
   proxy headers require live proxy verification before they can be resolved safely.
5. Do not print `.env` or secret values while diagnosing a failed check.

`check_release_preflight --strict` is intentionally limited to configuration shape,
Django security baseline, secret-key quality, database transport/configuration shape,
object-storage configuration shape, cookie/session/browser policy, and reviewed URL
security boundaries. It does not query the database, send mail, access S3, or probe
the network.

The repository now pins the approved Django 5.2 LTS security patch baseline:
`Django==5.2.16`. Framework installation and full Django tests still require an
isolated runtime environment containing the required Python/GeoDjango dependencies.

The static release preflight also requires
`TENANT_DB_REQUIRE_SECRET_REFERENCES=1`. Do not enable that runtime flag until every
active `group_db_config.db_password` value has been converted from a reusable
password to an approved external secret reference.

### B. Dependency validation — isolated environment only

Install the exact requirements in an isolated non-production environment and run:

1. `python manage.py check`;
2. the Phase 1 signup/security regression tests; and
3. `python manage.py check_release_preflight --strict` again.

Do not combine a framework patch upgrade with an unrelated schema migration or
production data cleanup in the same rollback unit.

### C. Database-backed validation — read-only first

Only after A and B pass should a specifically approved non-production central DB be
used for the read-only audits:

```text
python manage.py check_signup_launch_schema --strict
python manage.py check_tenant_db_secret_refs --strict
```

Both commands are database access operations. The schema command checks structural
launch prerequisites; the tenant-secret command reports counts only and never
resolves or prints tenant DB passwords. Migration rehearsal comes after these audits.

### D. External-service validation

After schema validation, verify the HTTPS/proxy contract, AWS Secrets Manager access,
SMTP/HMAC delivery runtime, S3 behavior, worker/scheduler supervision, and finally
application deployment. Keep public signup closed until every required gate has
passed.

## 1. Repository safeguards already in place

### Central identity and signup

- Public signup creates inactive, unverified central users.
- Email verification and central approval remain separate lifecycle transitions.
- Central login requires both an active and verified central account before session
  creation.
- Authenticated sessions are revalidated against central account state.
- Tenant membership freshness requires an active central account, active membership,
  active group, and matching tenant DB alias.
- Legacy implicit account provisioning cannot create or activate a central account.
- Legacy invitation password-email code no longer creates a new raw-token delivery
  path.
- Legacy password URLs use no-cache/no-referrer wrappers while they remain available.
- Logout and tenant selection are CSRF-protected POST state transitions.
- The Django `auth_user` record is treated as a non-privileged session bridge for
  confirmed GeoFlow central identities.

### Tenant authorization and attachments

- The tenant root requires an authenticated current tenant context.
- Reviewed project, contract, partner, organization-unit, employee, event, and
  attachment routes use explicit tenant/permission/method boundaries.
- Sensitive employee/event reads are marked non-cacheable.
- Attachment presign/commit operations enforce supported entity/purpose combinations,
  caller authorization, object-key scope, declared size, actual S3 object size/type,
  and server-side-encryption metadata before DB commit.
- Attachment metadata/event linking is transactional after object verification.
- Presigned download responses are non-cacheable and constrain content disposition
  and filenames.
- Attachment delete is currently a metadata soft delete; physical S3 lifecycle remains
  an operations/governance item.

### Tenant database credentials

- Dynamic tenant DB credentials can now be represented as
  `aws-secretsmanager:<secret-id>#<json-key>` references in the existing
  `group_db_config.db_password` column; no schema migration is required for the
  reference format.
- The runtime resolves a reference only when a tenant DB connection is needed.
- Resolution failures are generic and do not log secret values.
- `TENANT_DB_REQUIRE_SECRET_REFERENCES=1` makes plaintext/malformed tenant DB
  credentials fail closed after the live conversion is complete.
- `python manage.py check_tenant_db_secret_refs --strict` audits stored reference
  shape without resolving or printing secret values.
- The ordered conversion/rollback procedure is documented in
  `tenant_db_secret_reference_runbook.md`.

### Privacy

- New RRN collection, encryption, decryption, and display paths are disabled in the
  active employee application flow.
- Non-empty direct `rrn_plain` submissions are rejected.
- Existing tenant DB RRN values, if any, have not been inventoried or deleted by
  repository work. That remains a live-data governance task.

## 2. Required live-environment checks before public launch

### Database and schema

1. Confirm the target central DB and a non-production validation environment.
2. Run `check_signup_launch_schema --strict` against the approved non-production
   central DB.
3. Run `check_tenant_db_secret_refs --strict`; do not proceed with secret-reference
   enforcement while legacy or malformed rows remain.
4. Review pending signup migrations and the exact migration/rollback plan.
5. Apply/rehearse migrations outside production before any production migration.
6. Re-run Django/system tests against the migrated schema.
7. Validate central account erasure and signup lifecycle behavior against disposable
   records and real FK relationships.
8. Inventory historical tenant RRN columns/values and decide retention/destruction
   before any deletion.

### Tenant DB secret-reference cutover

1. Create/identify Secrets Manager secrets in `ap-northeast-2` without exposing the
   underlying password values.
2. Restrict the application IAM role to `secretsmanager:GetSecretValue` for only the
   required tenant secret ARNs.
3. Convert one non-production `group_db_config.db_password` value to a secret
   reference and exercise tenant selection/read-only access.
4. Convert the remaining intended production tenant rows during the approved window.
5. Require `check_tenant_db_secret_refs --strict` to pass.
6. Set `TENANT_DB_REQUIRE_SECRET_REFERENCES=1` and re-run
   `check_release_preflight --strict`.
7. Only after successful application cutover, rotate historical DB passwords that
   were previously stored directly in the central DB.

### Reverse proxy and HTTPS

1. Confirm canonical production origin `https://geoflow.co.kr`.
2. Confirm the trusted proxy terminates TLS and overwrites the forwarded-proto header.
3. Configure `SECURE_PROXY_SSL_HEADER` only for a trusted proxy contract.
4. Verify secure session/CSRF cookies end-to-end.
5. Enable/test `SECURE_SSL_REDIRECT` without redirect loops.
6. Stage HSTS only after HTTPS is stable.
7. Keep `DJANGO_DEBUG=0` and verify stock Django admin is absent.
8. Require explicit HTTPS, non-wildcard, non-local CSRF trusted origins.

### Signup email verification

1. Configure NAVER SMTP credentials only in the runtime secret/environment store.
2. Configure the production sender and canonical public URLs.
3. Configure the signup verification HMAC key ring and active key id.
4. Confirm TTL, resend cooldown, retry, timeout, lease, and max-attempt settings.
5. Run a controlled non-production delivery test.
6. Start/supervise the verification outbox worker only after schema/mail validation.
7. Keep the public legal confirmation/activation gate closed until all checks pass.

### S3 lifecycle and orphan objects

1. Confirm the production bucket/prefix layout and ownership boundary.
2. Confirm the runtime identity has only required object/KMS permissions.
3. Exercise presign -> upload -> commit -> download against a non-production object.
4. Verify actual ContentLength, ContentType, and SSE/KMS metadata enforcement.
5. Define orphan reconciliation/lifecycle separately from attachment soft deletion.
6. Use dry-run inventory before any physical delete/lifecycle rule.

### Scheduled lifecycle jobs

1. Validate signup expiry and one-year rejected/expired retention against a migrated
   non-production central DB.
2. Confirm the scheduler/service mechanism and least-privilege service account.
3. Run dry-run/reporting modes where available before execute modes.
4. Add alerting for failures and document cadence/operator ownership.

## 3. Transitional legacy surface

The legacy set-password URL remains temporarily available for compatibility. Its
response is no-cache/no-referrer, but a raw path token can still appear in reverse
proxy/access logs. Remove both aliases together after confirming no active process
uses them and outstanding tokens are expired or invalidated under an approved DB
procedure.

One P1 code debt remains in employee detail: a GET can populate
`hr.employee_profile.central_user_id` when it is empty. It should ultimately become a
read-only central identity lookup plus an explicit `directory.edit` synchronization
path. Do not treat the current cache write as authorization state; central roles and
permissions remain authoritative.

## 4. Go-live stop conditions

Do not enable public signup or deploy the Phase 1 release if any of these conditions
is true:

- `check_release_preflight --strict` fails;
- runtime Django is below 5.2.16 in the approved 5.2 LTS series;
- `check_signup_launch_schema --strict` fails;
- `check_tenant_db_secret_refs --strict` reports legacy/malformed credentials;
- `TENANT_DB_REQUIRE_SECRET_REFERENCES=1` cannot be enabled safely;
- migrations have not been validated against the intended schema;
- SMTP/HMAC/HTTPS runtime readiness is incomplete;
- production proxy scheme handling is unknown;
- the outbox worker cannot be supervised;
- a critical authorization regression is found;
- historical high-risk identifier handling is unresolved for the intended tenant
  onboarding scope; or
- application rollback cannot be performed independently of irreversible DB changes.

## 5. Operational evidence to retain

For the final change record, retain only non-secret evidence:

- exact application commit SHA;
- requirements/Django version;
- PASS/FAIL output from repository preflight;
- PASS/FAIL/count output from read-only DB audits;
- migration identifiers/checksums and rollback plan;
- public HTTPS/legal-page smoke-test results;
- worker/service health state;
- IAM policy/resource identifiers without credential material;
- deployment timestamp and rollback result if used.

Never attach `.env`, DB passwords, SMTP passwords, raw signup tokens, HMAC key
material, Secrets Manager secret values, or AWS secret keys to the evidence record.
