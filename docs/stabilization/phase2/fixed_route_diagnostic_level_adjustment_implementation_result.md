# Fixed Route Diagnostic Level Adjustment Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 10475c5 phase2: design fixed route diagnostic levels
- Implementation commit: 58d9d36 phase2: lower fixed route diagnostics to debug
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Reduce diagnostic noise from normal successful route decisions.
- Lower expected normal-path route diagnostics from INFO to DEBUG.
- Keep failure, fail-closed, availability, and authorization diagnostics visible.
- Preserve routing, session, authentication, tenant candidate, and tenant connection behavior.

## 3. Modified Files

- `control/middleware.py`
- `control/views_auth.py`
- `control/test_tenant_connection_registration.py`

No `geoflow_ops` files were modified. No templates or static files were modified. No settings or URL files were modified. No migrations were added or changed. No DB code path was intentionally changed.

## 4. Implementation Summary

- Normal route-resolution diagnostics in middleware were lowered from `logger.info()` to `logger.debug()`.
- Normal central/tenant route-resolution diagnostics in the inactive selector middleware were also lowered to DEBUG as log-level-only changes.
- Central guard expected redirect-decision diagnostics were lowered from INFO to DEBUG.
- Expected login candidate or central-route decision diagnostics were lowered from INFO to DEBUG.
- Successful post-login route diagnostics were lowered from INFO to DEBUG.
- A directly related test assertion was updated from `logger.info` to `logger.debug`.
- No routing conditions, redirects, session mutations, tenant candidate filtering, tenant connection registration, or fail-closed behavior were intentionally changed.

## 5. Diagnostics Lowered to DEBUG

| file | diagnostic area | change |
|---|---|---|
| `control/middleware.py` | normal central route resolution | INFO to DEBUG |
| `control/middleware.py` | normal tenant route resolution | INFO to DEBUG |
| `control/middleware.py` | inactive selector normal central/tenant route diagnostics | INFO to DEBUG |
| `control/middleware.py` | central guard expected redirect decision | INFO to DEBUG |
| `control/views_auth.py` | expected multiple tenant candidate decision | INFO to DEBUG |
| `control/views_auth.py` | expected central route without tenant membership | INFO to DEBUG |
| `control/views_auth.py` | successful post-login central route | INFO to DEBUG |
| `control/views_auth.py` | successful post-login tenant route | INFO to DEBUG |

## 6. Diagnostics Kept Visible

- Tenant connection unavailable warnings were kept unchanged.
- Router unavailable or unregistered route target warnings were kept unchanged.
- Tenant connection verification/configuration warnings were kept unchanged.
- Authentication lookup or eligibility failure warnings were kept unchanged.
- Post-login tenant connection unavailable warnings were kept unchanged.
- Authorization denial warnings were kept unchanged.
- Failure, fail-closed, and security-relevant diagnostics remain visible.

## 7. Test Update

- `control/test_tenant_connection_registration.py` was updated only for the directly affected normal-route diagnostic assertion.
- The assertion changed from `logger.info.assert_called_with(...)` to `logger.debug.assert_called_with(...)`.
- Routing, session, status, redirect, tenant connection registration, and fail-closed assertions were not intentionally changed.
- No test was deleted or weakened.

## 8. Verification Result

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
- No browser smoke was performed for this log-level-only implementation.
- No unexpected traceback or test failure was observed.

## 9. Behavior Preservation

- No routing condition was intentionally changed.
- No redirect target was intentionally changed.
- No session key or session mutation was intentionally changed.
- No tenant candidate filtering or selection validation was intentionally changed.
- No tenant connection registration or verification behavior was intentionally changed.
- No middleware order was changed.
- No router behavior was changed.
- No authentication behavior was changed.
- No authorization behavior was changed.
- No DB schema or data behavior was changed.
- No S3 or upload behavior was changed.

## 10. Deferred Items

- central dashboard medium-risk log cleanup
- inactive selector diagnostic removal or legacy class cleanup
- unrelated test-only diagnostic cleanup
- W342 model warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups
- broad AdminKit-derived template cleanup

## 11. Safety Notes

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

## 12. Conclusion

- Fixed route diagnostic level adjustment implementation is complete.
- Normal successful route diagnostics are now DEBUG-level.
- Failure, fail-closed, and security-relevant diagnostics remain visible.
- Control route regression tests passed.
