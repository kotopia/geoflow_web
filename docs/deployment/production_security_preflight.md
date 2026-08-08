# GeoFlow production security preflight

Status date: 2026-08-08

This checklist separates repository-level safeguards that are already implemented
from changes that require a real deployment environment, database, S3 bucket,
mail provider, reverse proxy, or scheduler. Do not treat this document as approval
to perform any live operation.

## 0. Required execution order

Keep release validation in this order so a later operational action cannot hide an
earlier repository/configuration failure.

### A. Repository/runtime-shape checks — no live infrastructure access

1. Use an isolated non-production Python environment.
2. Run `python manage.py check_release_preflight --strict`.
3. Treat every `FAIL` as a release blocker. `WARN` items for SSL redirect, HSTS, or
   proxy headers require live proxy verification before they can be resolved safely.
4. Do not print `.env` or secret values while diagnosing a failed check.

`check_release_preflight --strict` is intentionally limited to configuration shape,
Django security baseline, and cookie/session policy. It does not query the database,
send mail, access S3, or probe the network.

The release preflight currently requires the approved Django 5.2 LTS security patch
baseline of at least Django 5.2.16. The repository still pins Django 5.2.4 until the
protected `requirements.txt` dependency change receives its own explicit approval.
See `docs/deployment/django_5_2_security_upgrade_plan.md`.

### B. Dependency validation — isolated environment only

After the dependency pin change is explicitly approved, install the exact requirements
in an isolated non-production environment and run:

1. `python manage.py check`;
2. the Phase 1 signup/security regression tests; and
3. `python manage.py check_release_preflight --strict` again.

Do not combine a framework patch upgrade with a schema migration or production data
cleanup in the same change window.

### C. Database-backed validation — separate approval required

Only after A and B pass should a specifically approved non-production central DB be
used for the read-only schema audit:

`python manage.py check_signup_launch_schema --strict`

Despite being SELECT-only, this command is a database access operation and therefore
is not part of the repository-only preflight. Migration rehearsal comes after the
read-only audit and has its own approval boundary.

### D. External-service validation — separate approvals required

After schema validation, verify the HTTPS/proxy contract, SMTP/HMAC delivery runtime,
S3 behavior, worker/scheduler supervision, and finally application deployment. Keep
public signup closed until every required gate has passed.

## 1. Repository safeguards already in place

### Central identity and signup

- Public signup creates inactive, unverified central users.
- Email verification and central approval remain separate lifecycle transitions.
- Central login now requires both `users.is_active = TRUE` and
  `users.email_verified = TRUE` before password verification or session creation.
- Authenticated sessions are revalidated against the same active + verified
  requirement.
- Tenant membership freshness also requires an active + verified central account,
  active membership, active group, and matching tenant DB alias.
- Legacy implicit account provisioning cannot create or activate a central account.
- Legacy people provisioning can create only inactive, unverified, non-staff
  placeholders and rejects an activation request.
- The dormant legacy invitation password-email helper no longer creates raw reset
  tokens or sends invitation mail.
- Legacy password setup uses Django password validators, bounds password length,
  masks sensitive request/local values, disables response caching, and serializes
  token consumption with a row lock.
- Logout is a CSRF-protected POST rather than a GET side effect.

### Central administration

- Central category endpoints require a central administrator and GET-only reads.
- `/api/catalog/admin/*` routes require a central administrator.
- Catalog delete routes are POST-only at the URL boundary.
- Catalog facet-option reads require authentication.
- Stock Django `/admin/` is registered only when `DEBUG=True`; production
  administration is expected to use guarded GeoFlow control views.
- `/after-login/` requires an authenticated Django session before tenant routing.

### Tenant authorization and attachments

- The tenant root requires an authenticated, current tenant context.
- Project, contract, partner, organization-unit, event, employee, and attachment
  paths use tenant context and stored entity scope rather than trusting caller scope.
- Attachment presign/commit operations enforce supported entity/kind combinations,
  caller authorization, object-key scope, declared size, S3 object size/content
  type, and server-side encryption metadata before database commit.
- Default upload bounds are enforced before presign/commit.
- Active web content such as HTML, SVG, JavaScript, and XML is rejected for event
  attachments.
- Only explicitly safe MIME types are eligible for inline viewing; other content is
  forced to attachment download.
- Attachment delete is soft delete; no live S3 deletion is performed by the current
  application path.

### Privacy

- New RRN collection, encryption, decryption, and display paths are disabled in the
  application.
- The retired RRN encryption key is no longer a required Django boot dependency.
- Existing tenant database RRN values, if any, have not been inventoried or deleted.
  That is a separate live-data task.

## 2. Required live-environment checks before public launch

The following items require explicit authorization because they change or inspect a
real environment.

### Database and schema

1. Confirm the target central database and a non-production validation environment.
2. Run the read-only launch schema audit against the specifically approved
   non-production central DB.
3. Review pending signup migrations and the exact migration plan.
4. Apply migrations first outside production and run Django/system tests against the
   migrated schema.
5. Verify central users, signup requests/events, verification-token/outbox tables,
   join-request compatibility, and FK behavior.
6. Inventory historical tenant RRN columns/values and decide lawful retention or
   destruction before any deletion.
7. Validate central account erasure against real FK relationships before enabling
   an operational withdrawal/delete procedure.

Do not run migration, DDL, production queries, or tenant-data inventory solely from
this checklist.

### Reverse proxy and HTTPS

Before enabling Django SSL redirect or HSTS, verify the actual AWS/ALB/Nginx proxy
chain and how the original request scheme is conveyed.

1. Confirm canonical production origin: `https://geoflow.co.kr`.
2. Confirm the trusted proxy terminates TLS and sets the expected forwarded-proto
   header.
3. Configure `SECURE_PROXY_SSL_HEADER` only if that header is guaranteed to be
   overwritten by the trusted proxy. Never trust arbitrary client-supplied forwarded
   headers.
4. Confirm secure cookies work end-to-end with HTTPS.
5. Enable/test `SECURE_SSL_REDIRECT` only after proxy scheme handling is known to be
   correct; verify there is no redirect loop.
6. Stage HSTS only after HTTPS is stable. Start with a conservative max-age before
   considering a long max-age or `includeSubDomains`.
7. Keep `DJANGO_DEBUG=0` in production and verify the stock Django admin is absent.
8. Verify production `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` contain only required
   hosts/origins.

### Signup email verification

1. Configure the NAVER SMTP endpoint/account using environment variables; never
   store credentials in the repository.
2. Configure a real production `DEFAULT_FROM_EMAIL` and HTTPS `SITE_ORIGIN`.
3. Configure the signup verification HMAC key ring and active key id through the
   environment.
4. Confirm verification TTL, resend cooldown, retry, timeout, lease, and max-attempt
   settings.
5. Run a controlled non-production mail delivery test.
6. Start and supervise the signup verification outbox worker only after the migrated
   schema and mail configuration are validated.
7. Keep the public signup confirmation/activation gate closed until all of the above
   checks pass.

### S3 lifecycle and orphan objects

Presigned PUT permits an object to exist before GeoFlow's commit endpoint accepts
it. A failed/abandoned commit can therefore leave an unreferenced S3 object.

Before adding deletion code or an S3 lifecycle rule:

1. Confirm the production bucket/prefix layout and whether any prefix is shared with
   non-GeoFlow data.
2. Define the orphan eligibility rule. Do not infer deletion eligibility only from
   object age when a valid database reference may exist.
3. Decide a grace period long enough for interrupted uploads/retries.
4. Prefer a dry-run reconciliation report before any delete operation.
5. Validate soft-deleted attachment retention requirements separately from never-
   committed orphan objects.
6. Apply lifecycle/deletion first in a non-production bucket and verify recovery and
   audit expectations.

No S3 list/head/delete/lifecycle mutation is authorized by this document.

### Scheduled lifecycle jobs

The repository contains lifecycle/retention primitives, but production scheduling is
an operations decision.

1. Validate signup expiry and one-year rejected/expired retention behavior against a
   migrated non-production central DB.
2. Confirm the desired scheduler/service mechanism and service account.
3. Run dry-run/reporting modes where available before execute modes.
4. Add alerting for failures rather than silently skipping lifecycle work.
5. Document the final cadence and operator ownership.

## 3. Transitional legacy surface

The legacy set-password URL remains temporarily available for compatibility. Its
mail generator is disabled and token use is hardened, but raw URL tokens can still
appear in reverse-proxy/access logs if an existing token link is used. Before the
legacy flow is removed:

- confirm no active operational invitation/reset process depends on it;
- allow outstanding tokens to expire or explicitly invalidate them under an
  approved database procedure;
- remove both legacy URL aliases together; and
- confirm the signup verification/outbox lifecycle fully replaces the old flow.

One additional P1 code debt remains in employee detail: a read request can populate
`hr.employee_profile.central_user_id` when the field is empty. This should be split
into a read-only lookup plus an explicit `directory.edit` write path when a
patch-capable checkout is available. Do not rewrite the large employee view wholesale
solely to remove that hidden write.

## 4. Go-live stop conditions

Do not enable public signup or deploy the Phase 1 signup/security changes if any of
these conditions is true:

- `check_release_preflight --strict` fails;
- runtime Django is below the approved 5.2 LTS security patch baseline;
- migrations have not been validated against the intended schema;
- SMTP/HMAC/HTTPS runtime readiness is incomplete;
- production proxy scheme handling is unknown;
- legal document confirmation is not explicitly enabled for the finalized version;
- the outbox worker cannot be supervised;
- a critical authorization regression is found;
- historical RRN handling requires an unresolved retention/destruction decision; or
- the operator cannot roll back the application deployment independently of a DB
  migration.

## 5. Approval boundary

Repository-only code, tests, and documentation may be prepared without touching the
live environment. The following operations require an explicit, separate approval:

- any central or tenant DB query against a real environment;
- migration, DDL, or data cleanup;
- S3 list/head/delete/lifecycle operations against a real bucket;
- SMTP live delivery tests or credential configuration;
- reverse-proxy/ALB/Nginx changes;
- cron/systemd/worker/scheduler installation or start;
- EC2 pull/restart or application deployment;
- changing protected dependency pins such as `requirements.txt`; and
- enabling public signup.
