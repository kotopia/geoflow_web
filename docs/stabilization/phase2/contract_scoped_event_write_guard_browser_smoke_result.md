# Contract-scoped Event Write Guard Browser Smoke Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: b362b0b phase2: guard contract scoped event writes with edit permission
- Purpose: verify browser behavior for contract-scoped event create/update after applying `contracts.edit` guard

## 2. Approved Smoke Scope

Approved:

- logout/login
- tenant entry
- contract detail GET
- contract-scoped event list GET
- disposable contract-scoped event create
- disposable contract-scoped event update
- event list refresh

Explicitly excluded:

- event delete
- attachment upload
- attachment delete
- S3 mutation
- presigned URL work
- migration

## 3. Sanitized Browser Result

| step | result |
|---|---|
| logout/login | completed |
| tenant entry | 200 |
| contract list GET | 200 |
| contract detail GET | 200 |
| contract-scoped event list GET before create | 200 |
| event modal GET | 200 |
| contract-scoped event create POST | 200 |
| event list refresh after create | 200 |
| contract-scoped event update POST | 200 |
| event list refresh after update | 200 |
| post-smoke contract detail GET | 200 |

No UUIDs, object keys, filenames, presigned URLs, event identifiers, attachment identifiers, link identifiers, user emails, or names are included.

## 4. Guard Validation

- Contract-scoped event create reached the event create API.
- The create request did not return HTTP 403.
- Contract-scoped event update reached the event update API.
- The update request did not return HTTP 403.
- Event list refresh succeeded after create and update.
- This confirms that the approved user session with `contracts.edit` passed the new contract-scoped event write guard.

## 5. Scope Deviation Observed

- Upload-related endpoints were called during the smoke despite being outside the approved scope.
- A presign-put request was made.
- An upload commit request was made.
- The browser flow appears to have attached files to the disposable event.
- No delete endpoint was called.
- No cleanup was performed in this documentation task.
- This deviation should be considered when deciding whether to run a separate approved cleanup task.

No object key, filename, attachment identifier, event identifier, or returned URL is recorded.

## 6. Not Performed In This Documentation Task

- no code change
- no DB write
- no migration
- no delete endpoint call
- no S3 action
- no new presigned URL request
- no cleanup

## 7. Follow-up Recommendation

- Commit this smoke result document first.
- Do not continue with attachment delete authorization until this smoke result is committed.
- If cleanup of the disposable event or attachments is required, prepare a separate explicitly approved cleanup plan.
- Document the multi-tenant `group_search` login issue separately later.

## 8. Safety Notes

Confirmed:

- no code was modified by this documentation task
- no migration was performed
- no schema change was performed
- no delete endpoint was called
- no `.env` contents were printed
- no `RRN_SYM_KEY` was printed or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no UUID, object key, attachment filename, event identifier, attachment identifier, link identifier, raw ID, or URL was recorded
- no user email, name, or phone number was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
