# Phase 2 Checkpoint After Delete Attachment Smoke Test

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: 6047d29 phase2: document isolated delete attachment smoke test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- 6047d29 phase2: document isolated delete attachment smoke test

This baseline includes:

- `presign_get()` READ authorization
- upload commit object_key scope validation
- `presign_put()` and `commit()` CSRF restoration
- CSRF missing-token negative unit test
- direct `delete_attachment()` isolated smoke test result

## 3. Direct Delete Smoke State

Confirmed:

- disposable event attachment upload succeeded
- direct `/api/uploads/delete/<attachment_id>/` returned HTTP 200
- event list refresh returned HTTP 200
- existing PDF `presign_get()` returned HTTP 200
- existing Excel `presign_get()` returned HTTP 200

No actual identifiers, object keys, attachment filenames, or returned URLs are recorded.

## 4. Current Upload Security State

Implemented:

- commit object_key scope validation
- `presign_get()` entity existence check
- `presign_get()` READ authorization
- `presign_put()` CSRF restored
- `commit()` CSRF restored
- `delete_attachment()` entity existence check
- direct delete smoke passed

Still deferred:

- `delete_attachment()` CSRF restoration
- `delete_attachment()` authorization
- contract write/delete permission confirmation

## 5. Excel/PDF Final State

- `excel_preview.html` does not exist
- `thumbnail-utils.js` does not exist
- Excel remains download-only
- PDF inline remains available

## 6. Remaining Work

- `delete_attachment()` CSRF restoration design
- `delete_attachment()` authorization prerequisite analysis
- employee self photo GET exception decision
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review

## 7. Recommended Next Scope

Recommended:

- read-only design for `delete_attachment()` CSRF restoration

Alternative:

- delete authorization prerequisite analysis
- employee encrypted data repair plan

## 8. Prohibited Until Explicitly Approved

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

