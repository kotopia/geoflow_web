# Phase 2 Completion Checkpoint

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `a0f30bd phase2: document full regression test result`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Phase 2 Scope Completed

Phase 2 stabilization covered:

- original dirty-file classification and clean-base handling
- Codex agent rules
- selected B/D group cleanup items
- Excel preview removal and download-only policy
- upload write CSRF restoration
- presign GET read authorization
- attachment delete authorization
- contract write permission guard
- contract-scoped event write guard
- employee RRN decryption failure guard
- group search login fix
- group selection session-candidate validation
- tenant connection registration
- middleware defensive tenant preparation
- `EnsureTenantAliasMiddleware` hardening
- tenant connection handler verification
- DB router fail-closed behavior
- selectable tenant candidate filtering
- group-selection auto-route policy decision
- full regression test result

## 3. Final Tenant Candidate Policy

| condition | behavior |
|---|---|
| zero selectable candidates | central fallback |
| one selectable candidate | direct tenant route |
| two or more selectable candidates | group-selection page |
| non-selectable candidates | excluded from session and UI |

- Option A is the selected policy.
- Group selection is not forced only because raw membership count is greater than one.
- Non-selectable candidates must not be shown as selectable choices.
- `group_select` must continue to validate against session candidates.

## 4. Final Regression Status

- `control.test_group_search_login_fix`: 16 tests OK
- `control.test_tenant_connection_registration`: 29 tests OK
- `geoflow_ops.test_attachment_delete_authorization`: 12 tests OK
- `geoflow_ops.test_upload_write_csrf`: 7 tests OK
- `geoflow_ops.test_upload_presign_get_read_authorization`: 9 tests OK
- `geoflow_ops.test_contract_write_permission`: 6 tests OK
- `geoflow_ops.test_event_write_permission`: 9 tests OK
- `python manage.py check`: passed with existing W342 warning only
- `py_compile`: passed

The existing W342 warning remains unrelated. Expected diagnostic messages appeared during negative tests. No unexpected traceback or test failure was observed.

## 5. Final Browser Smoke Status

- A fresh `--noreload` runserver smoke was performed before the full regression result.
- Multi-membership login completed.
- The group selection page was skipped because filtering left one selectable candidate.
- The tenant home/main page returned HTTP 200.
- The contracts page returned HTTP 200.
- `ConnectionDoesNotExist` was not observed.
- `ImproperlyConfigured` was not observed.
- This confirms the tested selectable tenant workflow.

## 6. Safety and Non-regression Notes

- No migration was required.
- No tenant DB schema change was made.
- No static tenant alias was added to `settings.py`.
- No DB password, host, tenant config, or `.env` value was recorded.
- `RRN_SYM_KEY` was not printed or changed.
- `excel_preview.html` remains absent.
- `thumbnail-utils.js` remains absent.
- Existing upload Excel behavior remains download-only.
- Existing S3 and presigned URL safety policy remains unchanged.
- Existing permission semantics remain:
  - employee attachment delete: directory edit permission
  - employee-scoped event attachment delete: directory edit permission
  - contract attachment delete: contract edit permission
  - contract-scoped event attachment delete: contract edit permission
  - orgunit, project, and unknown attachment scopes: fail closed

## 7. Deferred Items

The following remain deferred and are not implemented in this checkpoint:

- UX notice page for raw multi-membership users with one selectable candidate
- disabled unavailable group rows
- unavailable group explanation UI
- single-tenant browser smoke as a separate documented smoke
- broader manual smoke for contracts, events, and uploads after this checkpoint
- cleanup of unrelated diagnostic log noise
- W342 model warning cleanup
- any DB provisioning or tenant metadata repair for non-selectable groups

## 8. Conclusion

- Phase 2 tenant-candidate stabilization is complete at this checkpoint.
- The branch is clean and suitable as a safe continuation point.
- Next work should start from this completion checkpoint.
- Any future work must continue to avoid broad reset, dirty-repository merge, migration, tenant provisioning, or secret exposure unless explicitly approved.

## 9. Safety Notes

- No code was modified by this documentation task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB config value, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
