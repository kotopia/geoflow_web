# AGENTS.md

## 1. Project Scope

This repository is the clean working tree for the GeoFlow project.

Primary working path:

- C:\GeoFlow\geoflow_web_commitA_clean

Current phase:

- Phase 2
- Active branch: phase2-clean-base

Important related paths:

- Original dirty archive worktree: C:\GeoFlow\geoflow_web
- Phase 1 archive: C:\GeoFlow\_phase1_archive
- DB backups: C:\GeoFlow\backups

Do not modify the original dirty worktree unless the user explicitly asks for it.

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
- modifying C:\GeoFlow\geoflow_web
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

Before any commit, report:

- git status --short
- git diff --cached --name-only
- git diff --cached summary

Do not create commits unless the user explicitly asks.

Do not push.

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

RRN_SYM_KEY is actively used for resident-registration-number encryption/decryption and must not be rotated.

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

## 8. Current Phase 2 Workflow

The current Phase 2 task is selective recovery from the original dirty worktree.

Process:

1. Compare clean files and dirty files.
2. Save review diffs to C:\GeoFlow\_phase1_archive only when requested.
3. Analyze risk.
4. Select minimal safe hunks.
5. Reconstruct changes manually in the clean branch.
6. Validate.
7. Let the user decide whether to commit.

Never copy a dirty file wholesale.

Prefer small commits with narrow scope.

## 9. Validation Rules

For Python/Django changes, run when approved:

- git diff --check
- python manage.py check

Known acceptable warning:

- catalog.CategoryParent.child W342

If a new error appears, stop and report it.

For JavaScript/template-only changes, at minimum run:

- git diff --check
- git status --short

When a Django check requires environment variables, load .env silently without printing values.

## 10. Reporting Format

After each task, report:

- files changed
- commands run
- validation results
- git status --short
- whether any forbidden action was avoided
- whether any DB or migration operation was performed

Use concise Korean explanations for the user.

## 11. Current Forbidden Areas Unless Explicitly Approved

Do not modify these unless specifically included in the task scope:

- control/
- geoflow_project/settings.py
- geoflow_project/asgi.py
- geoflow_project/wsgi.py
- manage.py
- requirements.txt
- migrations
- .env
- C:\GeoFlow\geoflow_web

## 12. Current Deferred Items

These items are deferred and must not be implemented unless explicitly approved:

- employee_create.html address fields
- orgunit logo/photo/document attachment feature
- base_tenant.html global overlay cleanup
- topbar avatar S3 presigned URL feature
- tenant provisioning/deprovisioning
- migration chain changes
- DB schema changes
