# Delete Attachment Isolated Smoke Test Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: aa6fa25 phase2: plan isolated delete attachment smoke test
- Working tree after test: clean

## 2. Purpose

This smoke test verifies the direct `/api/uploads/delete/<attachment_id>/` endpoint using only a newly created disposable event attachment.

- This was not an event delete-only test.
- The direct attachment delete endpoint was exercised.
- Existing real attachments were not selected as the delete target.
- The disposable event attachment was created specifically for this test.

## 3. Test Scope

In scope:

- create temporary event through UI
- upload disposable event attachment through normal UI flow
- verify upload `presign-put` and `commit`
- call direct attachment delete through UI
- confirm `/api/uploads/delete/<attachment_id>/` returned HTTP 200
- confirm event list refreshed
- confirm unrelated PDF and Excel read flows still work
- clean up temporary event through UI

Out of scope:

- delete authorization implementation
- delete CSRF restoration
- contract write/delete permission mapping
- employee photo delete
- orgunit attachment delete
- DB repair
- migration work

## 4. Observed Flow

Only sanitized labels and status codes are recorded:

- contract list GET: HTTP 200
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
- temporary event delete POST: HTTP 200
- event list refresh after event cleanup: HTTP 200

No UUIDs, object keys, attachment filenames, returned URLs, or personal data are included.

## 5. Direct Delete Confirmation

Confirmed:

- direct `/api/uploads/delete/<attachment_id>/` was called
- the response status was HTTP 200
- this was separate from `/api/events/delete/<event_id>/`
- the target was the newly uploaded disposable event attachment
- after deletion, the event list refreshed successfully

## 6. Regression Checks

Confirmed:

- upload `presign-put` still works after CSRF restoration
- upload `commit` still works after CSRF restoration
- `presign_get()` for the disposable PDF worked before delete
- existing PDF inline read returned HTTP 200
- existing Excel read returned HTTP 200
- topbar avatar `presign_get()` continued to return HTTP 200
- no `excel_preview.html` file exists
- no `thumbnail-utils.js` file exists

## 7. Current Delete Endpoint State

Current state after smoke test:

- `delete_attachment()` direct smoke test passed
- `delete_attachment()` still has `csrf_exempt`
- `delete_attachment()` still lacks user permission authorization
- entity existence check remains implemented
- delete remains soft-delete

## 8. Safety Notes

Confirmed:

- no production code was changed
- no migration command was run
- no `.env` was read or printed
- no `RRN_SYM_KEY` was read, printed, or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no object key was recorded in the document
- no UUID was recorded in the document
- no existing real attachment was selected as the delete target
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created

## 9. Result

PASS.

The direct `delete_attachment()` isolated smoke test passed using a newly created disposable event attachment.

## 10. Remaining Work

Still remaining:

- `delete_attachment()` CSRF restoration
- `delete_attachment()` authorization
- contract write/delete permission confirmation
- employee self photo GET exception decision
- employee encrypted data repair plan
- orgunit attachment feature and permission policy
- dirty control/multitenancy changes
- migration chain review

## 11. Recommended Next Step

Recommended next step:

- record this result document
- then create a Phase 2 checkpoint after direct delete smoke test

After checkpoint, choose one of:

1. read-only design for `delete_attachment()` CSRF restoration
2. delete authorization prerequisite analysis
3. employee encrypted data repair plan

Do not restore CSRF or authorization for `delete_attachment()` in this documentation task.

