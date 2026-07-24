# Disposable Event Attachment Cleanup Plan

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 0540378 phase2: document contract scoped event write guard browser smoke
- Working tree expected state: clean

## 2. Purpose

The contract-scoped event write guard browser smoke succeeded. During that smoke, upload-related endpoints were called outside the intended scope, so a disposable event and related attachments may remain in tenant data.

Cleanup should be handled as a separate, explicitly approved operation. This document is a plan only and performs no cleanup.

## 3. Cleanup Target

Sanitized target description:

- the disposable contract-scoped event created during the latest event write guard browser smoke
- any attachments linked to that disposable event during the smoke
- any event-to-attachment link rows associated with the disposable event

No UUIDs, object keys, filenames, attachment identifiers, link identifiers, event identifiers, user emails, or names are included.

## 4. Cleanup Scope Options

### Option A: Leave as-is

- no delete endpoint
- no DB mutation
- no S3 mutation
- lowest operational risk
- leaves the test event and attachments in tenant data

### Option B: UI/API cleanup of disposable event only

- use the existing event delete flow
- expect the current implementation to remove the event and event-to-attachment links
- attachment rows or physical S3 objects may remain
- lower risk than direct DB or S3 manipulation
- requires explicit approval before execution

### Option C: Full attachment cleanup

- remove the event, event links, attachment rows, and S3 objects if policy permits
- highest operational risk
- must not proceed until attachment delete authorization is implemented and approved
- not recommended in the current phase

Recommendation:

- use Option B only if cleanup is required now
- do not perform Option C in this phase

## 5. Pre-cleanup Inspection Plan

Before any cleanup, perform a separately approved read-only inspection:

- identify the disposable event using sanitized criteria from the latest smoke
- confirm that it is contract-scoped
- confirm that it is a disposable test event
- confirm the linked attachment count only
- print only counts and sanitized labels
- do not print UUIDs, object keys, filenames, URLs, raw IDs, or user identifiers

If the target cannot be identified unambiguously without exposing or guessing identifiers, stop and request direction.

## 6. Proposed Cleanup Execution Plan

Only after explicit approval:

1. logout/login to refresh the permission session
2. open the relevant contract detail page
3. confirm that the disposable event is visible
4. use the existing event delete UI/API only for that disposable event
5. confirm that the event list refresh succeeds
6. do not call the attachment delete endpoint separately
7. do not manually delete S3 objects
8. do not run migrations
9. document the sanitized result

## 7. Expected Effects

- The event record may be deleted through the existing event delete flow.
- Event-to-attachment links may be deleted if the current event delete implementation performs that operation.
- Attachment rows and S3 objects may remain unless existing code removes them.
- This is operational cleanup of a visible test event, not guaranteed full storage cleanup.

The result document should distinguish event visibility cleanup from attachment metadata and physical object cleanup.

## 8. Safety Constraints

Actual cleanup must not:

- delete a non-disposable event
- delete unrelated attachments
- call raw SQL DELETE
- manipulate S3 directly
- print UUIDs, object keys, or filenames
- change permissions or role assignments
- run migrations
- modify application code
- broaden cleanup beyond the explicitly confirmed target

## 9. Follow-up After Cleanup

After approved cleanup:

- create a cleanup result document
- commit the cleanup result document
- only then proceed to attachment delete authorization design or implementation

## 10. Out of Scope

- attachment delete authorization implementation
- S3 object deletion
- raw DB cleanup
- `contracts.delete` creation or assignment
- multi-tenant `group_search` login issue
- template or static changes
- migrations

## 11. Safety Notes

Confirmed:

- no code was modified
- no DB write was performed
- no migration was performed
- no event delete was called
- no upload or delete endpoint was called
- no S3 access was performed
- no presigned URL was generated or printed
- no `.env` contents were printed
- no `RRN_SYM_KEY` was printed or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no UUID, object key, attachment filename, event identifier, attachment identifier, link identifier, or raw ID was recorded
- no user email, name, or phone number was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
