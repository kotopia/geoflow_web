# Phase 2 Full Regression Test Result

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `4e617e4 phase2: document group selection autoroute policy`
- Working tree state before tests: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Confirm that the Phase 2 tenant-candidate stabilization work did not regress existing login, tenant routing, upload, authorization, contract, or event guard behavior.
- Confirm that the selected group-selection auto-route policy remains compatible with existing tests.
- Confirm that no migration or DB schema change is required.

## 3. Test Result Summary

| command | result |
|---|---|
| `python manage.py test control.test_group_search_login_fix` | 16 tests OK |
| `python manage.py test control.test_tenant_connection_registration` | 29 tests OK |
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | 12 tests OK |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | 7 tests OK |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | 9 tests OK |
| `python manage.py test geoflow_ops.test_contract_write_permission` | 6 tests OK |
| `python manage.py test geoflow_ops.test_event_write_permission` | 9 tests OK |
| `python manage.py check` | passed with existing W342 warning only |
| `python -m py_compile control/views_auth.py control/views_groups.py control/tenant_connections.py control/middleware.py control/db_router.py control/test_group_search_login_fix.py control/test_tenant_connection_registration.py` | passed |

## 4. Observed Warnings and Diagnostic Output

- The only Django system check warning was the pre-existing `catalog.CategoryParent.child` W342 warning.
- The `DATABASES` override warning appeared during tenant connection registration tests and is expected for that isolated test coverage.
- Sanitized middleware, router, and post-login diagnostic messages appeared during tenant routing tests.
- CSRF Forbidden diagnostic messages appeared during CSRF negative tests and are expected.
- Attachment-delete diagnostic output appeared during attachment delete authorization tests and is pre-existing test output.
- No unexpected traceback was observed.
- No test failure was observed.

## 5. Coverage Confirmed

- Group search login fix remains covered.
- Group selection session-candidate validation remains covered.
- Selectable tenant candidate filtering remains covered.
- Tenant connection registration remains covered.
- Middleware defensive tenant preparation remains covered.
- `EnsureTenantAliasMiddleware` pass-through behavior remains covered.
- Connection handler verification remains covered.
- Router fail-closed behavior remains covered.
- Attachment delete authorization remains covered.
- Upload write CSRF protection remains covered.
- Presign GET read authorization remains covered.
- Contract write permission guard remains covered.
- Contract-scoped event write guard remains covered.

## 6. Not Performed

- No code change
- No DB write
- No migration
- No schema change
- No tenant provisioning
- No permission provisioning
- No browser smoke
- No endpoint call
- No S3 access
- No presigned URL generation
- No template/static change
- No `settings.py` change

## 7. Safety Notes

- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB config value, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 8. Conclusion

- Phase 2 tenant-candidate stabilization regression test passed.
- Current policy remains:
  - zero selectable candidates: central fallback
  - one selectable candidate: direct tenant route
  - two or more selectable candidates: group-selection page
  - non-selectable candidates: excluded from session and UI
- The branch is ready for a Phase 2 completion checkpoint after this result document is committed.
