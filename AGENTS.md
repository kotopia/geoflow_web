# AGENTS.md

## 1. Project Scope

This repository is the clean working tree for the GeoFlow project.

Canonical working location:

- the repository root containing this `AGENTS.md`; do not assume one machine-specific absolute path

Historical prior-workstation paths (context only, not canonical):

- C:\GeoFlow\geoflow_web_commitA_clean
- C:\GeoFlow\geoflow_web
- C:\GeoFlow\_phase1_archive
- C:\GeoFlow\backups

A new workstation may use a different local clone path. Do not recreate historical dirty/archive paths merely to match an older PC.

Current phase:

- Phase 1 release stabilization
- Focus: signup, identity, tenant authorization, privacy, and production-readiness hardening
- Active branch: release/stabilized-deploy

Do not modify a historical/original dirty worktree unless the user explicitly asks for it.

## 2. Role of Codex

Codex is used as an implementation and analysis agent.

Codex may:

- inspect files
- compare clean and dirty worktrees
- generate diff review files in the archive when explicitly requested
- make minimal code changes only within the exact files approved by the user
- run safe validation commands when approved
- report changed files, diffs, and validation results

Codex must not make broad refactors or infer permission to edit files outside the approved scope.

## 3. Hard Prohibitions

Never do any of the following unless the user explicitly approves that exact action in the current task:

- git push
- git add .
- git add -A
- git commit
- git merge
- git cherry-pick
- git apply
- git reset
- git restore
- git clean
- migrate
- makemigrations
- migrate_all_tenants
- tenant_provision
- tenant_deprovision
- database DDL
- schema changes
- destructive file operations
- modifying a historical/original dirty worktree
- copying dirty files wholesale into the clean branch
- printing .env
- printing secrets
- rotating secrets
- changing RRN_SYM_KEY
- changing geoflow_ops.apps label
- changing webgisapp legacy migration identity

## 4. Git Rules

Use exact file staging only when the user explicitly asks for staging.

Allowed staging pattern:

- git add path/to/exact_file.py
- git add path/to/exact_file.html

Forbidden staging pattern:

- git add .
- git add -A

Before any local git commit, report:

- git status --short
- git diff --cached --name-only
- git diff --cached summary

Do not create commits unless the user explicitly asks.

Do not push unless the user explicitly approves the current publish action. When the
GitHub connector is used instead of a local checkout, preserve the same narrow-scope,
non-force, fast-forward-only intent.

## 5. Database and Migration Rules

cheonan_db contains real data.

Treat cheonan_db as production-like and high risk.

Do not run:

- migrate
- makemigrations
- migrate_all_tenants
- SQL DDL
- tenant provisioning commands
- tenant deprovisioning commands

Reading metadata is allowed only when explicitly requested.

Migration files must not be changed unless the user explicitly approves a migration task.

## 6. Secrets and Environment Rules

Never print or expose:

- .env
- DJANGO_SECRET_KEY
- RRN_SYM_KEY
- AWS keys
- DB passwords
- SMTP passwords
- any credential value

It is allowed to check whether .env exists.

It is allowed to load .env into the current process for validation, but values must not be printed.

Legacy RRN key material must not be rotated or exposed. Phase 1 application code no
longer collects, encrypts, decrypts, or displays RRN values; any historical tenant DB
values require a separately approved inventory/retention decision.

## 7. GeoFlow Architecture Notes

Core stack:

- Django
- GeoDjango
- PostGIS
- Leaflet
- AWS S3
- Multi-tenant central DB + tenant DB architecture

Important database routing concepts:

- central/default DB for login, users, groups, roles, and join requests
- tenant DB such as cheonan_db for operational data
- current_db_alias and tenant_db_alias must be treated carefully

Important permission concepts:

- control.gf_authz
- require_perm
- gf_perm_required
- tenant roles and permissions
- projects.view
- directory.view
- directory.edit
- directory.roles.assign

Do not bypass authorization checks.

## 8. Current Release-Stabilization Workflow

The current task is narrow release stabilization on `release/stabilized-deploy`.

Process:

1. Re-read the current remote branch HEAD before preparing changes.
2. Inspect the smallest relevant code surface and identify fail-closed behavior.
3. Prefer minimal repository-only fixes and regression tests over broad refactors.
4. Validate syntax/static contracts without connecting to live DB/S3/SMTP/server infrastructure unless the user explicitly approves that operational boundary.
5. Before a remote ref update, re-read HEAD and require an exact fast-forward parent.
6. Never force-update the branch.
7. Keep migrations, live-data operations, deployment, and activation behind their own explicit approval boundary.
8. Report what changed, what remains unvalidated, and the exact next operational boundary.

Do not copy a dirty file wholesale.

Prefer small commits with narrow scope.

## 9. Validation Rules

For Python/Django changes, run when approved and when the required runtime is available:

- git diff --check
- python manage.py check

Known acceptable warning:

- catalog.CategoryParent.child W342

If a new error appears, stop and report it.

For JavaScript/template-only changes, at minimum run:

- git diff --check
- git status --short

When a Django check requires environment variables, load .env silently without printing values.

If the current execution environment does not contain Django/GDAL/PostgreSQL runtime
dependencies, use syntax/static contract validation and state that full Django checks
were not executed; do not substitute a live production connection for missing local dependencies.

## 10. Reporting Format

After each task, report:

- files changed
- commands or connector checks run
- validation results
- branch HEAD / changed-file scope when remote writes were used
- whether any forbidden action was avoided
- whether any DB, migration, S3, SMTP, server, or deployment operation was performed

Use concise Korean explanations for the user.
