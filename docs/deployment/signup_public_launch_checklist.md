# GeoFlow public signup launch checklist

Status: preparation only. Do not apply to a server or database without explicit approval.

## Legal document baseline

- Terms version: `2026-08-08-v1`
- Privacy version: `2026-08-08-v1`
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

## Account withdrawal gap

The current central administrator delete path predates the signup FK chain. After signup migrations are eventually applied, a user that owns a `signup_requests` row cannot be safely hard-deleted until dependent signup outbox/token/event rows are handled in the correct order. Before public launch, either harden that deletion path or document an operator procedure that invokes a dedicated erasure service. Do not run deletion tests against production-like data.


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
