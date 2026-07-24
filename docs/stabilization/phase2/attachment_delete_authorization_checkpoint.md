# Attachment Delete Authorization Checkpoint

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 4ee1fca phase2: document attachment delete smoke cleanup
- Working tree expected state: clean

## 2. Completed Scope

- Upload write CSRF restoration is complete.
- Presign GET read authorization is complete.
- The `contracts.edit` permission was provisioned.
- Contract detail POST is guarded by `contracts.edit`.
- Contract-scoped event writes are guarded by `contracts.edit`.
- Attachment delete authorization is implemented using the resolved stored scope.
- Browser smoke passed for contract-scoped event attachment deletion.
- The disposable event created during the smoke was cleaned up.

## 3. Permission Matrix Now Implemented

| resolved entity/scope | required permission |
|---|---|
| employee attachment | `directory.edit` |
| employee-scoped event attachment | `directory.edit` |
| contract attachment | `contracts.edit` |
| contract-scoped event attachment | `contracts.edit` |
| orgunit/project/unknown | fail closed |

## 4. Validation Summary

- DB-free attachment delete authorization tests passed.
- Upload CSRF tests passed.
- Presign GET read authorization tests passed.
- Contract write permission tests passed.
- Event write permission tests passed.
- `manage.py check` passed with the existing W342 warning only.
- Browser smoke confirmed the valid contract-scoped event attachment delete path.
- Cleanup confirmed removal of the remaining disposable event.

## 5. Safety Notes

- No migrations were performed.
- No schema change was made.
- No raw database cleanup was performed.
- No direct S3 cleanup was performed.
- No secrets were printed.
- No UUID, object key, filename, event ID, attachment ID, link ID, or user information was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 6. Remaining Follow-up Candidates

- Multi-tenant `group_search` login issue documentation and analysis.
- Orgunit and project attachment delete policy remains deferred.
- Employee self-delete exception remains deferred.
- Attachment upload authorization changes remain out of scope.
- Direct S3 cleanup policy remains out of scope.
