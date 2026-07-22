# Upload Write CSRF Restoration Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: 48ca773 phase2: restore csrf checks for upload put and commit
- Runtime: local Django development server
- Tenant alias observed: cheonan_db

## 2. Implementation Under Test

Changed:

- removed `@csrf_exempt` from `presign_put()`
- removed `@csrf_exempt` from `commit()`

Not changed:

- `delete_attachment()` remains `csrf_exempt`
- `presign_get()` unchanged
- upload JavaScript unchanged
- templates unchanged
- settings unchanged
- migrations unchanged
- PDF inline behavior unchanged
- Excel download-only behavior unchanged
- `presign_get()` READ authorization unchanged

## 3. Validation Commands

Observed successful validation:

- `git diff --check`
- `python -m py_compile geoflow_ops/views_uploads.py`
- `python manage.py check`
- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`

Known warning only:

- `catalog.CategoryParent.child` W342

READ authorization test result:

- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

## 4. Employee Photo Upload Smoke Test

Observed successful flow:

- employee detail GET returned HTTP 200
- employee edit detail GET returned HTTP 200
- photo `presign-put` returned HTTP 200
- photo `commit` returned HTTP 200
- photo_thumb `presign-put` returned HTTP 200
- photo_thumb `commit` returned HTTP 200
- employee detail POST returned HTTP 302
- employee detail after redirect returned HTTP 200

Result:

- PASS

Note:

- the topbar avatar is the logged-in user's avatar
- it is separate from the selected employee profile photo
- changing the selected employee photo should not be expected to change the topbar avatar

## 5. Event Attachment Upload Smoke Test

Observed successful flow:

- contract detail GET returned HTTP 200
- event modal GET returned HTTP 200
- event create POST returned HTTP 200
- event attachment `presign-put` returned HTTP 200
- event attachment `commit` returned HTTP 200
- event attachment link was created
- event list GET returned HTTP 200
- event update POST returned HTTP 200

Result:

- PASS

## 6. Attachment Read Regression Check

Observed successful read flows:

- employee photo_thumb `presign_get` returned HTTP 200
- event image `presign_get` returned HTTP 200
- event PDF inline `presign_get` returned HTTP 200
- event Excel `presign_get` returned HTTP 200

Result:

- PASS

## 7. Employee RRN Guard Regression Check

Observed damaged-RRN employee detail pages still returned HTTP 200.

The safe warning log included only:

- employee ID
- error type

No key, ciphertext, or decrypted personal data was logged.

Result:

- PASS

## 8. Delete Flow Scope

This slice did not change `delete_attachment()`.

Observed:

- event delete POST returned HTTP 200

Not fully covered:

- direct `/api/uploads/delete/<attachment_id>/` smoke test was not clearly isolated in this run

Result:

- delete endpoint CSRF restoration remains deferred

## 9. Excel/PDF Final State

Expected state confirmed:

- `geoflow_ops/templates/geoflow_ops/excel_preview.html` does not exist
- `geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` does not exist
- Excel attachments remain download-only
- PDF inline behavior remains available

## 10. Result

PASS.

The limited CSRF restoration slice did not break employee photo upload, event attachment upload, `presign_get()` read flows, Excel download-only, PDF inline, or damaged-RRN employee detail rendering.

## 11. Still Not Covered

Still not covered:

- missing-token `presign-put` browser/runtime 403 test
- missing-token `commit` browser/runtime 403 test
- direct `delete_attachment()` CSRF restoration
- direct `delete_attachment()` isolated smoke test
- delete authorization
- contract write/delete permission mapping

## 12. Recommended Next Step

Recommended next step:

- record a Phase 2 checkpoint after CSRF limited slice

Then choose one of:

1. DB/S3-free CSRF negative unit test for missing token
2. direct delete attachment smoke test
3. delete authorization prerequisite analysis
4. employee encrypted data repair plan

Do not restore CSRF for `delete_attachment()` until direct delete smoke and policy are separately scoped.

