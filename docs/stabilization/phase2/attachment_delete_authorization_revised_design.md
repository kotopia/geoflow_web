# Attachment Delete Authorization Revised Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: c23fcff phase2: document disposable event cleanup attempt
- Working tree expected state: clean

## 2. Purpose

Attachment delete CSRF restoration and presign GET read authorization are already complete. Contract write permission hardening has progressed after `contracts.edit` provisioning:

- contract detail POST now requires `contracts.edit`
- contract-scoped event writes now require `contracts.edit`

Attachment delete authorization can therefore be revised to allow contract-scope deletion through `contracts.edit`.

This document is design only and performs no code or DB change.

## 3. Current Permission Baseline

- `directory.edit` exists and is assigned as employee write authority.
- `contracts.edit` now exists and is assigned to the approved operational roles.
- `contracts.view` remains read-only.
- `contracts.create` remains creation-only.
- `contracts.delete` remains out of scope and is not used by this design.

The write permissions must be evaluated by permission code. Role names must not be checked directly.

## 4. Proposed Attachment Delete Permission Matrix

| resolved entity/scope | required permission | result |
|---|---|---|
| employee attachment | `directory.edit` | allow if present |
| employee-scoped event attachment | `directory.edit` | allow if present |
| contract attachment | `contracts.edit` | allow if present |
| contract-scoped event attachment | `contracts.edit` | allow if present |
| orgunit attachment | none in this slice | fail closed |
| project attachment | none in this slice | fail closed |
| unknown/unresolved | none | fail closed |

Rules:

- `contracts.view` must not authorize deletion.
- `contracts.create` must not authorize deletion.
- `contracts.delete` is not used in this slice.
- Role names must not be checked directly.
- No new staff bypass may be introduced.

## 5. Entity Resolution Rule

- Resolve the attachment before authorization.
- Derive the true entity and scope from stored attachment and link data.
- Do not trust request payload or URL context for authorization.
- Event attachments inherit delete authorization from the stored event source scope.
- Verify event-to-attachment linkage through existing entity resolution.
- An unresolved, unsupported, or inconsistent entity/scope must fail closed before mutation.

For event attachments, the stored event scope is authoritative even if request context suggests a different scope.

## 6. Mutation Ordering

Required order inside the delete flow:

1. resolve the tenant alias
2. load the attachment
3. return the existing not-found or already-deleted response when applicable
4. resolve and validate the stored source entity and link
5. authorize attachment deletion from the resolved entity/scope
6. only then enter the existing mutation path

The permission check must occur before:

- soft-delete field changes
- attachment-row save
- event-link deletion
- attachment-row deletion
- any S3-related action

Denied requests:

- return HTTP 403
- do not call S3
- do not mutate the tenant DB
- do not alter session fallback state

## 7. Proposed Helper Shape

Design only:

- reuse `_resolve_attachment_entity(alias, attachment)`
- add or revise `_authorize_attachment_delete(request, alias, attachment)`
- reuse `_request_has_any_perm()` or the established permission helper
- do not query user or role tables
- do not print identifiers

Expected behavior:

- employee: require `directory.edit`
- contract: require `contracts.edit`
- event:
  - resolve the stored `ProcessEvent`
  - employee source: require `directory.edit`
  - contract source: require `contracts.edit`
  - orgunit, project, unknown, or missing source: deny
- orgunit: deny
- project: deny
- unknown: deny

The helper should return a boolean and leave response construction to the view. A denied delete should use the existing JSON error style with HTTP 403.

## 8. Implementation Slice Proposal

Future implementation should be limited to:

- `geoflow_ops/views_uploads.py`
- one DB-free test file for attachment delete authorization

Do not include:

- templates or static changes
- migrations
- event code changes
- contract code changes
- S3 cleanup logic
- raw DB cleanup
- permission provisioning

The existing successful delete mutation logic should remain unchanged after authorization passes.

## 9. Test Plan

DB-free tests should verify:

1. employee attachment deletion requires `directory.edit`
2. employee-scoped event attachment deletion requires `directory.edit`
3. contract attachment deletion requires `contracts.edit`
4. contract-scoped event attachment deletion requires `contracts.edit`
5. `contracts.view` does not authorize contract attachment deletion
6. `contracts.create` does not authorize contract attachment deletion
7. unsupported orgunit, project, and unknown attachment deletion fails closed
8. denied deletion returns HTTP 403 before mutation
9. denied deletion does not call S3
10. allowed deletion reaches the existing mutation stage
11. existing upload CSRF tests still pass
12. existing presign GET read authorization tests still pass
13. existing contract and event write permission tests still pass

Mocks should cover:

- attachment lookup
- source entity and event lookup
- event-to-attachment link lookup
- attachment save
- session fallback DB lookup
- any S3 service call

No real tenant DB, attachment, event, or S3 object should be used in unit tests.

## 10. Browser Smoke Plan After Implementation

Only after implementation and commit, and only with explicit approval:

- logout/login to refresh the permission session
- contract detail GET returns HTTP 200
- delete a disposable contract-scoped event attachment through the existing UI/API
- delete response returns HTTP 200
- event list or detail refresh returns HTTP 200
- do not perform raw DB cleanup
- do not perform direct S3 cleanup unless the existing delete implementation already does so

Run a negative smoke test only if a suitable restricted user is safely available.

Any disposable data created for the smoke must have a separately approved cleanup plan.

## 11. Out of Scope

- attachment upload authorization changes
- presign-put or commit changes
- direct S3 cleanup
- raw DB cleanup
- orgunit or project delete policy
- employee self-delete exception
- `contracts.delete` creation or assignment
- multi-tenant `group_search` login issue
- UI, template, or static changes
- migrations

## 12. Risk Analysis

- Authorizing from request data could allow scope spoofing.
- Authorizing after mutation begins could allow an unauthorized deletion.
- Using `contracts.view` or `contracts.create` would over-grant write/delete capability.
- Failing to support contract scope now may block valid contract workflows.
- Orgunit and project scopes still require separate permission policy.
- Existing sessions may need logout/login before `contracts.edit` appears.
- Browser smoke testing may create real tenant data and requires separate approval.

## 13. Safety Notes

Confirmed:

- no code was modified
- no DB write was performed
- no migration was performed
- no event, upload, or delete endpoint was called
- no attachment delete endpoint was called
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
