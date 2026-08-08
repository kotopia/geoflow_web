# GeoFlow public signup launch checklist

Status: **repository preparation/hardening only. Public signup remains closed.**

This checklist distinguishes code-complete work from operational actions that still require a separately approved database/server/runtime change window.

## 1. Legal document baseline

Current repository baseline:

- Terms version: `2026-08-08-v2`
- Privacy version: `2026-08-08-v2`
- Operator: `geoflow-manager/GeoFlow`
- Address: `대전광역시`
- Privacy officer: `peako`
- Service/privacy email: `kotopia79@naver.com`
- Privacy phone: `042-822-8636`
- Rejected/expired signup retention: 1 year
- Third-party provision: none at present
- Infrastructure processor: AWS, primary region `ap-northeast-2`
- Verification-mail processor/service: NAVER

The initial public signup is for users aged 14 or older. The v2 form requires an affirmative `age_14_or_over` confirmation. GeoFlow does not collect date of birth or guardian details merely to enforce this B2B eligibility boundary.

Any material change to operator details, collected items/purposes, retention, processor, third-party/cross-border handling or consent wording requires coordinated legal review and a legal-document version bump. Do not change displayed legal text while persisting the old version.

## 2. Code-complete signup safety controls

The repository now contains code for the following controls:

- displayed terms/privacy versions and stored signup consent versions use the same version policy;
- public signup collects only the approved initial fields; optional contact phone and invitation code are not exposed;
- signup creates an inactive, unverified central account;
- email verification advances verification state but does not activate the account;
- administrator approval is a separate activation/membership boundary;
- resend responses are generic and do not reveal account existence;
- signup readiness fails closed when legal/runtime prerequisites are incomplete;
- public legal/verification URLs are constrained to the canonical same-origin path/transport rules;
- signup schema has a read-only structural audit command;
- stale-request expiry, one-year terminal retention cleanup and verification-outbox processing have bounded management commands/services;
- central account erasure has an FK-aware dedicated service and fails closed for a partially installed signup schema;
- tenant role requests no longer auto-provision the requesting central identity;
- live approval does not rely on the legacy raw `user_tokens` set-password path.

These code paths have been statically validated in the preparation environment. Full Django/database integration validation still requires an approved environment with the intended schema state.

## 3. Final legal activation gate

Keep this disabled throughout preparation:

- `SIGNUP_LEGAL_DOCUMENTS_CONFIRMED=0`

Set it to `1` only in the final approved launch window, after the matching legal documents are deployed and verified. Repository hardening alone must not open public signup.

## 4. NAVER SMTP runtime configuration

Configure only in the runtime secret/environment store. Never commit credentials.

Required runtime shape:

- `USE_SMTP_EMAIL=1`
- `EMAIL_HOST=smtp.naver.com`
- `EMAIL_PORT=587`
- `EMAIL_USE_TLS=true`
- `EMAIL_HOST_USER=<NAVER account>`
- `EMAIL_HOST_PASSWORD=<NAVER application password>`
- `DEFAULT_FROM_EMAIL=kotopia79@naver.com`

NAVER mail must have the applicable external SMTP access enabled. Credentials remain runtime secrets and must never appear in source, logs, screenshots or review output.

## 5. Signup runtime values to set only in the launch window

- `SITE_ORIGIN`
- `SIGNUP_TERMS_URL`
- `SIGNUP_PRIVACY_URL`
- `SIGNUP_EMAIL_VERIFICATION_ACTIVE_KEY_ID`
- `SIGNUP_EMAIL_VERIFICATION_HMAC_KEYS_JSON`
- `ENABLE_SIGNUP_EMAIL_VERIFICATION_OUTBOX=1` only when the mail worker is ready
- `SIGNUP_EMAIL_VERIFICATION_URL`
- `SIGNUP_EMAIL_VERIFICATION_TTL_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_OUTBOX_LEASE_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_OUTBOX_RETRY_SECONDS`
- `SIGNUP_EMAIL_VERIFICATION_OUTBOX_MAX_ATTEMPTS`
- `EMAIL_TIMEOUT`
- `SIGNUP_LEGAL_DOCUMENTS_CONFIRMED=1` only at final activation

Recommended initial lifecycle values remain:

- verification token TTL: 24 hours (`86400`)
- resend cooldown: 10 minutes (`600`)
- unverified request expiry: 7 days
- verified/pending-approval expiry: 30 days
- outbox lease: 120 seconds
- email timeout: 30 seconds
- retry delay: 300 seconds
- maximum delivery attempts: 5
- rejected/expired retention: 1 calendar year from terminal decision/expiry

Do not claim automatic expiry/purge operation merely because commands exist. A production scheduler has not been approved, installed or observed yet.

## 6. Public URL/transport invariants

For non-debug public operation:

- `SITE_ORIGIN` must be a clean HTTPS origin with no path, query, fragment or userinfo;
- `SIGNUP_TERMS_URL` must be the same origin and exact `/terms/` path;
- `SIGNUP_PRIVACY_URL` must be the same origin and exact `/privacy/` path;
- `SIGNUP_EMAIL_VERIFICATION_URL` must be the same origin and exact `/signup/verify/` path;
- configuration URLs must not contain userinfo, query strings or fragments.

The raw verification token is appended by application code as a URL fragment after those checks. Do not configure an external verification host.

## 7. Database/schema validation boundary

Only after migrations are approved and applied in the intended environment, run the read-only structural audit:

```text
python manage.py check_signup_launch_schema --strict
```

The command must remain read-only. It verifies the modern signup/join-request schema and integrity objects required by the Phase 1 state machine, including the modern join-request audit fields and the Django `auth_user` bridge used by account erasure.

Do **not** run this command against an operating database until database access is separately approved.

## 8. Pre-launch functional validation

In an approved non-production environment, without introducing unreviewed migrations during the test itself:

1. Run `python manage.py check`.
2. Run the relevant Django test suite.
3. Confirm `/terms/` and `/privacy/` are public and show the exact approved versions.
4. Confirm signup remains unavailable with the legal confirmation gate off.
5. Confirm required consent and minimum-age confirmation cannot be bypassed server-side.
6. Confirm signup creates an inactive/unverified account.
7. Confirm verification does not activate it.
8. Confirm only an approved administrator flow activates/assigns membership.
9. Confirm resend and failed-verification responses do not enumerate email/account existence.
10. Exercise expiry, purge and account-erasure flows against disposable test records and verify their audit/FK behavior.
11. Exercise the verification-outbox worker using a non-production NAVER configuration without exposing raw tokens or credentials.
12. Confirm partially installed signup schema states fail closed.

## 9. Public-endpoint abuse controls

Before activation, configure ingress/application throttling for at least:

- `POST /signup/`
- `POST /signup/resend/`
- repeated failed verification POSTs to `/signup/verify/`

Also configure a conservative HTTP request-body limit for public signup endpoints. The signup form contains only short text fields; large request bodies are not a valid use case.

Do not log submitted passwords, raw verification tokens, HMAC key material or unnecessary email values in rate-limit/audit logs.

## 10. Tenant event/attachment security status

Tenant event and attachment APIs have been hardened in code:

- event writes are CSRF-protected;
- event and attachment access is derived from current tenant membership and scope permissions;
- event/attachment JSON renderers avoid injecting user/API values through HTML parsing sinks;
- direct upload combinations are fail-closed to the currently used employee/event purposes;
- upload commit verifies the S3 object's actual size, MIME and expected server-side-encryption metadata before creating attachment metadata;
- direct upload declarations are bounded by default application limits: employee photo 15 MiB, thumbnail 2 MiB, employee PDF 25 MiB, event document 100 MiB;
- download disposition values and filenames are constrained before presign generation.

Residual storage risk: the current presigned PUT design cannot cryptographically enforce `content-length-range` before the object reaches S3. A malicious client could upload an oversized orphan object and then fail commit verification. Strong pre-upload size enforcement requires a presigned-POST/content-length-range or equivalent upload/ingress redesign. Storage orphan cleanup/lifecycle must therefore be reviewed separately before broad attachment use.

Soft-deleting attachment metadata also does not by itself prove physical S3 object deletion. Define the storage deletion/retention lifecycle separately.

## 11. Tenant HR RRN status

The initial-release employee application now has the RRN path disabled:

- no RRN input/display in the employee UI;
- non-empty direct `rrn_plain` POST is rejected;
- normal employee detail does not select/decrypt RRN values;
- legacy RRN encryption/hash/decryption code was removed from the active employee view;
- hard-coded demo address/license/social content was removed.

No tenant database was inspected or modified. Historical `hr.employee_profile` RRN-related columns/values may therefore still exist. Inventory, retention and deletion of historical values remain a separately approved database/governance task. See `tenant_hr_personal_data_blocker.md`.

## 12. Tenant data-processing governance remains separate

Passing central signup gates does not make GeoFlow fully privacy-ready for unrestricted customer HR/business personal-data processing.

Before broad tenant onboarding, complete the work in `tenant_data_processing_governance_blocker.md`, including:

- customer/GeoFlow controller-processor responsibility model;
- customer contract/DPA terms;
- subprocessor inventory based on actual runtime flows;
- support/operator access controls and logging;
- tenant export, correction, deletion and contract-termination procedures;
- attachment/photo storage lifecycle;
- historical high-risk identifier treatment.

Central account erasure must not silently delete customer tenant records without a defined tenant data-lifecycle procedure.

## 13. Reapplication behavior

The initial signup service conservatively treats any existing central email as an existing account. A rejected/expired applicant therefore cannot create a new central identity with the same email while that retained signup-only identity remains.

Keep this behavior for the initial launch rather than silently creating duplicates. Design an explicit reapplication/reopen policy later if required.

## 14. Explicitly prohibited during preparation

Until a separate operational approval is given:

- no `.env` or secret output;
- no password/token/key output;
- no database access;
- no migrations or DDL;
- no S3 runtime inspection/mutation;
- no EC2 pull/restart;
- no server deployment;
- no SMTP production send test;
- no scheduler installation;
- no public signup activation.

## 15. Final launch sequence

A final approved launch should be treated as an ordered change window, not a collection of independent toggles:

1. approve the final legal text/version and effective date;
2. approve and apply the intended database migrations;
3. run the strict read-only schema audit;
4. run application checks/tests in the approved environment;
5. configure runtime secrets/URLs/mail without exposing them;
6. configure public abuse/request-size controls;
7. validate worker/scheduler behavior and reconciliation on non-production records;
8. deploy the reviewed code;
9. verify public legal pages and the closed signup gate;
10. enable the mail/outbox/runtime prerequisites;
11. enable the final legal confirmation gate only after all preceding checks pass;
12. observe signup/verification/approval behavior and rollback if invariants fail.
