# Post-repair Read-only Manual Smoke Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 120da14 phase3: plan post-repair readonly manual smoke
- Working tree expected state before smoke: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Scope

- Read-only manual smoke only.
- Browser and manual navigation were allowed.
- No create, update, delete, upload, or save action was performed.
- No database write was performed.
- No migration was performed.
- No tenant provisioning was performed.
- No S3 write was performed.
- No presigned upload was generated.
- No code or test was changed.

## 3. Metadata Context

| item | count |
|---|---:|
| selectable candidates after repair | 8 |
| non-selectable candidates after repair | 6 |
| incomplete connection metadata after repair | 0 |
| inactive membership deferred | 6 |

## 4. Smoke Result

| check | result |
|---|---|
| login_page_load | pass |
| login_result | pass |
| tenant_selection_behavior | pass |
| group_selection_page_for_multiple_candidates | pass |
| tenant_route_load | pass |
| tenant_home_load | pass |
| contracts_list_load | fail |
| contract_detail_load | not_tested |
| event_readonly_load | not_tested |
| connection_registration_error_observed | no |
| connection_does_not_exist_observed | no |
| write_actions_performed | 0 |
| upload_actions_performed | 0 |
| db_write_performed | 0 |
| migration_performed | 0 |
| secrets_recorded | 0 |
| raw_identifiers_recorded | 0 |

## 5. Interpretation

- The login page loaded and login completed successfully.
- The multiple-candidate group selection page appeared as expected.
- Candidate selection entered the tenant context and the tenant page loaded.
- The contracts list did not load because a tenant database connection failure occurred.
- The observed failure category was an operational database connection failure, not a connection registration or missing-alias failure.
- `ConnectionDoesNotExist` and `ImproperlyConfigured` were not observed.
- Contract detail and event read-only navigation were not tested after the contracts list failure.
- No write, upload, migration, S3, provisioning, or presigned upload action was performed.
- No credentials, aliases, database names, hosts, session values, labels, or raw identifiers were recorded.

## 6. Safety Notes

- No code was modified.
- No test was modified.
- No database write was performed.
- No migration was performed.
- No tenant provisioning was performed.
- No endpoint write action was performed.
- No create, update, delete, or save action was performed.
- No upload action was performed.
- No S3 access was performed.
- No presigned upload was generated.
- No inactive membership was activated.
- No group was activated.
- No secrets were printed.
- No secrets were recorded.
- No local-only labels were recorded.
- No raw identifiers were recorded.
- `.env` contents were not printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 7. Conclusion

- The post-repair read-only manual smoke failed at the contracts list stage.
- The sanitized failure category is tenant database operational connection failure.
- Login, group selection, tenant routing, and tenant page loading passed before the failure.
- A separate read-only connection failure analysis is required before another browser smoke.
