# GeoFlow public signup launch checklist

Status: preparation only. Do not apply to a server or database without explicit approval.

## Legal document baseline

- Terms version: `2026-08-08-v2`
- Privacy version: `2026-08-08-v2`
- Operator: `geoflow-manager/GeoFlow`
- Address: `대전광역시`
- Privacy officer: `peako`
- Service/privacy email: `kotopia79@naver.com`
- Privacy phone: `042-822-8636`
- Rejected/expired signup retention: 1 year
- Approved account data: destroy without undue delay after withdrawal/account termination, except statutory retention
- Third-party provision: none at present
- Infrastructure processor: AWS, primary region `ap-northeast-2`
- Verification mail processor/service: NAVER

## Minimum-age boundary

The initial public signup is for users aged 14 or older. The terms/privacy v2 documents state that GeoFlow does not currently provide a legal-representative consent/verification flow for children under 14, so under-14 users must not submit the public signup form. Do not collect birth dates or guardian details merely to enforce this B2B eligibility boundary. If a future product requirement includes under-14 users, design the statutory representative-consent and verification flow first and issue a new legal-document version before enabling it.

## NAVER SMTP runtime configuration

Configure only in the runtime secret/environment store. Never commit credentials.

- `USE_SMTP_EMAIL=1`
- `EMAIL_HOST=smtp.naver.com`
- `EMAIL_PORT=587`
- `EMAIL_USE_TLS=true`
- `EMAIL_HOST_USER=<NAVER account>`
- `EMAIL_HOST_PASSWORD=<NAVER application password>`
- `DEFAULT_FROM_EMAIL=kotopia79@naver.com`

NAVER mail must have IMAP/SMTP use enabled. Follow the current NAVER two-step-verification/application-password requirements for external SMTP access; keep that credential only in the runtime secret/environment store.

## Existing signup runtime gates

Keep public signup closed until the final launch approval. The following must be configured only at launch time:

- `SITE_ORIGIN`
- `SIGNUP_TERMS_URL`
- `SIGNUP_PRIVACY_URL`
- `SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID`
- `SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS_JSON`
- `ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=1` only when the mail worker is ready
- `SIGNUP_EMAIL_VERIFICATION_URL` (absolute HTTPS URL; raw token is appended as a URL fragment by code)
- `SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS` (proposed: 600 seconds)
- `SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_OUTBOX_MAX_ATTEMPTS`
- `EMAIL_TIMEOUT`
- `SIGNUP_LEGAL_DOCUMENTS_CONFIRMED=1` only after final review

`SIGNUP_LEGAL_DOCUMENTS_CONFIRMED` is the final explicit legal activation gate and must remain disabled during preparation.

## Pre-launch validation

1. Ensure displayed terms/privacy versions equal versions persisted to `signup_requests`.
2. Confirm `/terms/` and `/privacy/` are public and return the finalized documents.
3. Confirm signup is unavailable while the legal confirmation gate is off.
4. Confirm required consent checkboxes cannot be bypassed server-side.
5. Confirm signup creates an inactive, unverified account.
6. Confirm email verification does not activate the account.
7. Confirm only administrator approval activates a verified account.
8. Confirm rejected and expired signup data has a tested one-year purge path before promising automatic destruction publicly.
9. Confirm account withdrawal/deletion handles signup request/event/token/outbox dependencies.
10. Run the relevant Django tests and `python manage.py check` without running migrations.

## Explicitly prohibited during preparation

- no `.env` output
- no secret/token/password output
- no database access
- no migrations
- no EC2 pull/restart
- no server deployment
- no public signup activation

## Proposed lifecycle defaults for the final approval bundle

These values are not yet applied anywhere. They are conservative operational defaults to approve or change as one bundle:

- verification token TTL: 24 hours (`86400`)
- verification resend cooldown: 10 minutes (`600`)
- unverified signup request expiry: 7 days after submission
- verified/pending-approval request expiry: 30 days after verification/update
- outbox lease: 120 seconds
- email send timeout: 30 seconds
- retry delay: 300 seconds
- maximum delivery attempts: 5
- terminal rejected/expired retention: 1 calendar year from decision/expiry

The repository already has the state-transition service for pending request expiration, but no management command/scheduler currently invokes it. Do not advertise automatic lifecycle enforcement until the expiry and purge jobs are wired and tested.

## Account withdrawal / erasure integration

The current repository HEAD still contains the legacy administrator delete path, but this proposal replaces it with the dedicated central erasure service. The proposed service handles signup outbox/token/event/request dependencies in FK-safe order, clears known legacy password-token generations, anonymizes the Django session bridge and falls back to central audit-anchor anonymization when hard deletion would break unrelated audit references. Do not run deletion tests against production-like data; validate the integration in an approved non-production database only after the signup schema state is known.


## Central account erasure design

A dedicated central-account erasure service is prepared but not wired to a public/self-service endpoint.

- It removes the account's own signup outbox, verification-token, signup-event and signup-request rows in RESTRICT-safe order.
- It removes central membership, join-request and legacy password-reset artifacts.
- If the account is referenced as an approver/audit actor for another applicant, it preserves the foreign-key anchor but irreversibly anonymizes central identifying fields instead of hard-deleting the row.
- It does not automatically delete tenant operational/business records. Those records may have a separate organizational, contractual or statutory retention basis and require a tenant-scoped lifecycle policy.
- Do not expose self-service withdrawal until the tenant-side consequences and operator procedure are separately validated.

## Reapplication behavior for initial launch

The existing signup service treats any existing central email as an existing account. Therefore, while a rejected/expired applicant record is retained, the same email cannot create another signup request. The one-year purge eventually releases that email by deleting the signup-only identity. For the initial public launch, keep this conservative behavior rather than silently creating duplicate central identities; design an explicit reapplication/reopen policy later if needed.


## Initial public signup data minimization

The public signup UI should initially collect only email, password, display name, organization and signup purpose. The nullable `contact_phone` schema field remains unused, and invitation-code intake is deferred until there is a verified purpose, validation flow and appropriate consent/notice design. This avoids collecting optional personal data before the feature has an operational need.


## Legal version governance

- Before the first public launch, replace the effective-date label with the actual public-signup effective date if a concrete date is known.
- Any material change to operator details, collection purpose/items, retention, processor, third-party/cross-border handling, or the consent notice must be reviewed together with a version bump.
- Do not edit the displayed legal text while continuing to persist the same terms/privacy version.
- Keep `SIGNUP_LEGAL_DOCUMENTS_CONFIRMED` off while legal text/version changes are under review; re-enable it only after the matching public documents are deployed and verified.

## Additional pre-launch structural gate

Before public signup is activated, and only after the signup migrations have been applied in an approved non-production/production change window, run the read-only structural audit:

```text
python manage.py check_signup_launch_schema --strict
```

This command must remain read-only. It verifies the modern central signup/join-request columns plus the named integrity constraints and indexes required by the Phase 1 signup state machine. In particular, public launch requires `join_requests.requested_email`, `join_requests.requested_role_code`, `join_requests.decided_at`, and the canonical `join_requests.decided_by` audit column; legacy `email` / `role_id` compatibility in administrator display code is not sufficient for launch readiness. It also verifies the full signup token/outbox lease columns and the Django `auth_user` bridge fields used by account erasure.

Do not run the command against an operating database until DB access has been separately approved.

## Mail processor/runtime alignment

The initial legal disclosure names NAVER as the signup verification-mail processor. The signup runtime readiness gate must therefore reject a non-NAVER SMTP host or the wrong submission port/TLS profile. Changing the mail processor later requires a coordinated legal-document review/version bump and runtime configuration/code change; do not silently switch providers under the same privacy-policy version.

## Central user-admin integration status

The prepared user-admin hardening replaces the legacy manual account-delete SQL with the dedicated central erasure service and blocks manual active membership assignment to inactive accounts. The erasure service is migration-order tolerant only in two safe states:

- all Phase 1 signup tables absent: legacy-compatible central cleanup may proceed;
- all Phase 1 signup tables present: signup dependencies are removed in FK-safe order.

If only part of the signup schema exists, erasure fails closed. This prevents an intermediate migration state from silently deleting an identity while leaving signup dependencies behind.

The user-admin detail query may read both legacy and modern join-request column generations for operator visibility, but launch readiness remains strict on the modern schema used by live approval/request flows.

## Background-job status

The repository has bounded management commands for signup verification outbox processing, stale-request expiration, and one-year terminal retention. No production scheduler has been enabled yet. Public signup must not be described as automatically enforcing lifecycle expiry/purge until the scheduler is separately reviewed, approved, installed, and observed with safe dry-run/reconciliation checks.

## Public-endpoint abuse controls

Before enabling public signup, configure an ingress/application rate limit for at least:

- `POST /signup/`
- `POST /signup/resend/`
- repeated failed verification POSTs to `/signup/verify/`

Prefer infrastructure/server-side throttling (for example the deployment's Nginx/ALB/WAF standard) so it applies before expensive password hashing/database/email work. Keep application responses generic so throttling does not introduce account/email enumeration. Start with observable conservative limits and adjust from real traffic; CAPTCHA is not required as the first control unless abuse pressure justifies it.

Do not log submitted email addresses, passwords, raw verification tokens, or HMAC key material in rate-limit/audit logs.

## Verification URL transport requirement

Production public document URLs and signup verification URLs must use HTTPS. Local `DEBUG` development may use HTTP, but the non-debug signup readiness gate must fail closed for an HTTP verification URL and the public document URL resolver must reject non-HTTPS URLs.

## Django auth-user bridge erasure

Account privacy erasure must include the standard Django `auth_user` session-bridge row because login mirrors the central email into that row. The prepared erasure path anonymizes and de-privileges the bridge instead of leaving the original email behind or blindly deleting possible Django audit anchors.

## Tenant role-request requester identity boundary

The live tenant employee role-request route must never provision the requesting administrator's central identity as a side effect of an authorization-sensitive action. The prepared safe route no longer delegates POST handling to the legacy `get_or_create_user_by_email` path. A dedicated central transaction rechecks the existing requester account, email verification/login credential, active group and requested role before it can UPSERT a pending `join_requests` row. Target employees are not auto-provisioned by this request path; account and membership approval remain separate.
## Legacy set-password compatibility boundary

The live join-approval path must not issue the legacy raw `user_tokens` set-password flow. Phase 1 public signup accounts already set a password during signup, and membership approval now requires the target active account to carry a login-compatible PBKDF2/Django-bcrypt or legacy bcrypt password hash inside the atomic approval predicate. If a legacy active account has no compatible password credential, resolve that account through a separately reviewed password-recovery/migration procedure before approving tenant membership. Do not create a membership first and then rely on the broken legacy follow-up mail path.

Account erasure and one-year signup-only retention cleanup defensively delete both known legacy token-table generations (`password_reset_tokens` and `user_tokens`) when those tables exist, so stale raw legacy tokens do not survive identity erasure.
## Separate tenant-HR privacy blocker

Central signup readiness does not make the whole product privacy-ready. The current tenant employee implementation contains an actively exposed resident-registration-number input/display path. Treat `docs/deployment/tenant_hr_personal_data_blocker.md` as a separate release blocker: keep RRN collection/processing disabled for the initial release unless a concrete lawful basis and dedicated controls are approved, and remove the demo-profile content before broad production use.


## Public endpoint origin and transport invariants

For non-debug/public operation, all signup-owned browser URLs must stay on the canonical GeoFlow HTTPS origin:

- `SITE_ORIGIN` must be a clean HTTPS origin with no path, query, fragment or userinfo;
- `SIGNUP_TERMS_URL` must be the same origin and exact `/terms/` path;
- `SIGNUP_PRIVACY_URL` must be the same origin and exact `/privacy/` path;
- `SIGNUP_EMAIL_VERIFICATION_URL` must be the same origin and exact `/signup/verify/` path;
- none of those URLs may contain userinfo, query strings or fragments in configuration.

The raw verification token is appended by application code as a URL fragment only after those checks. Do not configure an external verification host.

## Public abuse and request-size controls

Before enabling public signup, configure bounded ingress/application controls for unauthenticated endpoints. At minimum cover POST `/signup/`, POST `/signup/resend/`, and repeated failed POST `/signup/verify/` attempts. Keep public failure messages generic and do not log submitted email addresses or tokens merely for rate-limit telemetry.

Also set a conservative HTTP request-body limit at the ingress/web-server layer. The signup form contains only short text fields; multi-megabyte request bodies are not a valid signup use case. Do not rely on Django form `maxlength` alone as a transport-level abuse control.

## Explicit minimum-age confirmation

The v2 public form requires an affirmative `age_14_or_over` checkbox. GeoFlow does not collect date of birth or guardian details for this B2B boundary. The versioned v2 terms state the minimum-age rule, and the existing terms acceptance version/timestamp remains the durable record of the governing terms.

## Tenant data-processing governance remains separate

Passing the central signup launch gates does not by itself resolve customer-tenant personal-data governance. Review `tenant_data_processing_governance_blocker.md` and `tenant_hr_personal_data_blocker.md` before broad tenant HR/business personal-data onboarding. Customer contract/DPA responsibilities, tenant lifecycle/export, subprocessor inventory and the RRN blocker remain separate product/legal workstreams.
