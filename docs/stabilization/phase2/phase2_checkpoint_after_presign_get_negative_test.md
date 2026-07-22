# Phase 2 Checkpoint After Presign GET Negative Test

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: dd4b00d phase2: document presign get read authorization negative test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- dd4b00d phase2: document presign get read authorization negative test

This baseline includes:

- Excel preview revert
- Excel download-only cleanup
- upload commit object_key scope validation
- presign_get/delete entity existence resolution
- employee RRN decryption failure guard
- upload GET/delete permission design
- permission code grep analysis
- presign_get READ authorization implementation
- presign_get positive smoke test documentation
- restricted-user negative authorization test plan
- DB/S3-free negative unit test
- negative unit test result documentation

## 3. Presign GET READ Authorization State

Implemented:

- `_request_has_any_perm()`
- `_authorize_attachment_read()`
- `presign_get()` READ authorization check after source entity resolution
- fail closed behavior before presigned URL generation

Policy:

- employee attachment GET requires `directory.view`
- contract attachment GET requires `contracts.view`
- event attachment GET inherits source entity read permission
- orgunit/project/unknown GET fail closed
- `files.*` permissions are not used

## 4. Positive Smoke Test State

Positive regression smoke test passed for:

- employee detail
- employee edit detail
- employee list
- contract list
- contract detail
- event list
- event modal
- employee photo_thumb `presign_get`
- event PDF inline `presign_get`
- event HWP `presign_get`
- event XLSX `presign_get`
- event attachment upload
- event attachment commit
- event attachment delete

## 5. Negative Unit Test State

Test file:

- geoflow_ops/test_upload_presign_get_read_authorization.py

Test command:

- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`

Observed result:

- Found 9 test(s)
- Skipping setup of unused database(s): cheonan_db, default
- Ran 9 tests
- OK

Verified:

- unauthorized helper paths return False
- endpoint denial returns HTTP 403
- `generate_presigned_get_url()` is not called for denied requests
- no DB setup
- no DB access
- no S3 call
- no presigned URL output

## 6. Upload Authorization Current State

Implemented:

- `commit()` object_key tenant/entity/purpose validation
- `presign_get()` entity existence check
- `presign_get()` READ authorization
- `delete_attachment()` entity existence check

Not implemented:

- `delete_attachment()` permission authorization
- contract write/delete permission mapping
- event delete source write inheritance
- orgunit permission policy
- CSRF restoration

## 7. Delete Authorization Decision

`delete_attachment()` authorization remains deferred.

Reason:

- `contracts.edit` is not confirmed
- `contracts.delete` is not confirmed
- `files.delete` is not confirmed
- `contracts.create` must not be used as delete permission

Do not implement delete authorization until contract write/delete permission is confirmed.

## 8. Excel Final State

Expected state:

- `geoflow_ops/templates/geoflow_ops/excel_preview.html` does not exist
- `geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` does not exist
- Excel `.xls` and `.xlsx` attachments remain download-only
- PDF inline behavior is preserved

## 9. Remaining Work

Still remaining:

- real restricted-user browser/integration test, if a known restricted account exists
- employee self photo GET exception decision
- `delete_attachment()` authorization
- contract write/delete permission confirmation
- CSRF restoration
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review remains deferred

## 10. Recommended Next Scope

Recommended next scope:

- CSRF restoration design for upload write endpoints

Alternative scopes:

- read-only analysis for `delete_attachment()` authorization prerequisites
- employee encrypted data repair plan

Recommended order:

1. record this checkpoint
2. design CSRF restoration for upload write endpoints
3. later revisit `delete_attachment()` authorization after write/delete permission is confirmed

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

