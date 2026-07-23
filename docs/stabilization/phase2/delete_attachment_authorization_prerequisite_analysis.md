# Delete Attachment Authorization Prerequisite Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 644959d phase2: record checkpoint after upload write csrf full restoration
- Working tree expected state: clean

## 2. Purpose

`delete_attachment()` now has Django CSRF protection and already verifies that the attachment's source entity exists. User permission authorization is still missing.

This analysis identifies the permission prerequisites needed before delete authorization can be implemented safely. This task does not modify code or call the delete endpoint.

## 3. Current delete_attachment State

The current `views_uploads.py` flow:

- requires an authenticated user
- accepts the DELETE method only
- uses Django CSRF protection
- resolves the current tenant database alias
- looks up the `Attachment` in the tenant database
- returns HTTP 410 when the attachment is already deleted
- calls `_resolve_attachment_entity()` before deletion
- performs a soft delete by setting deletion metadata and saving the attachment
- retains the existing avatar fallback session update

Missing:

- no user permission authorization is performed before the soft delete

## 4. Existing Permission Systems

### `gf_perm_required`

- Reads permissions through `gf_get_perms()`.
- Uses `request._gf_perms_cache` first, then session `gf_perms`.
- Treats multiple permission codes as an OR condition.
- Requires authentication.
- Has no explicit staff bypass in its implementation.

### `_gf_perms_cache`, session `gf_perms`, and session `perms`

- `_gf_perms_cache` and `gf_perms` are the primary inputs used by the `gf_authz` helpers.
- Some tenant views and the legacy `require_perm` path use session `perms`.
- The upload READ helper conservatively checks all three sources without adding a new permission model or central database query.

### `require_perm`

- Uses the existing ACL template-tag permission logic.
- Includes a central staff bypass.
- May query the central database to confirm staff status.
- Is used by employee views, including `directory.view` and `directory.edit` enforcement.

### Existing upload READ authorization

`presign_get()` uses `_request_has_any_perm()` and `_authorize_attachment_read()`. The helper checks `_gf_perms_cache`, `gf_perms`, and `perms`, and maps source entities to confirmed READ permissions. A future delete helper should mirror this conservative session lookup, but use separately confirmed write permissions.

## 5. Existing Permission Codes

| permission code | confirmed usage? | current meaning | delete suitability |
|---|---:|---|---|
| `directory.view` | Yes | Employee list/detail read | No; read-only permission |
| `directory.edit` | Yes | Employee create/edit and write UI | Yes; grounded employee write permission |
| `contracts.view` | Yes | Contract list/detail read | No; read-only permission |
| `contracts.create` | Yes | Contract creation | No; creation does not imply delete |
| `contracts.edit` | No confirmed enforcement | Candidate contract update permission in documentation | Not until assignment and enforcement are confirmed |
| `contracts.delete` | No confirmed enforcement | Candidate contract delete permission in documentation | Not until assignment and enforcement are confirmed |
| `projects.view` | Yes | Project and project-scope read | No; read-only permission |
| `projects.edit` | Yes | Project create/edit and scope changes | Potential project write permission, but project attachments are unsupported in this slice |
| `files.view` | No | No confirmed permission implementation or assignment | Do not use |
| `files.upload` | No | No confirmed permission implementation or assignment | Do not use |
| `files.delete` | No | No confirmed permission implementation or assignment | Do not use |

Permission semantics must not be invented. In particular, `contracts.create` must not be treated as contract attachment delete authority.

## 6. Entity-specific Delete Authorization Options

### employee

Options:

- require `directory.edit`
- allow a narrowly scoped employee self photo or document delete exception
- defer the self exception

`directory.edit` is the safest currently grounded permission for employee attachment deletion. The self exception should remain deferred until the login user-to-employee identity mapping and allowed attachment purposes are explicitly confirmed.

### contract

Options:

- require `contracts.edit`
- require `contracts.delete`
- require `contracts.create`
- defer or fail closed

`contracts.create` is not a safe delete permission. Neither `contracts.edit` nor `contracts.delete` has confirmed enforcement and assignment semantics in the inspected baseline. Contract attachment deletion should therefore fail closed until a contract write/delete permission is explicitly confirmed.

### event

Event attachment deletion should inherit authority from the event's source scope:

- employee-scoped event: require `directory.edit`
- contract-scoped event: require a confirmed contract write/delete permission
- orgunit or unknown scope: fail closed

The existing event and attachment link resolution should remain separate from this authorization decision.

### orgunit

The orgunit attachment feature and its permission policy remain deferred. Orgunit attachment deletion should fail closed until an explicit policy exists.

### project / unknown

Project and unknown attachment types should fail closed until their upload support and delete permission policies are explicitly approved.

## 7. Recommended Authorization Helper Design

Proposed helper:

- `_authorize_attachment_delete(request, alias, attachment) -> bool`

Expected behavior:

- employee: require `directory.edit`
- contract: require an explicitly confirmed contract write/delete permission; otherwise return `False`
- event:
  - employee source: require `directory.edit`
  - contract source: require the explicitly confirmed contract write/delete permission
  - orgunit or unknown source: return `False`
- orgunit, project, and unknown entity: return `False`

The helper should reuse the conservative session permission lookup already used by READ authorization. It should not introduce role-name bypasses, new central permission queries, or unconfirmed permission codes.

Authorization should occur after attachment and source-entity resolution but before any soft-delete field is changed or saved.

## 8. Implementation Risk

- A logged-in user who knows an attachment identifier can currently attempt a same-tenant delete without a source-entity permission check.
- An overbroad permission mapping could authorize destructive operations beyond the user's actual entity rights.
- Using `contracts.create` would incorrectly convert a creation permission into delete authority.
- Contract write/delete permission codes and their assignments need confirmation.
- A self-photo exception could authorize the wrong employee attachment if identity mapping or purpose restrictions are incomplete.
- Although deletion is soft, it is user-visible and changes attachment availability, so write or delete authority is required.

## 9. Recommended First Implementation Slice

Recommendation: **B. implement employee + event employee-scope only**.

The limited slice should:

- authorize employee attachment deletion with `directory.edit`
- authorize employee-scoped event attachment deletion with `directory.edit`
- fail closed for contract, contract-scoped event, orgunit, project, and unknown types
- avoid `contracts.create`
- avoid inventing `contracts.edit` or `contracts.delete`
- avoid an employee self exception

This slice closes a grounded subset without broadening uncertain contract permissions. If partial entity support is operationally unacceptable, choose D and defer the entire implementation until the contract permission mapping is confirmed.

## 10. Required Tests For Later Implementation

DB/S3-free unit tests:

- employee attachment delete requires `directory.edit`
- employee attachment delete is denied without `directory.edit`
- employee-scoped event attachment delete inherits `directory.edit`
- contract attachment delete fails closed until contract permission is confirmed
- contract-scoped event attachment delete fails closed
- orgunit, project, and unknown entities fail closed
- denied delete does not call the attachment soft-delete save
- denied delete does not call S3
- existing upload CSRF tests still pass
- existing READ authorization tests still pass

Browser smoke tests after implementation:

- a user with the allowed permission can delete a disposable attachment
- a restricted user cannot delete when a suitable restricted account exists
- upload and read flows still work
- PDF inline behavior still works
- Excel download-only behavior still works

## 11. Final Recommendation

Implement delete authorization only as a limited slice where the permission mapping is grounded.

- Employee attachments and employee-scoped event attachments may use `directory.edit`.
- Do not implement contract attachment deletion authorization until the actual contract write/delete permission and assignment policy are confirmed.
- Do not use `contracts.create`.
- Do not implement an employee self photo or document exception yet.
- Keep CSRF restoration and user authorization as separate axes: CSRF is complete; delete authorization remains pending.

## 12. Safety Notes

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
