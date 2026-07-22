# Presign GET Read Authorization Negative Unit Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: a1f8e16 phase2: test presign get read authorization denials
- Test file: geoflow_ops/test_upload_presign_get_read_authorization.py
- Working tree expected state: clean

## 2. Purpose

Validate `presign_get()` READ authorization denial behavior without using a real restricted user account.

Goals:

- verify unauthorized read cases fail closed
- verify denied requests return HTTP 403
- verify S3 presigned URL generation is not called on denied requests
- avoid DB access
- avoid S3 access
- avoid printing sensitive data

## 3. Test Scope

Tested functions:

- `_request_has_any_perm()`
- `_authorize_attachment_read()`
- `presign_get()` denial path

Production code changed in this commit:

- none

Test file added:

- geoflow_ops/test_upload_presign_get_read_authorization.py

## 4. Test Cases

Total tests:

- 9

Covered:

- `gf_perms` list grants permission
- `perms` list grants permission
- truthy permission dict grants permission
- missing permission returns False
- employee attachment requires `directory.view`
- contract attachment requires `contracts.view`
- event attachment inherits employee or contract scope read permission
- orgunit and unknown event scopes fail closed
- orgunit/project/unknown entities fail closed
- `presign_get()` denial returns HTTP 403
- denied `presign_get()` does not call `generate_presigned_get_url()`

## 5. Test Method

Used:

- `SimpleTestCase`
- `RequestFactory`
- fake request/session objects
- `SimpleNamespace` fake attachments
- mock `ProcessEvent`
- mock `Attachment`
- mock `_resolve_attachment_entity()`
- mock `_authorize_attachment_read()`
- mock `generate_presigned_get_url()`

Not used:

- real tenant DB rows
- real attachment rows
- real ProcessEvent rows
- real S3
- real presigned URL

## 6. Test Command

Command:

- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`

Observed result:

- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

Existing warning only:

- `catalog.CategoryParent.child` W342

## 7. Safety Result

Confirmed:

- no DB setup
- no DB access
- no S3 call
- no presigned URL generation
- no production code modification
- no `.env` output
- no `RRN_SYM_KEY` output
- no encrypted value output
- no decrypted personal data output
- no real employee name/email output
- no real contract name output
- no real attachment filename output

## 8. Result

PASS.

The test verifies that `presign_get()` READ authorization can deny unauthorized requests before S3 presigned URL generation.

## 9. Still Not Covered

Still not covered:

- browser test with a real restricted user
- middleware-loaded permission behavior for a real restricted user
- employee self photo GET exception
- `delete_attachment()` authorization
- contract write/delete permission mapping
- orgunit runtime attachment behavior

## 10. Recommended Next Step

Recommended next step:

- record a Phase 2 checkpoint after negative unit test

Then choose one of:

1. read-only analysis for `delete_attachment()` authorization prerequisites
2. CSRF restoration design
3. employee encrypted data repair plan

Do not implement `delete_attachment()` authorization until contract write/delete permission is confirmed.

