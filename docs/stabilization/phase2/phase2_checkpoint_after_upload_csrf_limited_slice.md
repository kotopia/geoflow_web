# Phase 2 Checkpoint After Upload CSRF Limited Slice

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: 8797b29 phase2: document upload csrf restoration smoke test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- 8797b29 phase2: document upload csrf restoration smoke test

This baseline includes:

- Excel preview revert
- Excel download-only cleanup
- upload commit object_key scope validation
- presign_get/delete entity existence resolution
- employee RRN decryption failure guard
- presign_get READ authorization implementation
- presign_get positive smoke test
- presign_get negative unit test
- upload write CSRF restoration design
- CSRF restoration for presign_put()
- CSRF restoration for commit()
- CSRF limited slice smoke test documentation

## 3. Upload Authorization Current State

Implemented:

- `commit()` validates tenant/entity/purpose object_key scope
- `presign_get()` checks source entity existence
- `presign_get()` checks READ authorization before URL generation
- `delete_attachment()` checks source entity existence

Not implemented yet:

- `delete_attachment()` user permission authorization
- contract write/delete permission mapping
- event delete source write inheritance
- orgunit permission policy

## 4. CSRF Current State

Implemented:

- `presign_put()` no longer has `csrf_exempt`
- `commit()` no longer has `csrf_exempt`

Still deferred:

- `delete_attachment()` still has `csrf_exempt`
- `delete_attachment()` CSRF restoration
- missing-token runtime/browser 403 test
- DB/S3-free CSRF negative unit test

Not changed:

- `presign_get()`
- upload JavaScript
- templates
- settings.py
- migrations
- PDF inline behavior
- Excel download-only behavior

## 5. Smoke Test Summary

Positive smoke test passed for:

- employee detail GET
- employee edit detail GET
- employee photo presign-put
- employee photo commit
- employee photo_thumb presign-put
- employee photo_thumb commit
- event create
- event attachment presign-put
- event attachment commit
- event attachment link creation
- event PDF inline presign_get
- event Excel presign_get
- damaged-RRN employee detail
- normal contract detail

Known warning only:

- `catalog.CategoryParent.child` W342

## 6. Test Summary

presign_get READ authorization negative unit test:

- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

Confirmed:

- no DB setup
- no DB access
- no S3 call
- denied `presign_get()` does not call `generate_presigned_get_url()`

## 7. Excel/PDF Final State

Expected state:

- `geoflow_ops/templates/geoflow_ops/excel_preview.html` does not exist
- `geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` does not exist
- Excel `.xls`/`.xlsx` attachments remain download-only
- PDF inline behavior remains available

## 8. Still Deferred

Still deferred:

- missing-token CSRF negative unit test for presign_put and commit
- direct `delete_attachment()` isolated smoke test
- `delete_attachment()` CSRF restoration
- `delete_attachment()` authorization
- contract write/delete permission confirmation
- employee self photo GET exception decision
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review

## 9. Recommended Next Scope

Recommended next scope:

- DB/S3-free CSRF negative unit test for missing-token presign_put and commit

Alternative next scopes:

- direct `delete_attachment()` isolated smoke test
- delete authorization prerequisite analysis
- employee encrypted data repair plan

Recommended order:

1. record this checkpoint
2. add CSRF negative unit test for missing token
3. document CSRF negative unit test result
4. then decide whether to test direct `delete_attachment()` or analyze delete authorization prerequisites

## 10. Prohibited Until Explicitly Approved

Do not run or perform:

- git push
- migrate
- makemigrations
- migrate_all_tenants
- tenant_provision
- DB schema changes
- DB UPDATE/INSERT/DELETE
- .env output
- RRN_SYM_KEY output or rotation
- encrypted value output
- decrypted personal data output
- presigned URL output
- dirty worktree wholesale copy
- excel_preview.html recreation
- thumbnail-utils.js recreation

