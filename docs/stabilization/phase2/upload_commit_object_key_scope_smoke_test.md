# Upload Commit Object Key Scope Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: 3f04d17 phase2: validate upload commit object key scope
- Runtime: local Django development server
- Tenant alias observed: cheonan_db

## 2. Purpose

Validate that the new commit() object_key scope checks do not break the normal event attachment upload flow.

The tested hardening checks:

- entity_type allowlist
- tenant alias prefix
- entity folder prefix
- entity_id prefix
- purpose segment prefix

## 3. Pages and APIs Checked

Observed HTTP 200 responses:

- GET /contracts/<contract_id>/
- GET /events/ui/modal/
- POST /api/uploads/presign-put/
- POST /api/uploads/commit/
- GET /api/events/list/
- GET /api/uploads/presign-get/<attachment_id>/?mode=inline
- DELETE /api/uploads/delete/<attachment_id>/

## 4. Observed Object Key

Observed presign-put generated an event attachment key with this structure:

- tenants/cheonan_db/events/<event_id>/doc/2026/07/<filename>.pdf

Observed commit payload:

- entity_type: event
- entity_id: same event UUID used in the object key
- purpose: doc

The commit endpoint returned HTTP 200.

## 5. Result

PASS.

The new commit() prefix validation matches the existing presign_put() object key structure for event attachments.

## 6. Scope Not Covered

This smoke test does not cover:

- entity existence validation
- user permission validation
- GET/delete authorization
- CSRF restoration
- mismatched object_key rejection
- nonexistent entity rejection

These remain future hardening scopes.

## 7. File State

Expected file state:

- geoflow_ops/templates/geoflow_ops/excel_preview.html does not exist
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js does not exist
