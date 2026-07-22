# Presign GET/Delete Entity Resolution Design

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: 998c844 phase2: document upload commit scope smoke test
- Working tree expected state: clean
- Excel preview policy: disabled / download-only
- Current upload hardening state: commit() object key scope validation implemented and smoke-tested

## 2. Purpose

Design the next minimal hardening slice for presign_get() and delete_attachment().

The goal is not full authorization yet.

The goal is to add entity resolution before issuing presigned GET URLs or soft-deleting attachments.

## 3. Current Flow Summary

### presign_get()

Current flow:

- resolve tenant DB alias
- query Attachment by attachment_id
- reject deleted attachment
- detect PDF and Excel
- generate presigned GET URL
- return URL, original file name, and MIME type

Current gaps:

- no entity_type validation
- no entity_id existence check
- no event attachment link check
- no user view permission check

### delete_attachment()

Current flow:

- resolve tenant DB alias
- query Attachment by attachment_id
- reject already deleted attachment
- set deleted_at, deleted_by, and is_deleted
- save soft-delete state
- update avatar session fallback if needed
- return success JSON

Current gaps:

- no source entity existence check
- no attachment delete permission check
- no event attachment link check
- no parent/thumbnail integrity check

## 4. Attachment Fields Relevant to Resolution

Relevant Attachment fields:

- id
- entity_type
- entity_id
- purpose
- object_key
- original_name
- mime_type
- active
- deleted_at
- is_deleted
- kind
- parent
- derivatives

Entity resolution should primarily use attachment.entity_type and attachment.entity_id.

Parent or derivative relationships should not be required in the first slice, because existing thumbnail data may not have complete parent linkage.

## 5. Event Attachment Link Structure

Event attachment structure:

- ProcessEvent has id, scope_type, and scope_id
- ProcessEventAttachment links ProcessEvent and Attachment
- normal event attachment should satisfy:
  - Attachment.entity_type == "event"
  - Attachment.entity_id == ProcessEvent.id
  - ProcessEventAttachment.event_id == Attachment.entity_id
  - ProcessEventAttachment.attachment_id == Attachment.id

For event attachments, entity resolution should check both:

- ProcessEvent existence
- ProcessEventAttachment link existence

Permission checks should later follow ProcessEvent.scope_type and ProcessEvent.scope_id.

## 6. Recommended Minimal Resolution Design

Add an internal helper in views_uploads.py only.

Candidate helper:

- _resolve_attachment_entity(alias, attachment)

Expected behavior:

- employee: verify hr.employee_profile row exists
- contract: verify Contract exists
- orgunit: verify MyOrgUnit exists
- event: verify ProcessEvent exists and ProcessEventAttachment link exists
- project: unsupported for now
- unknown entity_type: reject

Failure policy:

- unsupported entity type: 404
- missing source entity: 404
- missing event link: 404
- DB errors: preserve existing error handling pattern

This helper should not perform user permission checks in the first slice.

## 7. Insertion Points

### presign_get()

Recommended order:

1. query Attachment
2. check deleted state
3. resolve attachment entity
4. preserve existing PDF/Excel/download logic
5. generate presigned URL
6. return existing response shape

This avoids changing Excel/PDF behavior.

### delete_attachment()

Recommended order:

1. query Attachment
2. check deleted state
3. resolve attachment entity
4. preserve existing soft-delete logic
5. preserve existing avatar fallback update
6. return existing response shape

If entity resolution fails, do not modify attachment state.

## 8. Entity Type Handling

| entity_type | Expected source | Existence check | Permission later | Notes |
|---|---|---|---|---|
| employee | hr.employee_profile | Yes | directory.view / directory.edit or self exception | Requires parameterized SQL because there is no current Employee ORM model |
| contract | Contract | Yes | contracts.view / edit permission | ORM .exists() possible |
| orgunit | MyOrgUnit | Yes | approved orgunit view/edit policy | Permission policy not approved yet |
| event | ProcessEvent + ProcessEventAttachment | Yes | inherit scope entity permission | Check event and event-attachment link |
| project | Project | Technically possible | projects.view / projects.edit | Keep unsupported because upload API allowlist does not support project |

## 9. Recommended First Implementation Slice

Recommended option:

- A. entity existence check only

Reasons:

- smallest safe hardening step
- no permission policy decision required
- no migration required
- no schema change required
- prevents GET/delete against orphan source entities
- limits code change mostly to views_uploads.py

Limitations:

- same-tenant UUID-based access is not fully solved
- user permission checks remain a later slice
- CSRF restoration remains a later slice

Do not implement options B or C in the first slice.

## 10. Risks and Preservation Requirements

### Employee avatar/photo_thumb

- employee existence check must support existing employee photo and thumbnail attachments
- do not require parent linkage in the first slice
- preserve avatar fallback session update after delete

### PDF inline preview

- do not change existing is_pdf detection
- do not change mode=inline PDF behavior

### Excel download-only

Do not change:

- filename selection
- .xls and .xlsx detection
- is_excel or mode == "download" branch
- disposition="attachment"

Entity resolution should be added before URL generation without touching this logic.

### Event attachment delete

- check ProcessEvent existence
- check ProcessEventAttachment link existence
- do not delete event links in this slice
- do not change event attachment soft-delete behavior
- orphan cleanup should remain a separate admin/operations task

### Soft delete

Do not add:

- hard delete
- S3 object delete
- parent/derivative cascade
- active flag changes

Preserve:

- deleted_at
- deleted_by
- is_deleted
- 410 response for already deleted attachments

## 11. DB / Migration Impact

No new migration is required.

No schema change is required.

Existing structures are sufficient for:

- Contract existence check
- MyOrgUnit existence check
- ProcessEvent existence check
- ProcessEventAttachment link check
- employee existence check through parameterized SQL against hr.employee_profile

Future DB changes may be needed only for:

- upload grants
- attachment ACL
- audit log table
- per-object permission model

## 12. Final Recommendation

Status:

- implement later

Recommended next code-change scope:

- views_uploads.py only
- entity existence check only
- no permission helper yet
- no CSRF restoration yet
- no DB/migration change

Expected next smoke tests:

- employee avatar presign_get still returns 200
- event PDF presign_get still returns 200
- event attachment delete still returns 200
- Excel download-only behavior remains unchanged
- orphan or unsupported entity attachment returns 404 if test data is available
