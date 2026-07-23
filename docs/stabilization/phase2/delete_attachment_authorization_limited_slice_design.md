# Delete Attachment Authorization Limited Slice Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: de13479 phase2: analyze delete attachment authorization prerequisites
- Working tree expected state: clean

## 2. Purpose

CSRF restoration is complete for the upload write endpoints. `delete_attachment()` still lacks user permission authorization.

The prerequisite analysis recommended a limited slice grounded in permissions that are already enforced elsewhere. This document designs that slice without changing code.

## 3. Current Security State

`delete_attachment()` currently:

- requires an authenticated user
- requires the DELETE method
- is protected by Django CSRF middleware
- resolves the tenant database alias
- verifies that the attachment exists
- returns HTTP 410 when the attachment is already deleted
- verifies that the source entity exists
- performs a soft delete

Missing:

- user permission authorization before the soft delete

## 4. Recommended Authorization Scope

Recommended initial implementation:

- employee attachment delete: require `directory.edit`
- employee-scoped event attachment delete: require `directory.edit`
- contract attachment delete: fail closed
- contract-scoped event attachment delete: fail closed
- orgunit attachment delete: fail closed
- project attachment delete: fail closed
- unknown entity or unknown event scope: fail closed
- no employee self exception
- do not use `contracts.create`
- do not invent `contracts.edit` or `contracts.delete`

This limited slice intentionally blocks contract and contract-scoped event attachment deletion until the contract write/delete permission mapping is confirmed.

If that temporary fail-closed behavior would be operationally unacceptable, implementation should be deferred instead of broadening permissions.

## 5. Proposed Helper

Design only:

`_authorize_attachment_delete(request, alias, attachment) -> bool`

Expected behavior:

- reuse `_request_has_any_perm(request, *codes)`
- employee:
  - return `_request_has_any_perm(request, "directory.edit")`
- event:
  - load `ProcessEvent` by `attachment.entity_id`
  - if the event is missing, return `False`
  - if `scope_type == "employee"`, require `directory.edit`
  - if `scope_type == "contract"`, return `False` for now
  - otherwise return `False`
- contract:
  - return `False` for now
- orgunit:
  - return `False` for now
- project:
  - return `False` for now
- unknown:
  - return `False`

Placement inside `delete_attachment()`:

1. attachment lookup
2. already-deleted check
3. `_resolve_attachment_entity(alias, att)`
4. `_authorize_attachment_delete(request, alias, att)`
5. soft-delete field changes
6. `att.save()`

Denied response:

- return `_json_error("Forbidden", status=403)`

Authorization must run before any soft-delete field is changed and before `att.save()`.

## 6. Exact Production Code Change Plan

Expected file:

- `geoflow_ops/views_uploads.py`

Expected changes:

- add `_authorize_attachment_delete()`
- call it inside `delete_attachment()` after source entity resolution

Do not change:

- `_resolve_attachment_entity()`
- `_authorize_attachment_read()`
- `presign_get()`
- `presign_put()`
- `commit()`
- CSRF decorators
- delete implementation after authorization succeeds
- PDF inline behavior
- Excel download-only behavior
- JavaScript
- templates
- settings
- migrations

## 7. Unit Test Plan

Preferred new test file:

- `geoflow_ops/test_upload_delete_authorization.py`

DB/S3-free unit tests should use fake attachments and mock all ORM and save behavior.

Required tests:

1. employee delete is allowed with `directory.edit`
2. employee delete is denied without `directory.edit`
3. employee-scoped event delete is allowed with `directory.edit`
4. employee-scoped event delete is denied without `directory.edit`
5. contract attachment delete fails closed
6. contract-scoped event attachment delete fails closed
7. orgunit attachment delete fails closed
8. project attachment delete fails closed
9. unknown entity type fails closed
10. delete denial returns HTTP 403 before soft-delete save
11. denied delete does not call S3
12. existing CSRF tests still pass
13. existing READ authorization tests still pass

Test constraints:

- do not access a tenant database
- do not access S3
- do not generate presigned URLs
- do not execute an actual delete request
- do not print attachment identifiers, object keys, filenames, or URLs

## 8. Browser Smoke Plan After Later Implementation

Use only if implementation is approved later.

Allowed smoke scenarios:

- an allowed user with `directory.edit` deletes a disposable employee attachment or employee-scoped event attachment
- a restricted user receives HTTP 403 when attempting the same operation, if a suitable restricted account already exists

Do not use a contract-scoped event as a positive smoke case because contract scope is intentionally fail closed in this slice.

Regression checks:

- upload presign-put: HTTP 200
- upload commit: HTTP 200
- PDF presign_get: HTTP 200
- Excel presign_get: HTTP 200
- topbar avatar presign_get: HTTP 200
- `excel_preview.html` remains absent
- `thumbnail-utils.js` remains absent

## 9. Implementation Risk

- The design is intentionally conservative.
- It may block existing contract attachment and contract-scoped event attachment deletion until contract permission mapping is confirmed.
- That is safer than using `contracts.create` or unconfirmed `contracts.edit` or `contracts.delete`.
- If continuity of contract deletion is required, stop and perform contract permission mapping analysis first.
- No employee self exception should be added without validating the login identity-to-employee mapping and attachment-purpose restrictions.

## 10. Recommendation

Implement this limited slice only if temporary fail-closed behavior for contract and contract-scoped event deletion is acceptable.

Otherwise, defer implementation and first analyze and confirm the contract write/delete permission mapping.

Required boundaries:

- do not implement broad delete authorization now
- do not use `contracts.create`
- do not implement an employee self exception
- keep orgunit, project, and unknown types fail closed

## 11. Safety Notes

Confirmed:

- no code was modified
- no delete endpoint was called
- no DB write was performed
- no S3 access was performed
- no `.env` was read or printed
- no `RRN_SYM_KEY` was read, printed, or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no UUID, object key, or attachment filename was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
