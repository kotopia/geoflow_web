# Attachment Delete Authorization Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 77dab87 phase2: revise attachment delete authorization design
- Implementation commit: a3d0dbc phase2: authorize attachment deletes by resolved scope
- Working tree expected state: clean

## 2. Purpose

This implementation adds attachment delete authorization based on the resolved stored scope while preserving the existing CSRF protection for the delete endpoint and leaving presign GET read authorization unchanged.

Authorization does not use request payload or URL context as its source. Unsupported scopes fail closed before they can mutate the tenant database or interact with S3.

This document only records the implementation result.

## 3. Modified Files

- geoflow_ops/views_uploads.py
- geoflow_ops/test_attachment_delete_authorization.py

## 4. Implementation Summary

- Added `_authorize_attachment_delete()`.
- Employee attachments require `directory.edit`.
- Employee-scoped event attachments require `directory.edit`.
- Contract attachments require `contracts.edit`.
- Contract-scoped event attachments require `contracts.edit`.
- Orgunit, project, unknown, unresolved, or inconsistent scopes fail closed.
- Event attachments are authorized from the stored `ProcessEvent.scope_type`.
- `contracts.view`, `contracts.create`, and `contracts.delete` are not used.
- Role names are not checked directly.
- No staff bypass was added.
- The existing successful delete mutation path remains unchanged after authorization passes.

## 5. Mutation Ordering

- The attachment is loaded first.
- Existing not-found and already-deleted behavior remains unchanged.
- The stored entity and scope are resolved before authorization.
- Authorization runs before soft-delete, save, link-delete, or S3-related behavior.
- Denied requests return HTTP 403.
- Denied requests do not mutate the tenant database.
- Denied requests do not call S3.

## 6. Test Result

| test command | result |
|---|---|
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | 12 tests OK |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | 7 tests OK |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | 9 tests OK |
| `python manage.py test geoflow_ops.test_contract_write_permission` | 6 tests OK |
| `python manage.py test geoflow_ops.test_event_write_permission` | 9 tests OK |
| `python manage.py check` | passed with existing W342 warning only |

The existing `catalog.CategoryParent.child` W342 warning was the only warning. It is unrelated to this implementation.

## 7. Not Performed

- No migration was performed.
- No database schema change was made.
- No real tenant database write was performed.
- No browser smoke was performed.
- No real attachment delete endpoint was called.
- No event, upload, or presign endpoint was called.
- No S3 access was performed.
- No presigned URL was generated.
- No template or static file was changed.
- No permission provisioning was performed.

## 8. Follow-up Recommendation

- Commit this implementation result document first.
- The next step should be an explicitly approved browser smoke.
- Limit that browser smoke to deletion of a disposable contract-scoped event attachment through the existing UI/API.
- Do not perform raw database cleanup.
- Do not perform direct S3 cleanup.
- Do not upload an attachment unless separately approved.
- If disposable data is created, document and clean it through a separate approved scope.

## 9. Safety Notes

- No code was modified by this documentation task.
- No database write was performed by this documentation task.
- No migration was performed.
- No endpoint was called.
- No S3 access was performed.
- No presigned URL was generated or printed.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext was printed.
- No decrypted personal data was printed.
- No UUID, object key, attachment filename, event ID, attachment ID, link ID, raw ID, or URL was recorded.
- No user email, name, or phone number was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
