# Delete Attachment Isolated Smoke Test Plan

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 8ed4176 phase2: record checkpoint after upload write csrf test
- Working tree expected state: clean

## 2. Purpose

The direct `/api/uploads/delete/<attachment_id>/` smoke test has not yet been isolated.

An event delete POST was observed previously, but deleting an event is not the same as calling the direct attachment delete endpoint.

`delete_attachment()` currently remains `csrf_exempt`.

This plan is read-only. It does not execute deletion or call the direct delete endpoint.

## 3. Current Delete Endpoint State

Current code state:

- URL pattern: `/api/uploads/delete/<uuid:attachment_id>/`
- mapped view: `delete_attachment()`
- expected HTTP method: DELETE
- `csrf_exempt`: still applied
- authentication: `login_required`
- attachment lookup: current tenant DB Attachment by UUID
- deleted-state check: already deleted attachments return HTTP 410
- entity check: `_resolve_attachment_entity(alias, att)` is applied
- user permission authorization: not implemented
- delete type: soft delete
- soft-delete fields: `deleted_at`, `deleted_by`, and `is_deleted`

The endpoint does not hard-delete the Attachment row or directly delete the S3 object.

## 4. Frontend Callers

| caller | route/function | sends CSRF token? | likely entity type | notes |
|---|---|---:|---|---|
| `upload-utils.js` | `deleteAttachment()` → `/api/uploads/delete/<id>/` | Yes | generic attachment | Shared direct DELETE helper |
| `upload-utils.js` attachment actions | `.btn-delete-att` → `deleteAttachment()` | Yes | contract/event or other rendered attachment | Removes the matching DOM item after success |
| `process-events-ui.js` | event attachment remove button → `window.deleteAttachment()` | Yes | event | Reloads the event list after success |
| employee detail inline script | `.btn-delete-doc` → direct DELETE fetch | Yes | employee document | Reloads the page after successful JSON response |
| contract detail script | `initAttachmentActions()` | Yes | rendered contract/event attachment | Supplies the page CSRF token to the shared helper |

No other direct `/api/uploads/delete/` frontend fetch was found in the reviewed upload-related files.

## 5. Why Direct Smoke Test Requires Care

- Calling the endpoint changes DB state through soft delete.
- An accidental delete of an existing real attachment must be avoided.
- The endpoint is not yet protected by entity-level user delete authorization.
- CSRF restoration and delete authorization are separate concerns and should not be mixed in this smoke test.
- A disposable attachment created specifically for the test is required.
- Employee avatar deletion can also update avatar-related session state, increasing regression risk.

## 6. Recommended Safe Smoke Strategy

Design for later execution:

1. Create or identify a disposable event attachment through the normal UI upload flow.
2. Verify that the attachment appears in the event attachment list.
3. Invoke the UI delete button for that disposable attachment only.
4. Confirm `/api/uploads/delete/<attachment_id>/` returns HTTP 200.
5. Confirm the attachment disappears from the UI or refreshed event list.
6. Do not use existing production-like or historical attachments.
7. Do not print a presigned URL, full object key, personal data, attachment filename, or secrets.

The actual delete test is NOT performed in this planning task. This plan does not call the delete endpoint.

## 7. Recommended Test Object

### Employee photo attachment

Not recommended:

- changes visible employee profile state
- may affect avatar fallback and session state
- recovery requires another upload

### Contract/event document attachment

Acceptable only when newly created specifically for the test. Existing contract or historical documents must not be used.

### Event attachment created specifically for the test

Recommended:

- can be isolated under a temporary event
- appears in a dedicated event attachment list
- can be identified by the immediate upload action without exposing its metadata
- avoids modifying an employee profile photo

Conclusion: a newly uploaded disposable event attachment is the safest test object.

## 8. Smoke Test Steps For Later Execution

Status: NOT RUN in this task.

Later execution steps:

1. Start the local development server.
2. Open a normal contract detail page.
3. Create a temporary event if needed.
4. Upload a small disposable file to that event.
5. Confirm upload `presign-put` and `commit` return HTTP 200.
6. Click the direct attachment delete button for that newly uploaded file.
7. Confirm `/api/uploads/delete/<attachment_id>/` returns HTTP 200.
8. Confirm the refreshed UI or event list no longer shows the attachment.
9. Confirm unrelated PDF and Excel `presign_get()` requests still return HTTP 200.
10. Confirm `excel_preview.html` and `thumbnail-utils.js` remain absent.

Only status codes and sanitized case labels should be recorded. Do not record attachment identifiers, object keys, filenames, or returned URLs.

## 9. What Not To Test Yet

Do not include in this smoke test:

- delete authorization implementation
- delete CSRF restoration
- contract write/delete permission mapping
- orgunit attachment delete
- employee profile photo delete
- DB repair
- migration work

## 10. Pass/Fail Criteria

PASS if the later test confirms:

- disposable upload succeeds
- direct `/api/uploads/delete/<attachment_id>/` returns HTTP 200
- the target attachment disappears from the UI or list
- unrelated attachment reads still work
- no secrets or presigned URLs are printed
- no existing real attachment is deleted

FAIL if:

- the direct delete endpoint is not called
- only event delete is tested
- an existing important attachment is deleted
- delete returns a non-200 response
- the UI still shows the deleted attachment after refresh
- PDF or Excel read flow regresses

## 11. Recommended Next Step

Recommended next step after this plan is committed:

- run the direct `delete_attachment()` isolated smoke test manually using a newly created disposable event attachment

Then:

- document the result
- decide whether to restore CSRF for `delete_attachment()`
- analyze delete authorization prerequisites separately

