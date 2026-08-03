# Attachment Table Schema Diagnostic Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 5c2377c phase3: plan attachment table schema diagnostic
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Compare attachment and event schema state between the selected tenant and the representative tenant.
- Confirm whether the contract detail failure is caused by connection failure, missing tables, or inconsistent migration records.
- Classify the result without running migrations or changing either database.

## 3. Scope

- Tenant database access was read-only.
- The selected target was chosen through a local-only numbered list.
- Database catalog and migration-history presence checks were performed.
- No business-data rows were read.
- No database write was performed.
- No migration or schema operation was performed.
- No code, endpoint, or browser operation was performed.
- No connection value, credential, identifier, or raw error was recorded.

## 4. Selected Tenant Result

| check | result |
|---|---|
| selected_target_count | 1 |
| selected_connection | pass |
| selected_ops_attachments | no |
| selected_ops_process_events | no |
| selected_ops_process_event_attachments | no |
| selected_webgisapp_0015_record | no |
| selected_webgisapp_0016_record | no |
| selected_webgisapp_0017_record | no |
| selected_webgisapp_0018_record | no |

## 5. Representative Tenant Result

| check | result |
|---|---|
| representative_connection | pass |
| representative_ops_attachments | yes |
| representative_ops_process_events | yes |
| representative_ops_process_event_attachments | yes |
| representative_webgisapp_0015_record | yes |
| representative_webgisapp_0016_record | yes |
| representative_webgisapp_0017_record | yes |
| representative_webgisapp_0018_record | yes |

## 6. Comparison

| item | selected tenant | representative tenant |
|---|---|---|
| read-only connection | pass | pass |
| attachment table | absent | present |
| process event table | absent | present |
| process event attachment table | absent | present |
| migration 0015 record | absent | present |
| migration 0016 record | absent | present |
| migration 0017 record | absent | present |
| migration 0018 record | absent | present |

## 7. Diagnostic Classification

- Primary cross-tenant classification: `partial_schema_rollout`.
- Selected-tenant local condition: `migration_not_applied` for the inspected migration range.
- `migration_record_table_mismatch` was not observed because the selected tenant lacks both the migration records and the corresponding tables.

## 8. Interpretation

- Both tenant connections passed, so the difference is not a tenant connection failure.
- The selected tenant does not contain any of the three inspected attachment or process-event tables.
- The selected tenant also does not record `webgisapp` migrations 0015 through 0018 as applied.
- The representative tenant contains all three tables and all four inspected migration records.
- The evidence supports a schema rollout that reached the representative tenant but not the selected tenant.
- The selected tenant contract detail failure is consistent with the missing attachment table.
- The absence of the related process-event tables shows that the issue is broader than one isolated table.
- No evidence indicates that migrations were recorded without creating their expected tables on the selected tenant.

## 9. Recommended Next Action

- Prepare a separate selected-tenant migration impact and safety review for `webgisapp` migrations 0015 through 0018.
- Inspect the migration files and dependencies statically before authorizing execution.
- Confirm whether any prerequisite migrations, schemas, extensions, or legacy table assumptions apply.
- Determine whether the migration sequence creates only the missing structures or also performs data changes.
- Define backup, precheck, rollback, and post-migration verification requirements.
- Do not run migrations until that review is documented and explicitly approved.
- Do not create the missing tables manually.
- Do not alter migration history manually.

## 10. Not Performed

- No migration execution
- No table creation, alteration, rename, or deletion
- No database write
- No tenant business-data query
- No code or test change
- No endpoint or browser execution
- No S3 or presigned URL operation
- No git add, commit, or push

## 11. Safety Notes

- Database access was read-only.
- Both connections were used only for catalog and migration-history presence checks.
- No database value, credential, alias, tenant label, UUID, email, session value, or raw error was printed or recorded.
- No migration was performed.
- No schema was changed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 12. Conclusion

- The selected tenant is missing the inspected attachment and process-event tables.
- The selected tenant is also missing the corresponding `webgisapp` 0015 through 0018 migration records.
- The representative tenant has the inspected tables and migration records.
- The primary diagnosis is `partial_schema_rollout`, with `migration_not_applied` as the selected-tenant condition.
- A separate migration impact review is required before any repair is authorized.
