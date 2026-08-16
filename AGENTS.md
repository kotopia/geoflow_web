# AGENTS.md

## 1. Project Scope

This repository is the clean working tree for GeoFlow.

Active release branch:

- `release/stabilized-deploy`

Phase state:

- Phase 1: complete
- Phase 2: complete
- Phase 3: complete; see `docs/phase3-production-closeout.md`
- Phase 4: active product/architecture development; see `docs/phase4-design-draft-v0.1.md`

Historical worktrees, stale workflow runs, and old launcher branches are context only. Do not recreate or approve them merely because they still exist.

## 2. Current Objective

Phase 4 develops product functionality on top of the stabilized central/tenant runtime without weakening the security and fail-closed boundaries established in Phases 1-3.

Primary Phase 4 areas:

- contract and project workflow
- project/event/history management
- project catalog execution records and actual-vs-contract quantities
- employee qualifications, grades, career, and project participation history
- tenant-scoped external APIs for Google Sheets and later integrations
- WebGIS editing and authoritative PostGIS validation/calculation
- QGIS plugin login/project scoping with server-side authorization
- server-side structured-editing jobs
- dashboards and state/time/assignee filters

Prefer narrow, reviewable increments over a large rewrite.

## 3. Hard Safety Boundaries

Never do any of the following without separate explicit operational authorization for that exact action:

- modify production DB data or schema
- run production `migrate`, `makemigrations`, `migrate_all_tenants`, tenant provisioning, or tenant deprovisioning
- execute destructive SQL or DDL against a live DB
- enable or invoke a production-capable tenant provisioning executor
- create/drop a live tenant database or database role
- create/delete/update live Secrets Manager tenant secrets
- attach/update/delete live IAM policy/grants or broaden IAM
- perform a live S3 PUT/object mutation unless separately approved
- deploy or restart production services
- modify Nginx/systemd/EC2 production configuration
- rotate, reveal, print, or commit secrets/credentials
- expose `.env`, `DJANGO_SECRET_KEY`, AWS keys, DB passwords, SMTP passwords, tokens, or private identifiers unnecessarily
- bypass GitHub Environment, branch, or other protection rules
- force-push `release/stabilized-deploy`
- rewrite published history
- modify the separate legacy `iroomsng.kr` service unless the user explicitly reopens that scope

If a protected GitHub `production` Environment approval is required, leave the run waiting. Never treat stale Phase 2 waiting runs as valid approval targets.

## 4. Git Rules

For implementation work:

1. Re-read the exact current `release/stabilized-deploy` HEAD.
2. Create a narrow topic branch from that SHA.
3. Change only files required for the scoped task.
4. Keep commits small and auditable.
5. Open a PR to `release/stabilized-deploy`.
6. Inspect latest-head checks and fix failures on the topic branch.
7. Merge only when relevant checks are green and the diff remains in scope.
8. Re-read release HEAD after every merge before starting the next task.
9. Never force-update the release branch.

## 5. Architecture Invariants

Core stack:

- Django / GeoDjango
- PostgreSQL / PostGIS
- Leaflet/Web frontend
- AWS S3
- central control DB + tenant DB architecture

Central/tenant invariants:

- `default` is central control/auth data
- tenant operational data belongs in tenant DBs
- tenant runtime source of truth is `GroupDBConfig -> Secrets Manager -> dynamic tenant connection`
- static tenant aliases such as `cheonan_db` are not required in `settings.DATABASES`
- `current_db_alias`, `tenant_db_alias`, and explicit tenant request context must remain fail-closed
- existing tenant `GroupDBConfig` rows are protected and must never be overwritten by provisioning logic

Authorization invariants:

- server-side authorization is authoritative
- project/tenant scope must be enforced server-side even if the client filters UI
- QGIS/WebGIS clients must not be trusted to enforce access by themselves
- do not bypass authorization checks to make a test pass

## 6. Phase 3 Provisioning Boundary

Phase 3 completed the provisioning safety contract, not live production enablement.

Important reviewed rules:

- normal plans remain `execution_available=False`
- public Django runtime does not opt into `TENANT_PROVISIONING_EXECUTOR_MODE`
- execution requires a matching read-only readiness attestation
- a per-group provisioning lock is required
- readiness is revalidated read-only under the lock immediately before the first mutation
- runtime IAM access must be exact-secret scoped and read back after grant
- runtime secret resolution and tenant DB connectivity are verified before publication
- `GroupDBConfig` publication is the final mutation
- ambiguous publication is reconciled read-only before compensation
- rollback may remove only resources created by the current unpublished attempt

Do not turn these contracts into a live provisioning path as incidental Phase 4 work.

## 7. Phase 4 Product Direction

The current product decisions are maintained in `docs/phase4-design-draft-v0.1.md`.

Key working assumptions:

- `contract_id` is the primary business lineage key
- the central Level 1-4 catalog defines work types; tenant execution records hold project-specific quantities/status/results
- contract changes, suspension, restart, and extensions are events/history rather than catalog definitions
- early workflow should support management-department input with business-department visibility; internal request/approval/approval-chain automation is later scope
- work items may be parallel rather than forced into one linear sequence
- contract quantity and actual quantity are separate; completion may still be allowed with a recorded variance reason
- employee Phase 4 scope initially covers employment state, qualifications, technical grade, career, and project participation rather than full payroll/HR
- GeoFlow is the source of truth; external sheets/tools consume tenant-scoped APIs rather than directly mutating tenant DBs
- QGIS is a thin professional client; sensitive authorization/business rules remain on GeoFlow Server
- WebGIS general editing, positional editing, and structured editing are separate modes
- structured editing should use authoritative PostGIS/server computation

Open product decisions in the Phase 4 draft must be resolved before schema-heavy implementation; do not invent irreversible schema merely to avoid a product decision.

## 8. WebGIS / QGIS Rules

WebGIS may provide lightweight editing such as create/move/delete, vertex editing, snapping, split, and merge, but final geometry validity, project scope, and persistence authorization must be checked server-side/PostGIS-side.

Structured/derived geometry operations should run server-side so WebGIS and QGIS share one authoritative algorithm.

QGIS plugin guidance:

- authenticate against GeoFlow
- obtain only projects accessible to the current user
- default to one active project context at a time
- keep the plugin thin: UI, project choice, data-edit UX, and server communication
- never embed long-lived tenant-wide DB passwords, AWS keys, or authorization secrets in the plugin
- if direct PostGIS transport is later used for performance, access must still be project-scoped through a reviewed RLS/view/short-lived-role/proxy design

## 9. Database and Migration Rules

Existing tenant DBs contain real data and must be treated as production-like.

Repository-only schema design or migration-file creation is not permission to apply it to production.

Before introducing a Phase 4 schema change:

- prove the existing canonical model cannot express the requirement cleanly
- document central-vs-tenant ownership
- define migration/backfill/rollback behavior
- validate in disposable or isolated databases
- do not run the migration against production without exact separate approval

## 10. Validation Rules

For every change, run the strongest safe validation available.

At minimum where applicable:

- diff/syntax validation
- focused unit/regression tests
- tenant isolation and authorization tests for changed routes/services
- `python manage.py check` only in an isolated runtime that does not touch live infrastructure
- disposable Postgres/PostGIS rehearsal for DB-sensitive behavior
- release CI/preflight after merge where applicable

Known non-blocking Django warning:

- `ForeignKey(unique=True)` / `fields.W342` cleanup may be handled separately

Never weaken a security, tenancy, or release check just to obtain green CI.

## 11. Reporting

At useful checkpoints record:

- scope completed
- files changed
- tests/checks run and result
- PR number and merge SHA
- any protected production gate
- any exact user-only approval required

Never include secret values or raw production business records.
