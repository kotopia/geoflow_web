# Phase 2 Checkpoint After Upload Write CSRF Enforcement Test

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: ed463f2 phase2: document upload write csrf negative test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- ed463f2 phase2: document upload write csrf negative test

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
- CSRF limited slice smoke test
- CSRF missing-token negative unit test
- CSRF negative test documentation

## 3. Upload Write CSRF Current State

Implemented and tested:

- `presign_put()` no longer has `csrf_exempt`
- `commit()` no longer has `csrf_exempt`
- missing-token `presign_put()` returns HTTP 403
- missing-token `commit()` returns HTTP 403
- normal-token browser upload flow still works

Still deferred:

- `delete_attachment()` still has `csrf_exempt`
- direct `delete_attachment()` isolated smoke test
- `delete_attachment()` CSRF restoration

Not changed:

- `presign_get()`
- upload JavaScript
- templates
- settings.py
- migrations
- PDF inline behavior
- Excel download-only behavior

## 4. Upload Authorization Current State

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
- employee self photo GET exception

## 5. Test Summary

CSRF enforcement test:

- Test file: `geoflow_ops/test_upload_write_csrf.py`
- Found 6 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 6 tests
- OK

READ authorization regression test:

- Test file: `geoflow_ops/test_upload_presign_get_read_authorization.py`
- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

Known warning only:

- `catalog.CategoryParent.child` W342

## 6. Confirmed Behavior

Confirmed:

- no DB setup
- no tenant DB access
- no S3 call
- no actual upload view body execution in CSRF unit test
- no production code changed by the negative test
- no `.env` output
- no `RRN_SYM_KEY` output or change
- no ciphertext output
- no decrypted personal data output
- no presigned URL output

## 7. Browser Smoke State

Previously confirmed after CSRF restoration:

- employee photo presign-put returned HTTP 200
- employee photo commit returned HTTP 200
- employee photo_thumb presign-put returned HTTP 200
- employee photo_thumb commit returned HTTP 200
- event attachment presign-put returned HTTP 200
- event attachment commit returned HTTP 200
- event PDF inline presign_get returned HTTP 200
- event Excel presign_get returned HTTP 200
- damaged-RRN employee detail returned HTTP 200
- normal contract detail returned HTTP 200

## 8. Excel/PDF Final State

Expected state:

- `geoflow_ops/templates/geoflow_ops/excel_preview.html` does not exist
- `geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` does not exist
- Excel `.xls`/`.xlsx` attachments remain download-only
- PDF inline behavior remains available

## 9. Still Deferred

Still deferred:

- direct `delete_attachment()` isolated smoke test
- `delete_attachment()` CSRF restoration
- `delete_attachment()` authorization
- contract write/delete permission confirmation
- employee self photo GET exception decision
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review

## 10. Recommended Next Scope

Recommended next scope:

- direct `delete_attachment()` isolated smoke test

Alternative scopes:

- delete authorization prerequisite analysis
- employee encrypted data repair plan

Recommended order:

1. record this checkpoint
2. run direct `delete_attachment()` isolated smoke test without changing code
3. document delete smoke result
4. then decide whether to restore CSRF for `delete_attachment()` or analyze delete authorization first

## 11. Prohibited Until Explicitly Approved

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

