# Phase 2 Checkpoint After Upload Hardening and RRN Guard

## 1. Current Git State

- Branch: phase2-clean-base
- Latest commit: cc01fad phase2: document employee rrn guard smoke test
- Working tree expected state: clean

## 2. Current Safe Baseline

The current safe baseline is:

- cc01fad phase2: document employee rrn guard smoke test

This baseline includes:

- B-group safe recoveries
- topbar avatar S3 loading
- Excel preview revert
- Excel download-only frontend cleanup
- Excel download-only backend/URL cleanup
- Excel download-only smoke test documentation
- upload authorization read-only analysis
- commit() object_key scope validation
- commit() hardening smoke test documentation
- presign_get/delete entity resolution design
- presign_get/delete entity resolution implementation
- presign_get/delete entity resolution smoke test documentation
- employee encrypted data error analysis
- employee RRN decryption failure code guard
- employee RRN guard smoke test documentation

## 3. Upload Hardening Current State

Implemented:

- commit() entity_type allowlist
- commit() tenant/entity/purpose object_key prefix validation
- presign_get() source entity existence resolution before S3 URL generation
- delete_attachment() source entity existence resolution before soft delete
- event attachment link existence check for event attachments

Not yet implemented:

- user permission authorization for GET/delete
- read/write/delete permission helper
- event scope permission inheritance
- CSRF restoration
- orphan cleanup tooling
- attachment ACL or upload grant model

## 4. Excel Final State

Excel preview remains disabled.

Expected state:

- geoflow_ops/templates/geoflow_ops/excel_preview.html does not exist
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js does not exist
- /uploads/excel-preview/<uuid>/ route is removed
- excel_preview() view is removed
- Excel .xls and .xlsx attachments are forced to attachment download
- PDF inline behavior is preserved

## 5. Employee RRN Guard Current State

Implemented:

- employees_detail() catches pgcrypto decryption DatabaseError around the narrow decrypt block
- employee detail page continues rendering when rrn_cipher is damaged
- rrn_last4 fallback display is preserved
- safe warning log includes only employee_id and exception class name

Not changed:

- RRN_SYM_KEY
- .env
- encryption/save logic
- database data
- migrations

Still separate:

- identifying damaged employee rows
- controlled data repair
- rrn_cipher, rrn_hash, and rrn_last4 consistency repair

## 6. Smoke Test Summary

Observed successful flows:

- Excel download-only flow passed
- event attachment presign-put, commit, presign-get, and delete passed
- presign_get/delete entity resolution did not break normal attachment flows
- previously failing employee detail pages returned HTTP 200 after RRN guard
- normal employee detail page still returned HTTP 200
- related contract/event/upload pages still returned HTTP 200

## 7. Deferred Items

Still deferred:

- orgunit logo/photo/document attachment feature
- upload GET/delete permission authorization
- event scope permission inheritance
- CSRF restoration for write endpoints
- employee encrypted data repair
- employee_create.html address fields
- base_tenant.html broad overlay cleanup
- control/multitenancy dirty changes
- migration chain changes
- tenant provisioning/deprovisioning commands

## 8. Recommended Next Scope

Recommended next technical scope:

- upload GET/delete permission authorization read-only design

Alternative maintenance scope:

- controlled employee encrypted data repair plan

Recommended order:

1. upload GET/delete permission design
2. upload GET/delete permission implementation slice
3. employee encrypted data repair plan, if needed

## 9. Prohibited Until Explicitly Approved

Do not run or perform:

- git push
- migrate
- makemigrations
- migrate_all_tenants
- tenant_provision
- DB schema changes
- DB UPDATE/INSERT/DELETE
- .env output
- RRN_SYM_KEY output or rotation
- encrypted value output
- decrypted personal data output
- dirty worktree wholesale copy
- excel_preview.html recreation
- thumbnail-utils.js recreation
