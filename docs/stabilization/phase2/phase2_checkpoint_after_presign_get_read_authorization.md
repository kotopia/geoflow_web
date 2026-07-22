# Phase 2 Checkpoint After Presign GET Read Authorization

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: ec02142 phase2: document presign get read authorization smoke test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- ec02142 phase2: document presign get read authorization smoke test

This baseline includes:

- Excel preview revert
- Excel download-only frontend and backend cleanup
- upload commit object_key scope validation
- presign_get/delete entity existence resolution
- employee encrypted data error analysis
- employee RRN decryption failure guard
- upload GET/delete permission design
- permission code grep analysis
- presign_get READ authorization implementation
- presign_get READ authorization positive smoke test documentation

## 3. Upload Authorization Current State

Implemented:

- `commit()` validates tenant/entity/purpose object_key scope
- `presign_get()` checks attachment existence
- `presign_get()` checks deleted state
- `presign_get()` checks source entity existence
- `presign_get()` checks READ authorization before presigned URL generation
- `delete_attachment()` checks attachment existence
- `delete_attachment()` checks deleted state
- `delete_attachment()` checks source entity existence

READ authorization policy:

- employee attachment GET requires `directory.view`
- contract attachment GET requires `contracts.view`
- event attachment GET inherits source entity read permission
  - employee scope requires `directory.view`
  - contract scope requires `contracts.view`
- orgunit/project/unknown GET fail closed
- `files.*` permissions are not used

## 4. Delete Authorization Current State

Not implemented yet:

- `delete_attachment()` user permission authorization
- contract attachment DELETE permission mapping
- event attachment DELETE source write inheritance
- orgunit delete permission policy

Reason:

- `contracts.edit` is not confirmed
- `contracts.delete` is not confirmed
- `files.delete` is not confirmed
- `contracts.create` must not be used as delete permission

Current decision:

- defer delete authorization until a real contract write/delete permission is confirmed

## 5. Employee RRN Guard Current State

Implemented:

- damaged `rrn_cipher` no longer causes employee detail HTTP 500
- `employees_detail()` catches pgcrypto decryption `DatabaseError`
- existing `rrn_last4` fallback display is preserved
- warning log excludes key, ciphertext, and decrypted personal data

Still separate:

- identifying damaged rows
- controlled data repair
- `rrn_cipher` / `rrn_hash` / `rrn_last4` consistency repair

## 6. Excel Final State

Excel preview remains disabled.

Expected state:

- `geoflow_ops/templates/geoflow_ops/excel_preview.html` does not exist
- `geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` does not exist
- Excel `.xls` and `.xlsx` attachments are forced to download
- PDF inline behavior is preserved

## 7. Smoke Test Summary

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

Not covered yet:

- restricted-user unauthorized attachment GET denial
- restricted user without `directory.view`
- restricted user without `contracts.view`
- employee self photo GET exception
- orgunit fail-closed runtime test
- project/unknown fail-closed runtime test

## 8. Deferred Items

Still deferred:

- restricted-user negative authorization test
- employee self photo GET exception policy
- `delete_attachment()` authorization
- contract write/delete permission confirmation
- `files.*` permission model
- orgunit attachment feature
- orgunit permission policy
- CSRF restoration for upload write endpoints
- employee encrypted data repair
- dirty control/multitenancy changes
- migration chain changes

## 9. Recommended Next Scope

Recommended next scope:

- restricted-user negative authorization test plan

Alternative next scope:

- read-only analysis for creating or identifying a restricted test user

Do not implement delete authorization until contract write/delete permission is confirmed.

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
- dirty worktree wholesale copy
- excel_preview.html recreation
- thumbnail-utils.js recreation

