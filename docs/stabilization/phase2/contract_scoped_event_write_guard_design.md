# Contract-scoped Event Write Guard Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: ae5a270 phase2: document contract detail post guard browser smoke
- Working tree expected state: clean

## 2. Purpose

Contract detail POST is now protected by `contracts.edit`. Contract-scoped event create, update, and delete operations still require separate write authorization hardening.

Event list and read behavior must remain read-only and must not be broken by the write guard. This document designs the next limited slice only. No code or DB change is performed in this task.

## 3. Current Observed Event Flow

Sanitized observed flow:

- the contract detail page loads the event list for contract scope
- contract-scoped event creation currently succeeds
- contract-scoped event update currently succeeds
- upload and attachment lifecycle operations are related but remain outside this event write guard slice

No UUIDs, object keys, filenames, attachment identifiers, event identifiers, user emails, or names are included.

## 4. Proposed Permission Rule

- contract-scoped event create requires `contracts.edit`
- contract-scoped event update requires `contracts.edit`
- contract-scoped event delete requires `contracts.edit`
- contract-scoped event list/read remains governed by read permission and is not changed by this write guard
- `contracts.view` must not authorize event writes
- `contracts.create` must not authorize event writes
- role names must not be checked directly
- no new staff bypass may be introduced

The guard should reuse the established permission lookup used by the contract detail POST guard.

## 5. Scope Resolution Rules

### Create

- Parse and validate the submitted request data.
- Use the submitted `scope_type`.
- If `scope_type == "contract"`, require `contracts.edit`.
- Perform the permission check before constructing or saving the event.
- Do not perform a tenant DB write when authorization fails.

### Update

- Do not trust only submitted payload data for authorization.
- Resolve the existing event first.
- Derive the actual scope from the stored event record.
- If the stored scope is contract, require `contracts.edit`.
- Perform the permission check before applying field changes or calling save.

### Delete

- Resolve the existing event first.
- Derive the actual scope from the stored event record.
- If the stored scope is contract, require `contracts.edit`.
- Perform the permission check before deleting links, deleting the event, or making any other mutation.

### Non-contract scopes

- Do not expand non-contract policy in this slice unless it is already clearly implemented.
- Employee-scoped event writes may be handled later with a separately approved `directory.edit` policy.
- Orgunit, project, and unknown scopes should remain unchanged or fail closed according to existing behavior.
- Do not invent broad permissions.

## 6. Proposed Helper Shape

Design only:

`_authorize_event_write(request, alias, event=None, scope_type=None, scope_id=None)`

Expected behavior:

- determine the effective scope from the stored event when an event is provided
- otherwise use the already validated create scope
- for contract scope, return allowed only when `gf_has_perm(request, "contracts.edit")` succeeds
- return a denied result for a contract-scope write without `contracts.edit`
- allow the view to return HTTP 403 before mutation
- do not query users or roles directly
- do not check role names
- do not print identifiers

The helper should remain small and should not include attachment or upload authorization.

## 7. Implementation Slice Proposal

Future implementation should be limited to:

- `geoflow_ops/views_events.py`
- one new DB-free event write permission unit test file

Do not include:

- templates
- static JavaScript
- URL changes unless a separately discovered requirement makes them necessary
- upload or attachment code
- models or migrations

## 8. Test Plan

DB-free unit tests should verify:

1. contract-scoped event create without `contracts.edit` returns HTTP 403
2. contract-scoped event create with only `contracts.view` returns HTTP 403
3. contract-scoped event create with only `contracts.create` returns HTTP 403
4. contract-scoped event create with `contracts.edit` passes the permission stage
5. contract-scoped event update derives scope from the stored event, not only request payload
6. contract-scoped event update without `contracts.edit` returns HTTP 403 before save
7. contract-scoped event delete without `contracts.edit` returns HTTP 403 before link or event deletion
8. denied create, update, and delete do not call mutation functions
9. event list/read behavior is unchanged

Mocks should replace:

- tenant alias resolution where needed
- `ProcessEvent` lookup
- event save
- event-link delete
- event delete

Regression tests:

- contract detail POST guard tests
- upload write CSRF tests
- presign GET read authorization tests
- `python manage.py check`

## 9. Browser Smoke Plan After Implementation

After a future approved implementation and commit:

- logout/login to refresh the permission session
- contract detail GET returns HTTP 200
- contract event list GET returns HTTP 200
- contract-scoped event create with an approved user returns HTTP 200
- contract-scoped event update with an approved user returns HTTP 200
- optionally test delete only with a disposable event and explicit approval
- do not perform S3, attachment delete, or upload mutation unless separately approved

## 10. Out of Scope

- attachment delete authorization
- upload presign or commit authorization changes
- employee-scoped event policy changes
- orgunit or project event policy changes
- multi-tenant `group_search` login issue
- `contracts.delete` creation or assignment
- templates or static UI changes
- migrations
- tenant schema changes

## 11. Risk Analysis

- Event update and delete must resolve the stored event scope to prevent payload spoofing.
- Applying `contracts.edit` to every scope could break non-contract workflows.
- Performing authorization after mutation begins could allow unauthorized changes.
- Existing sessions may require logout/login after permission changes.
- Browser smoke testing may create or update real tenant data, so disposable event use requires explicit approval.
- Create authorization must occur before event save.
- Update authorization must occur before field assignment and save.
- Delete authorization must occur before link or event deletion.

## 12. Safety Notes

Confirmed:

- no code was modified
- no DB write was performed
- no migration was performed
- no event endpoint was called
- no upload or delete endpoint was called
- no S3 access was performed
- no presigned URL was generated or printed
- no `.env` contents were printed
- no `RRN_SYM_KEY` was printed or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no UUID, object key, attachment filename, or raw ID was recorded
- no user email, name, or phone number was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
