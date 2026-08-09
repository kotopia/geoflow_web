# GeoFlow Phase 1 release hardening runbook

Updated: 2026-08-09  
Branch: `release/stabilized-deploy`

## Purpose

This runbook records the closed Phase 1 state after the signup/security migration and tenant database credential transition. It separates repository-safe work from production-changing work and preserves a fail-closed path for tenant database credentials.

## Closed production baseline

The guarded `Phase 1 tenant repair and secret transition v3` workflow completed successfully on run `31303140714` for commit `3c7097805cee9e3c37cf584b5581614282252f57`.

Safe aggregate post-transition evidence from that run:

- 5 tenant DB config rows were audited.
- 3 groups are active and 2 are inactive/quarantined.
- All 3 active configs use Secrets Manager references.
- Both inactive configs have empty stored DB credentials.
- Plaintext tenant DB credentials remaining in central config: 0.
- All 3 active tenant database connections passed `SELECT 1` after restart.
- `TENANT_DB_REQUIRE_SECRET_REFERENCES=1` was enforced.
- The stabilized service recovered after restart and the post-restart audit passed.

The final protected read-only runtime audit run `31306204598` also completed successfully and independently reconfirmed the closed state: 5 total configs, 3 active, 2 inactive, 3 references, 0 plaintext, 0 malformed references, 0 resolution failures, 3/3 active DB connections successful, and strict-reference mode enabled.

Do not re-run the historical transition workflows. They are one-shot mutation paths and are retained only as blocked historical entry points.

## Repository hardening

The release preflight must always execute `control.test_tenant_db_secret_ref_audit` together with the existing resolver and runtime security regression suite.

Historical transition workflows v1, v2, and v3 must remain non-mutating/blocked. The supported production verification path after Phase 1 is `.github/workflows/phase1-tenant-runtime-audit.yml`.

The default branch contains only a safe workflow-registration placeholder for the runtime audit and blocked placeholders for the retired mutation workflows. Registry commit: `ecb2674925c13c4d92a991b1327bac8561f33627`. The real read-only audit implementation remains on `release/stabilized-deploy`.

After the final Phase 1 audit, the runtime audit was returned to **manual-only** dispatch. It must not automatically run on repository pushes.

## Runtime audit procedure

The runtime audit is read-only but uses the protected `production` environment because it connects to the reviewed host and reads production configuration.

To run it from GitHub Actions:

1. Open **Actions → Phase 1 tenant runtime audit**.
2. Choose **Run workflow**.
3. Select branch **`release/stabilized-deploy`**. Do not run the registry placeholder on `main` as the production verification.
4. Start the workflow and approve the protected **`production`** environment when the operational verification is authorized.

Expected invariants:

1. Stabilized service is active and the internal HTTP health endpoint responds.
2. `TENANT_DB_REQUIRE_SECRET_REFERENCES` is enabled.
3. No active config has an empty password field.
4. No non-empty tenant credential is plaintext.
5. Every stored secret reference parses and resolves.
6. Every active tenant database accepts the resolved credential and returns `SELECT 1`.
7. Public terms and privacy endpoints return HTTP 200.

The audit logs aggregate counters only. Do not add tenant IDs, group/user IDs, DB names, users, hosts, secret IDs, ARNs, account IDs, credentials, or exception text to workflow output.

## Failure handling

If the runtime audit fails, stop before any mutation. Diagnose only the failed invariant and prepare a separate reviewed remediation. Never make the audit self-healing.

If strict reference mode causes an application-start failure in a future change, do not silently fall back to plaintext. Restore only through a separately reviewed production procedure after confirming the central DB credential-reference state and Secrets Manager availability.

## Approval boundaries

Repository-only changes, tests, documentation, and non-production CI may proceed without a production approval.

The following remain explicit production gates: central/tenant DB mutation, `.env` modification, service restart, credential rotation, Secrets Manager mutation, RDS mutation, or any workflow that can perform those actions.

The read-only runtime audit does not mutate production, but its protected `production` environment approval is intentionally retained as an operational review gate.

## Phase 1 closure

Phase 1 is closed at 100% after:

- successful production migration/deployment;
- successful tenant credential repair and Secrets Manager transition;
- strict secret-reference enforcement;
- successful repository hardening CI;
- successful final protected read-only runtime audit.

Future AWS IAM-role migration, GitHub branch protection, historical workflow archival, or product feature work belong to subsequent hardening/feature phases rather than Phase 1 closure.
