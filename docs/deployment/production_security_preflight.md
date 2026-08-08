# GeoFlow production security preflight

Status date: 2026-08-08

This checklist separates repository-level safeguards that are already implemented
from changes that require a real deployment environment, database, S3 bucket,
mail provider, reverse proxy, or scheduler. Do not treat this document as approval
to perform any live operation.

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

### Central administration

- Central category endpoints require a central administrator and GET-only reads.
- `/api/catalog/admin/*` routes require a central administrator.
- Catalog delete routes are POST-only at the URL boundary.
- Catalog facet-option reads require authentication.
- Stock Django `/admin/` is registered only when `DEBUG=True`; production
  administration is expected to use guarded GeoFlow control views.
- `/after-login/` requires an authenticated Django session before tenant routing.

### Tenant authorization and attachments

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
2. Review pending signup migrations and the exact migration plan.
3. Apply migrations first outside production and run Django/system tests against the
   migrated schema.
4. Verify central users, signup requests/events, verification-token/outbox tables,
   join-request compatibility, and FK behavior.
5. Inventory historical tenant RRN columns/values and decide lawful retention or
   destruction before any deletion.
6. Validate central account erasure against real FK relationships before enabling
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

## 4. Go-live stop conditions

Do not enable public signup or deploy the Phase 1 signup/security changes if any of
these conditions is true:

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
- EC2 pull/restart or application deployment; and
- enabling public signup.
