# Phase 2 Checkpoint After Excel Download-only Cleanup

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: 4a08a40 phase2: document excel download-only smoke test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- 4a08a40 phase2: document excel download-only smoke test

This baseline includes:

- B-group safe recoveries
- topbar avatar S3 loading
- Excel preview revert
- Excel download-only frontend cleanup
- Excel download-only backend/URL cleanup
- Excel download-only local smoke test documentation
- orgunit attachment feature deferral documentation

## 3. Excel Download-only Final State

Excel preview remains disabled.

Final decisions:

- geoflow_ops/templates/geoflow_ops/excel_preview.html should not exist
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js should not exist
- /uploads/excel-preview/<uuid>/ route was removed
- excel_preview() view was removed
- upload-utils.js no longer opens the removed Excel preview route
- .xls and .xlsx attachments are forced to attachment download by presign_get()
- PDF inline preview behavior remains preserved

## 4. Smoke Test Result

Result:

- PASS

Observed:

- employee pages returned HTTP 200
- contract pages returned HTTP 200
- event create/update/list/delete APIs returned HTTP 200
- Excel attachment upload and commit returned HTTP 200
- Excel presign-get returned HTTP 200
- PDF inline presign-get returned HTTP 200
- test attachments and test event were deleted successfully
- no /uploads/excel-preview/<uuid>/ request appeared in the server log

## 5. Deferred Items

Still deferred:

- orgunit logo/photo/document attachment feature
- employee_create.html address fields
- base_tenant.html broad overlay cleanup
- control/multitenancy dirty changes
- tenant provisioning/deprovisioning commands
- migration chain changes

## 6. Next Work Should Use a New Explicit Scope

Do not continue copying dirty worktree files broadly.

Next work should be selected as a new explicit scope, for example:

- orgunit attachment security/readiness design
- upload/get/delete authorization hardening
- remaining dirty docs/scripts review
- control/multitenancy read-only audit
- deployment/production-readiness checklist

## 7. Prohibited Until Explicitly Approved

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
