# Group Selection Selectable Candidate Filtering Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 12b9f5f phase2: design selectable tenant candidate filtering
- Implementation commit: e7d93e7 phase2: filter selectable tenant candidates
- Working tree expected state: clean

## 2. Purpose

- Read-only diagnosis showed that some group-selection candidates were not actually connectable.
- The helper correctly failed closed for incomplete tenant metadata.
- The UX problem was that non-selectable candidates were still shown as selectable choices.
- This implementation filters candidates before they enter session `tenant_candidates`.

## 3. Modified Files

- control/views_auth.py
- control/test_group_search_login_fix.py

`control/views_groups.py` was not modified because it already renders and validates only session candidates. No template or static file was changed.

## 4. Implementation Summary

- Login candidate resolution now keeps only selectable candidates.
- Active membership is required.
- An active group is required.
- Group DB config is required.
- Connection alias metadata is required.
- DB name metadata is required.
- DB host metadata is required.
- DB port metadata is required.
- DB user metadata is required.
- DB password metadata is required.
- The candidate alias must match the config alias.
- Required display fields must be safe to render.
- Only filtered candidates are stored in session `tenant_candidates`.
- `group_search` continues to render only session candidates.
- `group_select` retains session-based HTTP 403 validation.
- URL or request identifiers are not trusted as an authorization source.
- Tenant DB queries, credential validation, and network validation are not performed.
- The tenant connection helper remains strict.
- `EnsureTenantAliasMiddleware` remains pass-through.
- No static alias was added to `settings.py`.

## 5. Zero Selectable Candidate Behavior

- Broken candidates are not stored in session.
- Broken candidates are not rendered as selectable choices.
- A tenant route is not set.
- The central alias and central flow are used safely.
- No template change was required.
- No redirect loop was introduced.
- No missing DB field, alias, DB name, host, password, UUID, or raw identifier is exposed to the user.

## 6. Test Result

| test command | result |
|---|---|
| `python manage.py test control.test_group_search_login_fix` | 16 tests OK |
| `python manage.py test control.test_tenant_connection_registration` | 29 tests OK |
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | 12 tests OK |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | 7 tests OK |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | 9 tests OK |
| `python manage.py test geoflow_ops.test_contract_write_permission` | 6 tests OK |
| `python manage.py test geoflow_ops.test_event_write_permission` | 9 tests OK |
| `python manage.py check` | passed with existing W342 warning only |
| `python -m py_compile control/views_auth.py control/views_groups.py control/test_group_search_login_fix.py` | passed |

- The only existing check warning was `catalog.CategoryParent.child` W342.
- Unrelated attachment-delete test diagnostic output remains pre-existing and outside this scope.
- `git diff --check` passed.
- No real DB connection, query, write, or migration was performed.

## 7. Not Performed

- No browser smoke was performed.
- No real login endpoint was called.
- No real group-selection endpoint was called.
- No real contracts endpoint was called.
- No event, upload, or delete endpoint was called.
- No S3 access was performed.
- No presigned URL was generated.
- No DB migration was performed.
- No schema change was performed.
- No tenant provisioning was performed.
- No permission provisioning was performed.
- No `settings.py` change was made.
- No template or static file was changed.

## 8. Follow-up Recommendation

- Commit this implementation result document first.
- The next step should be an explicitly approved browser smoke.
- Browser smoke must use:
  - all development-server processes stopped
  - one fresh `--noreload` development server from current clean HEAD
  - logout or a fresh browser session
  - `/login/` as the starting point
- Browser smoke should verify:
  - multi-membership login shows only selectable tenant candidates
  - non-selectable groups are not shown as selectable choices
  - selecting the visible valid candidate reaches tenant home or tenant workflow with HTTP 200
  - `ConnectionDoesNotExist` is not observed
  - `ImproperlyConfigured` is not observed
  - single-tenant login still reaches tenant home with HTTP 200
- Smoke documentation must remain sanitized.

## 9. Safety Notes

- No code was modified by this documentation task.
- No DB write was performed by this documentation task.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated or printed.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext was printed.
- No decrypted personal data was printed.
- No user email, name, or phone number was recorded.
- No UUID, group identifier, group name, tenant alias, candidate list, or raw identifier was recorded.
- No DB host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
