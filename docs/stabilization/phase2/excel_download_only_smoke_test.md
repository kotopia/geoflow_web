# Excel Download-only Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: a4274a5 phase2: enforce excel attachments as downloads
- Runtime: local Django development server
- Tenant alias observed: cheonan_db
- Excel preview policy: disabled / download-only

## 2. Purpose

Validate that Excel attachments no longer use the removed Excel preview route and continue to work through the presigned GET flow.

## 3. Pages Checked

The following pages returned HTTP 200:

- /employees/
- /employees/<employee_id>/
- /employees/<employee_id>/?edit=1
- /contracts/
- /contracts/<contract_id>/

## 4. Event Attachment Flow Checked

The following event and attachment API paths returned HTTP 200:

- GET /api/events/list/
- GET /events/ui/modal/
- POST /api/events/create/
- POST /api/uploads/presign-put/
- POST /api/uploads/commit/
- POST /api/events/update/<event_id>/
- GET /api/uploads/presign-get/<xlsx_attachment_id>/?mode=inline
- GET /api/uploads/presign-get/<pdf_attachment_id>/?mode=inline
- DELETE /api/uploads/delete/<attachment_id>/
- POST /api/events/delete/<event_id>/

## 5. Excel Behavior

Observed Excel attachment:

- object key ended with .xlsx
- presign-get endpoint returned HTTP 200
- request used mode=inline from the process-event UI
- no /uploads/excel-preview/<attachment_id>/ request appeared in the server log

Expected backend behavior after a4274a5:

- Excel files are treated as attachment downloads regardless of requested mode.
- The removed Excel preview template is not required.

## 6. PDF Behavior

Observed PDF attachment:

- object key ended with .pdf
- presign-get endpoint returned HTTP 200
- mode=inline was preserved for PDF inline preview behavior

## 7. Cleanup Verification

The smoke test also confirmed:

- uploaded Excel attachment could be deleted
- uploaded image attachment could be deleted
- test event could be deleted
- event list reloaded after cleanup
- git status remained clean

## 8. File State

Expected file state:

- geoflow_ops/templates/geoflow_ops/excel_preview.html does not exist
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js does not exist

## 9. Result

PASS.

Excel preview remains disabled, and Excel attachments no longer depend on the removed preview template or route.
