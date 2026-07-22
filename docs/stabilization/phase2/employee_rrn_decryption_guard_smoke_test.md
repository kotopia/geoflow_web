# Employee RRN Decryption Guard Smoke Test

## 1. Baseline

- Branch: phase2-clean-base
- Commit tested: a9047e7 phase2: guard employee rrn decryption failures
- Runtime: local Django development server
- Tenant alias observed: cheonan_db

## 2. Purpose

Validate that employee detail pages no longer return HTTP 500 when rrn_cipher cannot be decrypted by pgcrypto.

The goal is not data repair.

The goal is to keep the employee detail page available while preserving safe fallback behavior.

## 3. Pages Checked

Observed HTTP 200 responses:

- GET /contracts/<contract_id>/
- GET /employees/
- GET /employees/2d96f386-d8eb-411a-b872-90ea38362093/
- GET /employees/92631964-f4bf-42f9-b94b-088c53b56928/
- GET /employees/7d94badb-098a-4f2a-8e60-5a095519b748/

## 4. Previously Failing Employees

The following employee detail pages previously returned HTTP 500 due to:

- Wrong key or corrupt data

After the guard, both returned HTTP 200:

- /employees/2d96f386-d8eb-411a-b872-90ea38362093/
- /employees/92631964-f4bf-42f9-b94b-088c53b56928/

## 5. Normal Employee Check

A normal employee detail page also returned HTTP 200:

- /employees/7d94badb-098a-4f2a-8e60-5a095519b748/

This confirms that the guard did not break normal employee detail rendering.

## 6. Safe Logging Check

Observed warning log format:

- RRN decryption failed: employee_id=<uuid> error_type=OperationalError

The log includes only:

- employee ID
- exception class name

The log does not include:

- RRN_SYM_KEY
- .env values
- rrn_cipher
- decrypted resident registration number
- personal data

## 7. Upload/Attachment Flow Check

Observed related pages and APIs still returned HTTP 200:

- GET /contracts/<contract_id>/
- GET /api/events/list/
- GET /api/uploads/presign-get/<attachment_id>/?mode=inline

This confirms that the employee RRN guard did not interfere with the upload hardening work.

## 8. Result

PASS.

The code guard prevents damaged encrypted employee data from causing a full employee detail page HTTP 500.

## 9. Scope Not Covered

This smoke test does not repair damaged employee encrypted data.

Still separate:

- identifying damaged rows
- controlled data repair
- rrn_cipher / rrn_hash / rrn_last4 consistency repair
- any DB UPDATE
- any RRN_SYM_KEY change

## 10. File State

Expected file state:

- geoflow_ops/templates/geoflow_ops/excel_preview.html does not exist
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js does not exist
