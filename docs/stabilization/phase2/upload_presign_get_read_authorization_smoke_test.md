# Upload Presign GET Read Authorization Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: 7898635 phase2: authorize upload presign get reads
- Runtime: local Django development server
- Tenant alias observed: cheonan_db

## 2. Purpose

Validate that `presign_get()` READ authorization does not break existing allowed attachment read flows.

This smoke test covers positive regression flows.

Unauthorized negative testing with a restricted user was not covered in this run and remains required.

## 3. Implementation Under Test

Implemented in:

- geoflow_ops/views_uploads.py

Added helpers:

- `_request_has_any_perm(request, *codes)`
- `_authorize_attachment_read(request, alias, attachment)`

Authorization call location:

- after `_resolve_attachment_entity(alias, att)`
- before presigned URL generation

Changed endpoint:

- `presign_get()`

Not changed:

- `delete_attachment()`
- `presign_put()`
- `commit()`
- PDF inline handling
- Excel download-only handling
- avatar fallback logic

## 4. Read Authorization Policy Tested

Implemented read policy:

- employee attachment GET requires `directory.view`
- contract attachment GET requires `contracts.view`
- event attachment GET inherits read permission from `ProcessEvent.scope_type`
  - employee scope requires `directory.view`
  - contract scope requires `contracts.view`
- orgunit, project, and unknown entity/scope types fail closed
- `files.*` permissions are not used

Deferred:

- employee self photo GET exception
- delete authorization
- contract write/delete permission mapping

## 5. Positive Flow Results

Observed HTTP 200 responses:

- GET /employees/7d94badb-098a-4f2a-8e60-5a095519b748/
- GET /employees/7d94badb-098a-4f2a-8e60-5a095519b748/?edit=1
- GET /employees/
- GET /contracts/
- GET /contracts/553ebd35-2350-41a0-8d2b-ebd6632df0dc/
- GET /api/events/list/?scope_type=contract&scope_id=553ebd35-2350-41a0-8d2b-ebd6632df0dc
- GET /events/ui/modal/?scope_type=contract&scope_id=553ebd35-2350-41a0-8d2b-ebd6632df0dc

Observed attachment read HTTP 200 responses:

- employee photo_thumb `presign_get`
- event PDF inline `presign_get`
- event HWP `presign_get`
- event XLSX `presign_get`

## 6. Upload/Delete Regression Check

Observed successful event attachment flow:

- POST /api/uploads/presign-put/ returned HTTP 200
- POST /api/uploads/commit/ returned HTTP 200
- event attachment link was created
- DELETE /api/uploads/delete/<attachment_id>/ returned HTTP 200

This confirms that this read-only authorization slice did not change the existing delete flow.

## 7. Excel Download-only Check

Excel attachment `presign_get` returned HTTP 200.

The old Excel preview route/template remains absent.

Expected state:

- `excel_preview.html` does not exist
- `thumbnail-utils.js` does not exist

## 8. Not Covered

Not covered in this smoke test:

- unauthorized user attachment GET denial
- restricted user without `directory.view`
- restricted user without `contracts.view`
- employee self photo GET exception
- orgunit fail-closed runtime test
- project/unknown fail-closed runtime test

These require a separate restricted-user smoke test.

## 9. Result

PASS for positive regression flows.

The `presign_get()` READ authorization helper did not break existing allowed employee, contract, event, PDF, HWP, XLSX, upload, commit, or delete flows under the tested user.

## 10. Follow-up

Required follow-up:

- restricted-user negative authorization test
- document whether unauthorized access returns 403 before presigned URL generation
- later decide `delete_attachment()` authorization after contract write/delete permission is confirmed

