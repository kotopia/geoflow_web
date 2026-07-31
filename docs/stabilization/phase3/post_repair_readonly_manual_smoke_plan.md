# Post-repair Read-only Manual Smoke Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: a98fd34 phase3: verify post-repair selectable tenant metadata
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a read-only manual smoke plan after connection metadata repair.
- The post-repair metadata review verified 8 selectable candidates.
- The incomplete connection metadata category is resolved.
- The remaining 6 non-selectable candidates are deferred inactive membership rows.
- This document does not execute smoke testing.

## 3. Current Verified Metadata State

| item | count |
|---|---:|
| candidate relationships | 14 |
| selectable candidates | 8 |
| non-selectable candidates | 6 |
| incomplete connection metadata | 0 |
| missing DB user | 0 |
| missing DB password | 0 |
| alias mismatch | 0 |
| inactive membership deferred | 6 |

## 4. Smoke Scope

The future manual smoke should verify read-only navigation only.

Allowed future checks after separate approval:

- login page loads
- central login succeeds with an approved test account
- tenant selection behavior matches selectable candidate count
- group selection page appears when multiple selectable candidates exist
- selecting a candidate routes to the tenant context
- tenant home page loads
- contracts list loads
- contract detail loads if a safe existing item is available
- event list or modal loads only if it is part of read-only navigation

Not allowed in this smoke:

- create
- update
- delete
- upload
- download mutation
- presigned upload
- S3 write
- tenant provisioning
- migration
- inactive membership activation
- group activation
- DB metadata repair
- broad endpoint scan
- broad browser crawl

## 5. Expected Behavior

- The repaired candidates should no longer fail due to incomplete connection metadata.
- A user with multiple selectable candidates should see the group selection flow.
- A user with one selectable candidate should be routed directly to that tenant.
- A user with zero selectable candidates should remain in central fallback behavior.
- Deferred inactive membership rows should not appear as selectable choices.
- No `ConnectionDoesNotExist` or tenant alias registration error should appear for repaired candidates.

## 6. Future Smoke Safety Rules

- Use only a known approved test account or operator account.
- Do not paste credentials into GPT.
- Do not record emails, group names, aliases, UUIDs, DB names, hosts, or session values.
- Do not perform write actions.
- Do not click upload/delete/save/create buttons.
- Do not run migrations.
- Do not call tenant provisioning.
- Do not inspect or print `.env`.
- Record only sanitized status codes, page categories, and pass/fail outcomes.
- If an automatic page load triggers existing read-only asset requests, record only the sanitized category.

## 7. Planned Future Result Document

Future result document path:

- `docs/stabilization/phase3/post_repair_readonly_manual_smoke_result.md`

The future result should include only:

| check | result |
|---|---|
| login_page_load | pass/fail |
| login_result | pass/fail |
| tenant_selection_behavior | pass/fail |
| tenant_route_load | pass/fail |
| tenant_home_load | pass/fail |
| contracts_list_load | pass/fail |
| contract_detail_load | pass/fail/not_tested |
| event_readonly_load | pass/fail/not_tested |
| write_actions_performed | 0 |
| upload_actions_performed | 0 |
| db_write_performed | 0 |
| migration_performed | 0 |
| secrets_recorded | 0 |
| raw_identifiers_recorded | 0 |

## 8. Out of Scope

- Executing the smoke test in this planning step.
- Endpoint call in this planning step.
- Browser smoke in this planning step.
- DB SELECT or DB write in this planning step.
- Migration.
- S3 or presigned URL work.
- Upload, create, update, delete.
- Inactive membership repair.
- Group activation.
- W342 warning cleanup.
- Broad template cleanup.

## 9. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No database write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No secrets were recorded.
- No local-only labels were recorded.
- No raw identifiers were recorded.
- `.env` contents were not printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 10. Conclusion

- The next optional step is a separately approved read-only manual smoke execution.
- The smoke should verify routing and read-only page loading after the metadata repair.
- No write, upload, migration, S3, or provisioning action should be included.
