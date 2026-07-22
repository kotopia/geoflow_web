# Presign GET/Delete Entity Resolution Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: af15a2f phase2: resolve attachment entities before get and delete
- Runtime: local Django development server
- Tenant alias observed: cheonan_db

## 2. Purpose

Validate that the new attachment entity resolution check does not break normal presign_get() and delete_attachment() flows.

The tested hardening checks:

- attachment source entity resolution before presigned GET URL generation
- attachment source entity resolution before soft delete
- event attachment link existence check
- existing PDF inline behavior preservation
- existing Excel download-only behavior preservation

## 3. APIs Checked

Observed HTTP 200 responses:

- GET /contracts/<contract_id>/
- GET /api/events/list/
- GET /events/ui/modal/
- POST /api/uploads/presign-put/
- POST /api/uploads/commit/
- GET /api/uploads/presign-get/<event_pdf_attachment_id>/?mode=inline
- DELETE /api/uploads/delete/<event_attachment_id>/
- GET /api/events/list/

## 4. Employee Attachment Check

Observed employee photo/thumb presign_get requests returned HTTP 200 for valid employee attachments.

This confirms that employee attachment entity resolution works for normal employee photo/thumb records.

## 5. Event Attachment Check

Observed event attachment flow:

- presign-put generated object key under tenants/cheonan_db/events/<event_id>/doc/
- commit created Attachment metadata
- commit created ProcessEventAttachment link
- presign-get returned HTTP 200
- delete returned HTTP 200

This confirms that event entity and event-attachment link resolution work for normal event attachments.

## 6. Separate Employee Detail Error

Some employee detail pages returned HTTP 500 with:

- Wrong key or corrupt data

This error came from views_employees.py during encrypted data decryption, not from views_uploads.py.

Decision:

- Treat this as a separate employee encrypted-data issue.
- Do not handle it in the upload hardening scope.
- Do not change RRN_SYM_KEY.
- Do not output .env or secret values.

## 7. Result

PASS.

The presign_get/delete entity resolution hardening did not break normal attachment GET/delete flows.

## 8. Scope Not Covered

This smoke test does not cover:

- user permission authorization
- CSRF restoration
- orphan attachment cleanup
- unsupported entity rejection test with crafted data
- encrypted employee data repair

## 9. File State

Expected file state:

- geoflow_ops/templates/geoflow_ops/excel_preview.html does not exist
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js does not exist
