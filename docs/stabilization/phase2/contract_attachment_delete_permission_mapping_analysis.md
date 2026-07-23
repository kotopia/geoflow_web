# Contract Attachment Delete Permission Mapping Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 4c557c8 phase2: design delete attachment authorization limited slice
- Working tree expected state: clean

## 2. Purpose

The proposed delete authorization limited slice would fail closed for contract attachments and contract-scoped event attachments. Existing UI smoke testing has included successful deletion in a contract-scoped event flow, so the contract write/delete permission mapping must be confirmed before authorization is implemented.

This task is read-only. It does not modify code or call a delete endpoint.

## 3. Existing Contract Permission Usage

| permission code | found in code? | enforced by decorator/helper? | meaning in current code | safe for attachment delete? |
|---|---:|---:|---|---|
| `contracts.view` | Yes | Yes | Contract list and detail access; it also currently surrounds detail POST handling | No; it is defined and used as a read permission |
| `contracts.create` | Yes | Yes | Contract creation GET/POST | No; creation does not imply delete |
| `contracts.edit` | No confirmed production use | No | Documentation-only candidate | No; assignment and enforcement are unconfirmed |
| `contracts.delete` | No confirmed production use | No | Documentation-only candidate | No; assignment and enforcement are unconfirmed |

`contracts.view` must not be promoted into delete authority merely because the current detail view also processes POST. That coupling exposes a write-authorization gap; it does not redefine a read permission.

No inspected code establishes `contracts.create`, `contracts.edit`, or `contracts.delete` as a safe attachment deletion permission.

## 4. Existing Contract Write Flows

### Contract creation

- `contract_create()` creates contracts.
- It supports GET and POST.
- It is protected by `contracts.create`.
- This is clear creation authority only.

### Contract detail update

- `contract_detail_page()` handles both GET detail rendering and POST form save.
- The view is protected by `contracts.view`.
- There is no separate confirmed `contracts.edit` enforcement on the POST branch.
- Therefore the current update flow does not prove that `contracts.view` is intended as write authority; it shows that contract update authorization needs separate hardening.

### Additional form function

- `contract_form()` contains create/update behavior.
- No permission decorator is present on the inspected function.
- No active tenant URL mapping for this function was confirmed in the inspected URL configuration.
- It is not a reliable source for permission semantics.

### Contract deletion

- A `contract_delete()` function exists and performs hard deletion of the contract and related project records on POST.
- No permission decorator is present on that function.
- No active tenant URL mapping for this function was confirmed in the inspected URL configuration.
- It therefore does not establish a usable `contracts.delete` permission.

### Template permission conditions

- No confirmed contract edit/delete permission condition was found in the inspected contract templates.
- Contract detail event controls are wired to event APIs but do not establish contract write permission semantics.

## 5. Event Contract Scope Write Flows

### Event creation

- `create_event()` accepts a source scope, including contract scope.
- It requires login and POST.
- It does not enforce a source-entity permission such as a contract write permission.

### Event attachment linking

- Upload `commit()` creates the attachment metadata.
- For an event attachment, it resolves the event and creates the event-to-attachment link.
- Object-key scope validation and entity resolution do not substitute for user permission authorization.

### Event update and deletion

- `update_event()` requires login and POST but has no confirmed source-scope permission check.
- `delete_event()` requires login and POST but has no confirmed source-scope permission check.
- Event deletion removes event-attachment links and then deletes the event.
- Neither flow inherits a confirmed contract write/delete permission.

The event code therefore provides no grounded contract permission that can safely be reused for contract-scoped attachment deletion.

## 6. Candidate Permission For Contract Attachment Delete

### Option A: `contracts.edit`

Pros:

- Semantically closer to modifying contract-owned resources than a read or create permission.
- Could reasonably cover attachment lifecycle changes if the product permission model explicitly defines that behavior.

Cons:

- No production enforcement was confirmed.
- No assignment or role mapping was confirmed.
- The existing contract detail POST does not use it.

Conclusion:

- Candidate only; not safe to use until enforcement and assignment are explicitly established.

### Option B: `contracts.delete`

Pros:

- Semantically strongest and most conservative delete authority.
- Clear if the intended policy treats attachment deletion as a delete operation.

Cons:

- No production enforcement was confirmed.
- No assignment or role mapping was confirmed.
- It may be too restrictive if attachment lifecycle management is intended to be part of contract editing.

Conclusion:

- Candidate only; not safe to use until the permission is confirmed and assigned.

### Option C: `contracts.create`

Rejected:

- Creation authority does not imply modification or deletion authority.
- Using it would grant destructive capability based on unrelated semantics.

### Option D: fail closed

Pros:

- Prevents an unconfirmed permission from granting destructive access.
- Preserves the principle that delete requires explicit authority.

Cons:

- Blocks contract attachment and contract-scoped event attachment deletion.
- May interrupt an existing browser workflow until contract permission policy is completed.

Conclusion:

- This is the only safe current behavior based on confirmed code evidence.

## 7. Recommended Mapping

Neither `contracts.edit` nor `contracts.delete` is confirmed by current production enforcement or assignment evidence.

Recommendation:

- keep contract attachment deletion fail closed
- keep contract-scoped event attachment deletion fail closed
- do not use `contracts.view`
- do not use `contracts.create`
- defer contract delete authorization until one explicit contract write/delete permission is defined, assigned, and enforced in the contract write flow

Before choosing between `contracts.edit` and `contracts.delete`, the project should decide whether attachment deletion is part of contract editing or requires dedicated deletion authority. The selected permission should first be reflected consistently in contract update/delete UI and backend enforcement.

## 8. Later Implementation Impact

The limited-slice mapping remains:

- employee attachment: `directory.edit`
- employee-scoped event attachment: `directory.edit`
- contract attachment: fail closed until a contract permission is confirmed
- contract-scoped event attachment: fail closed until the same contract permission is confirmed
- orgunit, project, and unknown: fail closed
- no employee self exception

If a contract permission is later confirmed, both direct contract attachments and contract-scoped event attachments should use the same source-entity write policy unless an explicit product requirement distinguishes them.

## 9. Required Tests If Mapping Is Confirmed

DB/S3-free unit tests:

- contract attachment deletion is allowed with the confirmed permission
- contract attachment deletion is denied without the confirmed permission
- contract-scoped event attachment deletion is allowed with the confirmed permission
- contract-scoped event attachment deletion is denied without the confirmed permission
- `contracts.create` does not authorize deletion
- `contracts.view` does not authorize deletion
- orgunit, project, and unknown entities fail closed
- denial returns HTTP 403 before any soft-delete field change or save
- denial does not call S3
- existing upload CSRF tests still pass
- existing READ authorization tests still pass

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
