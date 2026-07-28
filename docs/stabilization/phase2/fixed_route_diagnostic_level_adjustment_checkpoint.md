# Fixed Route Diagnostic Level Adjustment Checkpoint

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: d88bcc8 phase2: document fixed route diagnostic levels
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Completed Scope

- Fixed route diagnostic level analysis was completed.
- Minimal design was completed.
- Minimal implementation was completed.
- Implementation result was documented.
- Normal successful route diagnostics were lowered from INFO to DEBUG.
- Failure, fail-closed, availability, and security diagnostics remain visible.
- Control route regression tests passed.
- This log-level adjustment item is ready to close.

## 3. Commit Sequence

- `f3f0306 phase2: analyze fixed route diagnostic levels`
- `10475c5 phase2: design fixed route diagnostic levels`
- `58d9d36 phase2: lower fixed route diagnostics to debug`
- `d88bcc8 phase2: document fixed route diagnostic levels`

## 4. Modified Files by Implementation

- `control/middleware.py`
- `control/views_auth.py`
- `control/test_tenant_connection_registration.py`

Implementation state:

- `control/middleware.py` changed normal route diagnostics from INFO to DEBUG.
- `control/views_auth.py` changed normal login/post-login route diagnostics from INFO to DEBUG.
- `control/test_tenant_connection_registration.py` changed only the directly affected log assertion from `logger.info` to `logger.debug`.
- No `geoflow_ops` file was modified.
- No template or static file was modified.
- No settings, URL, migration, or DB schema file was modified.

## 5. Diagnostics Adjusted

| file | diagnostic area | final state |
|---|---|---|
| `control/middleware.py` | normal central route resolution | DEBUG |
| `control/middleware.py` | normal tenant route resolution | DEBUG |
| `control/middleware.py` | inactive selector normal route diagnostics | DEBUG |
| `control/middleware.py` | central guard expected redirect decision | DEBUG |
| `control/views_auth.py` | expected multiple tenant candidate decision | DEBUG |
| `control/views_auth.py` | expected central route without tenant membership | DEBUG |
| `control/views_auth.py` | successful post-login central route | DEBUG |
| `control/views_auth.py` | successful post-login tenant route | DEBUG |

## 6. Diagnostics Preserved

- Tenant connection unavailable warnings remain unchanged.
- Router unavailable or unregistered route target warnings remain unchanged.
- Tenant connection verification/configuration warnings remain unchanged.
- Authentication lookup or eligibility failure warnings remain unchanged.
- Post-login tenant connection unavailable warnings remain unchanged.
- Authorization denial warnings remain unchanged.
- Failure, fail-closed, and security-relevant diagnostics remain visible.

## 7. Verification Summary

| command | result |
|---|---|
| `python -m py_compile control/middleware.py control/views_auth.py` | passed |
| `python manage.py test control.test_group_search_login_fix` | 16 tests OK |
| `python manage.py test control.test_tenant_connection_registration` | 29 tests OK |
| `python manage.py check` | passed with existing W342 warning only |
| `git diff --check` | passed |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

- Existing W342 warning remains unrelated.
- No browser smoke was performed because this was a log-level-only change.
- No unexpected traceback or test failure was observed.

## 8. Behavior Preservation

- No routing condition was changed.
- No redirect target was changed.
- No session key or session mutation was changed.
- No tenant candidate filtering or selection validation was changed.
- No tenant connection registration or verification behavior was changed.
- No middleware order was changed.
- No router behavior was changed.
- No authentication behavior was changed.
- No authorization behavior was changed.
- No DB schema or data behavior was changed.
- No S3/upload behavior was changed.

## 9. Safety Status

- No DB write was performed.
- No migration was performed.
- No tenant schema change was performed.
- No endpoint call was performed.
- No browser smoke was performed for this checkpoint.
- No S3 operation was performed.
- No presigned URL was generated.
- No sensitive runtime identifier was recorded.
- `excel_preview.html` remains absent.
- `thumbnail-utils.js` remains absent.

## 10. Deferred Items

- central dashboard medium-risk log cleanup
- inactive selector diagnostic removal or legacy class cleanup
- unrelated test-only diagnostic cleanup
- W342 model warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups
- broad AdminKit-derived template cleanup

## 11. Recommended Next Work

- The fixed route diagnostic level adjustment item is closed.
- The next safe candidate is central dashboard medium-risk log cleanup analysis.
- An alternative safe candidate is inactive selector legacy cleanup analysis.
- W342 cleanup should remain deferred unless explicitly selected.
- Level 2 write/upload smoke still requires separate explicit approval.

## 12. Safety Notes

- No code or test was modified by this documentation task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB config value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
