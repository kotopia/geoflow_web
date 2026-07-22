# Upload GET/Delete Permission Authorization Design

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: 4c8bc0e phase2: record checkpoint after upload hardening and rrn guard
- Working tree expected state: clean

## 2. Current Upload Authorization State

Current `presign_get()` and `delete_attachment()` checks include:

- `login_required`
- tenant DB Attachment existence
- `deleted_at` state
- source entity existence
- ProcessEvent and ProcessEventAttachment link existence for event attachments

The following checks are not implemented yet:

- user permission authorization
- read/write/delete permission helper
- event scope permission inheritance authorization
- CSRF restoration

## 3. Remaining Risk

A logged-in user who knows an attachment UUID may still attempt `presign_get()` or `delete_attachment()` against another attachment in the same tenant.

Tenant DB isolation limits cross-tenant exposure, but it does not provide attachment-level or source-entity-level user authorization within the tenant.

## 4. Existing Permission Systems

Two permission systems currently coexist:

- `gf_perm_required`
- `require_perm`

Their relevant behavior is:

- `gf_perm_required` is based on the session `gf_perms` value.
- `require_perm` is based on the session `perms` value and central permission lookup.
- `require_perm` includes a central `is_staff` bypass.
- `gf_perm_required` has no explicit staff bypass.
- An upload helper that reads only one session key directly may behave inconsistently with existing screens.

The implementation must therefore avoid inventing a third permission interpretation. A future helper should reuse or deliberately reconcile the existing permission sources and staff behavior.

## 5. Entity Permission Mapping Candidate

| entity_type | GET/read permission | DELETE/write permission | decision |
|---|---|---|---|
| employee | `directory.view` or a limited self-GET exception | `directory.edit` | Limit self GET to photo/photo_thumb/thumb purposes |
| contract | `contracts.view` | Approved contract write permission must be confirmed | Do not infer DELETE permission |
| orgunit | Policy unclear | Policy unclear | Defer or fail closed |
| event | Scope entity read permission | Scope entity write permission | Inherit from `ProcessEvent.scope_type` and `scope_id` |
| project | Unsupported | Unsupported | Continue rejecting under the current upload allowlist |

## 6. Event Scope Authorization

An event attachment should inherit authorization from the source entity identified by `ProcessEvent.scope_type` and `ProcessEvent.scope_id`, rather than using an independent event permission that does not currently exist.

Candidate mapping:

- event scope employee: `directory.view` for GET and `directory.edit` for DELETE
- event scope contract: `contracts.view` for GET and an explicitly approved contract write permission for DELETE
- event scope orgunit: defer or fail closed until an orgunit permission policy is approved
- unknown scope: fail closed

The authorization check should occur only after the existing event and event-attachment link resolution succeeds.

## 7. Employee Self GET Exception

Recommended policy:

- Allow a self-GET exception for the logged-in user's own employee attachment.
- Restrict that exception to avatar-related purposes such as `photo`, `photo_thumb`, and `thumb`.
- Do not allow a self-DELETE exception.
- Do not automatically extend the exception to `doc`, PDF, or general attachments.
- Do not grant authorization from an email string comparison alone; use the established login-to-employee identity relationship and tenant context.

This exception can preserve normal topbar avatar behavior for employees who do not have broad `directory.view` permission while avoiding a general employee-document access exception.

## 8. Contract DELETE Policy Gap

Using `contracts.view` for DELETE would incorrectly expand a read permission into a destructive write permission.

Inventing or assuming a code such as `contracts.edit` is also unsafe because the actual central permission code and its assignment policy have not been confirmed.

Contract attachment DELETE should therefore be deferred or fail closed until the real central permission code is verified and explicitly approved.

The full GET+DELETE authorization helper should not be implemented before this decision is made, because otherwise the helper would either grant excessive DELETE access or introduce an unverified permission dependency.

## 9. Orgunit Policy Gap

The current orgunit views do not establish a clear orgunit view/edit permission policy, and the orgunit attachment feature remains deferred.

The safest choices for this slice are:

- do not implement orgunit attachment GET/delete authorization yet, or
- fail closed for orgunit attachments until an explicit permission policy is approved

Temporary role-name assumptions such as tenant admin or manager should not be introduced without confirming their exact semantics and assignments.

## 10. Recommended Implementation Strategy

Status: implement later.

Recommended sequence:

1. Complete this design document.
2. Confirm the actual contract write permission code.
3. Approve the employee self-GET exception policy and allowed purposes.
4. Implement a minimal helper inside `views_uploads.py`.
5. Run focused smoke tests for allowed and denied users.
6. Document the implementation and smoke-test result.

## 11. Recommended First Code Slice

For the future implementation:

- Modified file: `geoflow_ops/views_uploads.py` only
- Candidate helper: `_authorize_attachment_action(request, alias, attachment, action)`
- Supported actions: `read` and `delete`
- `presign_get()` uses `read`.
- `delete_attachment()` uses `delete`.
- Call the helper immediately after entity resolution and before S3 URL issuance or soft delete.
- Return 403 on an explicit authorization failure, or 404 if the approved policy chooses resource-existence concealment.
- Do not change PDF inline, Excel download-only, or avatar fallback branches.
- No migration is required.
- No DB change is required.

The helper should fail closed for unsupported entity or scope types and must not expand the current upload entity allowlist.

## 12. Required Smoke Tests

Required tests:

- employee avatar/photo_thumb GET
- employee self photo GET
- unauthorized access to another employee attachment is rejected
- event PDF inline GET
- event attachment DELETE
- view-only user DELETE is rejected
- Excel download-only behavior is preserved
- normal employee detail page
- damaged-RRN employee detail page
- normal contract detail page
- orgunit fail-closed or deferred behavior
- `excel_preview.html` remains absent
- `thumbnail-utils.js` remains absent

Denied requests must also confirm that no presigned URL is issued and no attachment soft-delete state is changed.

## 13. Final Recommendation

Final recommendation:

- implement later
- permission hardening is necessary
- do not implement until contract DELETE permission and employee self-GET policy are confirmed
- orgunit remains deferred
- event authorization should inherit source entity scope
- next implementation should be a narrow `views_uploads.py`-only helper slice

