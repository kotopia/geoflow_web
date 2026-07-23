# Upload Write CSRF Negative Unit Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: f0a7afc phase2: test upload write csrf enforcement
- Working tree expected state: clean

## 2. Purpose

This test verifies that upload write endpoints restored to Django CSRF middleware are rejected before view execution when no CSRF token is present.

Target endpoints:

- `/api/uploads/presign-put/`
- `/api/uploads/commit/`

Non-target endpoints:

- `/api/uploads/delete/<uuid>/`
- `/api/uploads/presign-get/<uuid>/`

## 3. Test File

Test file:

- `geoflow_ops/test_upload_write_csrf.py`

Test class:

- `UploadWriteCsrfTests`

Test approach:

- `SimpleTestCase`
- `RequestFactory`
- `CsrfViewMiddleware`
- `django.urls.resolve`
- middleware-level `process_view()` only
- no actual view body execution

## 4. Test Cases

Implemented tests:

1. `test_presign_put_without_csrf_token_returns_403`
2. `test_commit_without_csrf_token_returns_403`
3. `test_presign_put_resolved_view_is_not_csrf_exempt`
4. `test_commit_resolved_view_is_not_csrf_exempt`
5. `test_delete_resolved_view_remains_csrf_exempt`
6. `test_presign_get_safe_method_is_not_blocked_by_csrf`

## 5. Test Result

Observed result:

- Found 6 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 6 tests
- OK

Expected CSRF rejection log was observed:

- `Forbidden (CSRF cookie not set.)`

No token value or cookie value was printed.

## 6. Existing Regression Test

The existing `presign_get()` READ authorization test was also run:

- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`

Observed result:

- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

## 7. Validation Commands

Commands run successfully:

- `python -m py_compile geoflow_ops/test_upload_write_csrf.py`
- `git diff --check`
- `python manage.py test geoflow_ops.test_upload_write_csrf -v 2`
- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`
- `python manage.py check`

Known warning only:

- `catalog.CategoryParent.child` W342

## 8. Confirmed Behavior

Confirmed:

- `presign_put()` without CSRF token returns HTTP 403
- `commit()` without CSRF token returns HTTP 403
- `presign_put()` is no longer `csrf_exempt`
- `commit()` is no longer `csrf_exempt`
- `delete_attachment()` remains `csrf_exempt`
- `presign_get()` GET is not blocked by CSRF middleware

## 9. Safety Notes

Confirmed:

- no production code was changed
- no DB setup was performed
- no tenant DB access occurred
- no S3 call occurred
- no actual upload view body was executed
- no `.env` was read or printed
- no `RRN_SYM_KEY` was read, printed, or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no migration command was run
- no DB write command was run
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created

## 10. Current CSRF State After Test

Current state:

- `presign_put()` CSRF restored and tested
- `commit()` CSRF restored and tested
- `delete_attachment()` CSRF restoration remains deferred
- `presign_get()` remains unchanged because it is read-only GET

## 11. Recommended Next Step

Recommended next step:

- record a Phase 2 checkpoint after upload write CSRF enforcement test

Then choose one of:

1. direct `delete_attachment()` isolated smoke test
2. delete authorization prerequisite analysis
3. employee encrypted data repair plan

Do not restore CSRF for `delete_attachment()` until its direct smoke test and delete policy are separately scoped.

