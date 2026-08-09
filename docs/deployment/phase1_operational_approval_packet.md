# GeoFlow Phase 1 Operational Approval Packet

Status date: 2026-08-09
Branch: `release/stabilized-deploy`

This document groups the remaining operational actions that cannot be completed by repository-only work. It is designed so the owner can approve the actions in one batch while preserving explicit boundaries around production data and credentials.

## Already completed without production mutation

- Django upgraded to the reviewed 5.2 LTS patch level.
- Release preflight and focused security regression tests pass in GitHub Actions.
- Central signup migrations and tenant migrations were successfully rehearsed on disposable PostGIS databases.
- The strict signup schema audit passed on the disposable central database.
- Tenant DB secret-reference runtime support and a read-only audit command are implemented.
- Public read-only smoke confirms HTTP-to-HTTPS redirect and a live HTTPS service.
- Public smoke currently detects `/terms/` and `/privacy/` as 404 and HSTS as absent.
- EC2 application-only deployment, systemd, Nginx, HSTS staging, and rollback templates are prepared.

## Approval A — application-only server release

Approve all of the following as one application release action on the reviewed target server:

1. Confirm the currently deployed commit and record it for rollback.
2. Fetch/checkout the exact reviewed `release/stabilized-deploy` commit.
3. Install the pinned `requirements.txt` into the existing/new isolated virtual environment.
4. Run `pip check`, `manage.py check`, focused security tests, and strict repository release preflight.
5. Run `collectstatic --noinput`.
6. Validate systemd/Gunicorn and Nginx configuration before reload.
7. Restart/reload the application service and Nginx.
8. Run public smoke checks after deployment.

This approval does **not** include database migration, schema mutation, S3 deletion, credential rotation, signup activation, or tenant provisioning.

## Approval B — database read-only audits

Approve read-only inspection of the specifically selected central database for:

- `check_signup_launch_schema --strict`
- `check_tenant_db_secret_refs --strict`
- migration state inspection / `migrate --plan` only
- historical tenant RRN presence/count inventory only if the target and purpose are explicitly selected

No secret values or personal-data values may be printed. Counts/status only.

## Approval C — central signup migration

Approve central database migration only after backup/restore readiness is confirmed and the read-only schema audit identifies the expected pre-migration state.

Scope:

- only the reviewed `control` signup migrations required by the release
- no tenant-wide migration sweep
- no unrelated DDL
- post-migration strict schema audit required

A rollback decision must be based on backup/restore and migration semantics, not application-code rollback alone.

## Approval D — tenant DB credential cutover

Approve the controlled migration of tenant database credentials from plaintext-at-rest values to secret references.

Scope:

1. Inventory rows by state without printing credential values.
2. Create/update approved secret entries in the selected secret manager.
3. Replace each stored plaintext credential with its secret reference.
4. Validate tenant connection for each converted tenant.
5. After all rows are converted, enable `TENANT_DB_REQUIRE_SECRET_REFERENCES=1`.
6. Rotate old credentials only after the application is confirmed to resolve the new references correctly.

This is a credential/secret-management operation and must not be inferred from ordinary code-deployment approval.

## Approval E — SMTP, S3, worker, and retention runtime validation

Approve narrowly scoped runtime tests:

- send a controlled signup verification email to an approved test recipient
- verify S3 upload/head/get behavior using a test object/prefix only
- verify worker/outbox supervision and one controlled delivery cycle
- verify retention/expiration commands in dry-run/read-only mode first

Do not enable destructive attachment cleanup or broad retention deletion until retention, legal-hold, tenant offboarding, versioning, and backup policy are approved.

## Approval F — HSTS and public signup activation

Only after A–E are successful:

1. Enable a short HSTS max-age at the trusted TLS edge/proxy.
2. Confirm no redirect/proxy loop and that HTTPS remains healthy.
3. Confirm `/terms/` and `/privacy/` return successful public responses.
4. Confirm SMTP delivery, signup schema, abuse/rate-limit controls, worker supervision, and legal contact/governance requirements.
5. Enable public signup.
6. Monitor signup, email delivery, authentication, and tenant-routing errors after activation.

HSTS max-age should be increased gradually after the TLS topology and rollback behavior are proven.

## Single-batch approval wording

If the owner intends to authorize all operational phases above, an unambiguous approval is:

> Approve Phase 1 operational actions A through F in order, with each later action conditional on the preceding validation passing. Do not print secrets or personal-data values. Do not broaden database, S3, tenant, or server scope beyond the selected GeoFlow release targets. Stop before any action whose prerequisite fails.

Even with this approval, execution still requires an actual connected server/AWS/DB/SMTP access channel. Approval does not create credentials or connectivity.
