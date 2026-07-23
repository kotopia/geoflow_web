# Delete Attachment CSRF Restoration Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: 1cb0771 phase2: restore csrf checks for attachment delete
- Working tree after implementation commit: clean

## 2. Implementation Under Test

Changed:

- removed `@csrf_exempt` from `delete_attachment()`
- removed unused `csrf_exempt` import
- updated upload write CSRF unit test for delete endpoint

Not changed:

- delete logic
- delete authorization
- entity resolution logic
- `presign_put()`
- `commit()`
- `presign_get()`
- upload JavaScript
- templates
- settings.py
- migrations
- PDF inline behavior
- Excel download-only behavior

## 3. Unit Test Result

Observed successful validation:

- `python -m py_compile geoflow_ops/views_uploads.py geoflow_ops/test_upload_write_csrf.py`
- `git diff --check`
- `python manage.py test geoflow_ops.test_upload_write_csrf -v 2`
- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`
- `python manage.py check`

Upload write CSRF test result:

- Found 7 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 7 tests
- OK

READ authorization regression test result:

- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

Known warning only:

- `catalog.CategoryParent.child` W342

## 4. Confirmed CSRF Behavior

Confirmed by unit test:

- `presign_put()` without CSRF token returns HTTP 403
- `commit()` without CSRF token returns HTTP 403
- `delete_attachment()` without CSRF token returns HTTP 403
- `presign_put()` is not `csrf_exempt`
- `commit()` is not `csrf_exempt`
- `delete_attachment()` is not `csrf_exempt`
- `presign_get()` GET is not blocked by CSRF middleware

## 5. Browser Smoke Test Result

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

## 6. Regression Checks

Confirmed:

- upload `presign-put` still works
- upload `commit` still works
- direct attachment delete still works after CSRF restoration
- existing PDF inline read still works
- existing Excel read still works
- topbar avatar read still works
- `presign_get()` READ authorization tests still pass
- no `excel_preview.html` file exists
- no `thumbnail-utils.js` file exists

## 7. Current Upload CSRF State

Current state:

- `presign_put()` CSRF restored
- `commit()` CSRF restored
- `delete_attachment()` CSRF restored
- `presign_get()` remains read-only GET and unchanged

## 8. Current Remaining Security Work

Still remaining:

- `delete_attachment()` user permission authorization
- contract write/delete permission confirmation
- event delete source write inheritance
- employee self photo GET exception decision
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review

## 9. Safety Notes

Confirmed:

- no production code was changed in this documentation task
- no additional delete endpoint was called in this documentation task
- no additional DB write was performed in this documentation task
- no S3 access was performed in this documentation task
- no `.env` was read or printed
- no `RRN_SYM_KEY` was read, printed, or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no object key was recorded
- no UUID was recorded
- no attachment filename was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created

## 10. Result

PASS.

The `delete_attachment()` CSRF restoration limited slice passed unit tests and browser smoke testing.

## 11. Recommended Next Step

Recommended next step:

- record this result document
- then create a Phase 2 checkpoint after upload write CSRF full restoration

After checkpoint, choose one of:

1. delete authorization prerequisite analysis
2. employee encrypted data repair plan
3. employee self photo GET exception decision

Do not implement delete authorization in this documentation task.
