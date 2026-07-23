# Phase 2 Checkpoint After Upload Write CSRF Full Restoration

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: d414a45 phase2: document delete attachment csrf restoration smoke test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- d414a45 phase2: document delete attachment csrf restoration smoke test

This baseline includes:

- Excel preview revert
- Excel download-only cleanup
- upload commit object_key scope validation
- presign_get/delete entity existence resolution
- employee RRN decryption failure guard
- presign_get READ authorization implementation
- presign_get positive smoke test
- presign_get negative unit test
- presign_put CSRF restoration
- commit CSRF restoration
- delete_attachment direct smoke test
- delete_attachment CSRF restoration
- upload write CSRF negative unit test
- delete_attachment CSRF restoration smoke test

## 3. Upload Write CSRF Final State

Implemented and tested:

- `presign_put()` no longer has `csrf_exempt`
- `commit()` no longer has `csrf_exempt`
- `delete_attachment()` no longer has `csrf_exempt`
- missing-token `presign_put()` returns HTTP 403
- missing-token `commit()` returns HTTP 403
- missing-token `delete_attachment()` returns HTTP 403
- normal browser upload flow still works
- normal browser direct attachment delete still works

Not CSRF target:

- `presign_get()` remains read-only GET and unchanged

## 4. Unit Test Summary

Upload write CSRF test:

- Test file: `geoflow_ops/test_upload_write_csrf.py`
- Found 7 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 7 tests
- OK

READ authorization regression test:

- Test file: `geoflow_ops/test_upload_presign_get_read_authorization.py`
- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

Known warning only:

- `catalog.CategoryParent.child` W342

## 5. Browser Smoke Summary

Sanitized observed flow:

- contract detail GET: HTTP 200
- event list GET: HTTP 200
- event modal GET: HTTP 200
- temporary event create POST: HTTP 200
- disposable attachment `presign-put` POST: HTTP 200
- disposable attachment `commit` POST: HTTP 200
- disposable attachment `presign_get` GET: HTTP 200
- direct disposable attachment delete DELETE: HTTP 200
- event list refresh after attachment delete: HTTP 200
- contract detail refresh: HTTP 200
- existing PDF `presign_get` GET: HTTP 200
- existing Excel `presign_get` GET: HTTP 200
- topbar avatar `presign_get` GET: HTTP 200

No UUIDs, object keys, filenames, returned URLs, or personal data are included.

## 6. Upload Authorization Current State

Implemented:

- `commit()` validates tenant/entity/purpose object_key scope
- `presign_get()` checks source entity existence
- `presign_get()` checks READ authorization before URL generation
- `delete_attachment()` checks source entity existence

Still not implemented:

- `delete_attachment()` user permission authorization
- contract write/delete permission mapping
- event delete source write inheritance
- employee self photo GET exception

## 7. Excel/PDF Final State

Expected state:

- `geoflow_ops/templates/geoflow_ops/excel_preview.html` does not exist
- `geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` does not exist
- Excel `.xls`/`.xlsx` attachments remain download-only
- PDF inline behavior remains available

## 8. Remaining Work

Still remaining:

- `delete_attachment()` user permission authorization
- contract write/delete permission confirmation
- event delete source write inheritance
- employee self photo GET exception decision
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review

## 9. Recommended Next Scope

Recommended next scope:

- delete authorization prerequisite analysis

Alternative scopes:

- employee encrypted data repair plan
- employee self photo GET exception decision

Recommended order:

1. record this checkpoint
2. analyze delete authorization prerequisites read-only
3. confirm contract write/delete permission mapping
4. only then implement delete authorization as a separate limited slice

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
