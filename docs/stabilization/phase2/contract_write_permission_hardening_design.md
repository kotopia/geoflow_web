# Contract Write Permission Hardening Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 1444c5e phase2: analyze contract attachment delete permission mapping
- Working tree expected state: clean

## 2. Purpose

Contract attachment delete authorization cannot be completed safely until contract write and delete permission semantics are confirmed.

The current contract detail POST path appears to run under `contracts.view`, while event create, update, and delete operations do not inherit source contract write permission. This document designs a safe hardening path that should precede attachment delete authorization.

## 3. Current Contract Permission Gap

- `contracts.view` protects contract list and detail read access.
- `contracts.create` protects contract creation.
- `contracts.edit` has no confirmed production enforcement.
- `contracts.delete` has no confirmed production enforcement.
- Contract detail POST/update is handled within a view protected by `contracts.view`, creating a write-authorization gap.
- A contract delete function exists, but an active route and permission enforcement were not confirmed.
- Contract-scoped event create, update, and delete APIs do not enforce source contract write permission.

The current behavior must not be interpreted as proof that a read or create permission is valid write authority.

## 4. Recommended Contract Permission Semantics

Recommended semantics:

- `contracts.view`: contract list and detail read only
- `contracts.create`: creation of a new contract only
- `contracts.edit`: updating contract fields and managing contract-owned lifecycle resources
- `contracts.delete`: deleting the contract record itself, if contract deletion is supported

Recommended default:

- use `contracts.edit` for contract attachment lifecycle operations
- use `contracts.edit` for contract-scoped event lifecycle operations
- reserve `contracts.delete` for deleting the contract record itself
- never use `contracts.create` for update, delete, or attachment deletion
- never use `contracts.view` for write operations

This is a proposed policy. It must be confirmed against actual central permission rows and role assignments before implementation.

## 5. Proposed Hardening Order

Recommended staged order:

1. document and approve the contract permission semantics
2. confirm that `contracts.edit` exists and is assigned to the intended roles
3. protect contract detail POST/update with `contracts.edit`
4. protect contract-scoped event create, update, and delete with `contracts.edit`
5. allow contract attachment and contract-scoped event attachment deletion with `contracts.edit`
6. keep the employee self exception deferred
7. keep orgunit, project, and unknown entity types fail closed

Each stage should be independently tested before the next stage begins.

## 6. Proposed Implementation Slices

Design only; no implementation is part of this task.

### Slice A: contract detail POST guard

- Keep contract detail GET protected by `contracts.view`.
- Require `contracts.edit` for POST update.
- Return HTTP 403 for a denied POST.
- Do not change models or schemas.
- Do not treat `contracts.view` or `contracts.create` as update authority.

A method-aware check inside the current combined view, or a split GET/update view, can enforce this boundary. The smallest safe change should preserve existing GET behavior while checking write permission before form processing or persistence.

### Slice B: contract-scoped event write guard

- Require `contracts.edit` for event create when the source scope is contract.
- Require `contracts.edit` for update and delete after resolving the event's source scope.
- Keep employee-scoped event write mapping separate.
- Fail closed for unknown or unsupported source scopes.
- Perform authorization before any event or link mutation.

### Slice C: attachment delete authorization

Only after Slices A and B:

- employee attachment: require `directory.edit`
- employee-scoped event attachment: require `directory.edit`
- contract attachment: require `contracts.edit`
- contract-scoped event attachment: require `contracts.edit`
- orgunit, project, and unknown: fail closed
- no employee self exception

Authorization must run before any soft-delete field is changed or saved.

## 7. Risk Analysis

- Moving contract detail POST from `contracts.view` to `contracts.edit` may reveal missing role assignments.
- Users who currently edit through a read permission may temporarily lose write access until role assignments are corrected.
- Contract-scoped event workflows may return HTTP 403 if intended users lack `contracts.edit`.
- These restrictions are desirable for security, but require controlled positive and negative smoke testing.
- No tenant schema migration should be required if the permission row and role assignments already exist.
- If the permission row does not exist, central permission provisioning and role assignment become a separate, explicitly approved task.
- Permission provisioning must not be combined silently with application-code hardening.

## 8. Required Tests Later

DB/S3-free unit tests:

- contract detail POST is denied without `contracts.edit`
- contract detail POST is allowed with `contracts.edit`
- contract detail GET is allowed with `contracts.view`
- `contracts.create` does not authorize contract update
- `contracts.view` does not authorize contract update
- contract-scoped event creation is denied without `contracts.edit`
- contract-scoped event creation is allowed with `contracts.edit`
- contract-scoped event update is denied without `contracts.edit`
- contract-scoped event deletion is denied without `contracts.edit`
- contract attachment deletion is denied without `contracts.edit`
- contract attachment deletion is allowed with `contracts.edit`
- denied attachment deletion occurs before soft-delete save
- upload CSRF tests still pass
- presign_get READ authorization tests still pass
- no S3 call occurs in authorization unit tests

Browser smoke tests after implementation:

- a user with `contracts.edit` can update a contract
- a user with `contracts.edit` can create and delete a contract-scoped event
- a user with `contracts.edit` can delete a disposable contract-scoped event attachment
- a user without `contracts.edit` receives HTTP 403 for write and delete paths, if a suitable restricted account exists
- PDF presign_get remains HTTP 200
- Excel presign_get remains HTTP 200
- `excel_preview.html` remains absent
- `thumbnail-utils.js` remains absent

## 9. Recommended Next Step

Do not implement attachment delete authorization yet.

First decide whether `contracts.edit` is the official write authority for contract attachments and contract-scoped events.

If approved:

- start the next implementation with the contract detail POST guard
- validate role assignments and positive/negative behavior
- then harden contract-scoped event writes
- only afterward extend attachment delete authorization

If role assignment is uncertain:

- perform a read-only inspection of central permission and role assignment metadata
- do not expose secrets or personal data
- do not perform DB writes

## 10. Safety Notes

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
