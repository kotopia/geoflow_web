# Phase 2 Checkpoint After B/D Groups

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: c752ac2 phase2: document excel preview revert decision
- Working tree expected state: clean

## 2. Completed B Group Work

Implemented and committed:

- Employee list empty-state improvement
- Partner label improvement
- Employee role request current-role selection
- Project scope catalog permission hardening
- Codex AGENTS.md rules
- Topbar avatar loading from S3 presigned URL
- Topbar avatar local smoke test documentation

## 3. B Group Deferred Items

Deferred:

- base_tenant.html global overlay cleanup
- employee_create.html address fields
- orgunit logo/photo/document attachment feature
- views_projects.py low-value cleanup

Reasons:

- broad common-template risk
- DB/save-logic uncertainty
- feature scope too large
- low practical value

## 4. Completed D Group Decision

D group was reviewed as S3/upload/preview helper candidates.

Final decisions:

- thumbnail-utils.js: rejected
- excel_preview.html: disabled / reverted
- UPLOAD_REFACTORING_SUMMARY.md: reference only

## 5. Excel Preview Decision

Excel preview remains disabled.

Reason:

- Browser-rendered Excel preview cannot reliably match native Excel layout and behavior.
- The project decision is to keep Excel attachments download-only.
- Commit 58e5c05 added the Excel preview template.
- Commit aa2c76f reverted that template.
- Commit c752ac2 documented the revert decision.

Current expected file state:

- geoflow_ops/templates/geoflow_ops/excel_preview.html should not exist.

## 6. Current Safe Baseline

The current safe baseline is:

- c752ac2 phase2: document excel preview revert decision

This baseline includes B-group safe recoveries and excludes Excel preview.

## 7. Next Work Should Use a New Explicit Scope

Do not continue copying dirty worktree files broadly.

The next task should start from a new explicitly approved scope, such as:

- remaining dirty file read-only inventory
- orgunit attachment feature as a separate Phase 2C analysis
- control/multitenancy review as read-only only
- upload/download UX cleanup without Excel preview
- deployment/production-readiness checklist

## 8. Prohibited Until Explicitly Approved

Do not run or perform:

- git push
- migrate
- makemigrations
- migrate_all_tenants
- tenant_provision
- DB schema changes
- .env output
- dirty worktree wholesale copy
- excel_preview.html recreation
- thumbnail-utils.js recreation
