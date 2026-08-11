# AGENTS.md

## 1. Project Scope

This repository is the clean working tree for the GeoFlow project.

Canonical working location:

- the repository root containing this `AGENTS.md`; do not assume one machine-specific absolute path

Current phase:

- Phase 1: complete
- Phase 2: IAM / authorization hardening and completion
- active release branch: `release/stabilized-deploy`

Historical dirty/archive worktrees are context only. Do not recreate or modify them merely to match an older workstation.

## 2. Phase 2 Unattended Authorization

The user has granted standing authorization for Phase 2 development to continue without per-change approval.

Within Phase 2, Codex may autonomously:

- inspect and search the repository
- choose the next unfinished Phase 2 item from the current repository state
- make narrow code, template, test, documentation, and CI changes
- run safe local/static/isolated tests
- fix test or CI failures and retry
- create topic branches from the exact current release HEAD
- stage exact changed files only
- commit changes to topic branches
- push topic branches
- open and update pull requests
- rebase or refresh work by creating a fresh topic branch when needed; never force-update release
- merge a PR into `release/stabilized-deploy` when its latest-head required checks are green and the diff remains within Phase 2 scope
- continue immediately with the next Phase 2 item after a merge

Do not stop merely to report routine progress. Stop only at a protected operational boundary or a product decision that cannot be inferred safely.

## 3. Hard Safety Boundaries

Even during unattended work, never do any of the following without a separate explicit operational approval for that exact action:

- modify production DB data or schema
- run production `migrate`, `makemigrations`, `migrate_all_tenants`, tenant provisioning, or tenant deprovisioning
- execute destructive SQL or database DDL against a live DB
- deploy or restart production services
- modify Nginx/systemd/EC2 production configuration
- modify S3 bucket policy, IAM policy, credentials, or production objects except a separately approved bounded diagnostic
- rotate or print secrets
- expose `.env`, `DJANGO_SECRET_KEY`, `RRN_SYM_KEY`, AWS keys, DB passwords, SMTP passwords, tokens, or credentials
- bypass GitHub Environment, branch, or other protection rules
- force-push `release/stabilized-deploy`
- use `git add .` or `git add -A`
- rewrite published history
- modify the separate legacy iroomsng service unless the user explicitly reopens that scope

If a protected GitHub `production` Environment approval is required, leave that run waiting and continue all independent repository work that can proceed safely.

## 4. Git Rules

For implementation work:

1. Re-read `release/stabilized-deploy` HEAD before creating a topic branch.
2. Create a narrow topic branch from that exact SHA.
3. Stage only exact files, for example `git add path/to/file.py`; never broad staging.
4. Keep commits small and scoped to one authorization/IAM concern where practical.
5. Open a PR to `release/stabilized-deploy`.
6. Wait for latest-head checks and fix failures on the topic branch.
7. Merge only when required checks are green and no unrelated files entered the diff.
8. After merge, re-read release HEAD before starting the next task.
9. Never force-update release.

If concurrent work has advanced release, prefer a fresh topic branch or a normal non-force refresh rather than rewriting shared history.

## 5. Phase 2 Objective

Complete GeoFlow IAM and authorization hardening without unnecessary architectural expansion.

Primary completion areas:

- canonical permission taxonomy consistency
- active tenant URL/view/API authorization coverage
- direct-URL and direct-API bypass prevention
- fail-closed behavior outside explicit tenant scope
- tenant isolation and stale permission-cache safety
- contracts / partners / projects / directory / maps / files permission consistency
- role request -> approval -> effective permission flow verification
- legacy ACL compatibility only where required for active GeoFlow behavior
- project-level authorization only if existing requirements and data structures justify it; do not invent schema merely for theoretical completeness
- regression tests for each confirmed authorization gap
- release preflight / security regression coverage

Prefer fixing proven gaps over speculative redesign.

## 6. Current Architecture Notes

Core stack:

- Django / GeoDjango
- PostGIS
- Leaflet
- AWS S3
- central control DB + tenant DB architecture

Important routing concepts:

- `default` is central control/auth data
- tenant aliases such as `cheonan_db` contain operational data
- `current_db_alias`, `tenant_db_alias`, and explicit tenant request context must remain fail-closed

Important authorization concepts include:

- `control.gf_authz`
- `require_perm`
- `gf_perm_required`
- tenant roles and permissions
- `projects.view`
- `directory.view`
- `directory.edit`
- `directory.roles.assign`

Do not bypass authorization checks to make a test pass.

## 7. Database and Migration Rules

`cheonan_db` contains real data and must be treated as production-like.

Repository-only migration design or a migration file is not automatically authorized by this document. If Phase 2 truly requires a schema change, first prove why the existing schema cannot satisfy the requirement and stop at a concise migration-design boundary for user review. Do not run it against production.

Read-only production diagnostics are not implied by Phase 2 autonomy. Use repository/static/isolated validation unless a separately approved workflow exists.

## 8. Validation Rules

For every change, run the strongest safe validation available in the current environment.

At minimum where applicable:

- `git diff --check`
- focused unit/regression tests for the changed authorization path
- existing tenant route / authorization security tests
- `python manage.py check` only when the local/isolated runtime can run it without touching live infrastructure

Known acceptable Django warning:

- `catalog.CategoryParent.child W342`

Do not substitute a production connection for missing local dependencies.

For CI changes, keep them narrowly tied to Phase 2 regression/preflight coverage and never weaken a failing security check merely to obtain green status.

## 9. Decision Rules for Unattended Work

When multiple safe next tasks exist, prioritize in this order:

1. confirmed authorization bypass or cross-tenant exposure
2. missing permission enforcement on write endpoints
3. missing permission enforcement on read endpoints
4. role/permission propagation inconsistencies
5. stale-cache / scope fail-closed issues
6. regression/preflight gaps
7. documentation and cleanup necessary to close Phase 2

If a finding is ambiguous, inspect call sites, URL routing, permission seed data, tests, and historical compatibility before changing code.

Do not introduce new permission codes, roles, tables, or project-membership schema unless the existing canonical model cannot express the required rule.

## 10. Definition of Phase 2 Done

Phase 2 is complete when all of the following are true:

- active tenant-facing routes and APIs have an explicit, tested authorization policy
- known direct URL/API bypasses are closed
- tenant scope is fail-closed
- canonical permission names used by views match the seeded/recognized taxonomy
- role approval changes are reflected in effective permissions as designed
- regression tests cover confirmed gaps and are part of CI/preflight where appropriate
- latest release CI is green
- no unresolved Phase 2 security blocker remains in the repository review
- remaining items are clearly Phase 3/product enhancements rather than IAM defects

When these criteria are met, stop creating new Phase 2 changes, prepare a concise completion report, and leave any production-only deployment/activation gate waiting for the user.

## 11. Reporting

Routine unattended work should not block on progress reporting.

At useful checkpoints record:

- issue/gap fixed
- files changed
- tests/checks run and result
- PR number and merge SHA
- any waiting protected production gate

Never include secret values or raw production business records.
