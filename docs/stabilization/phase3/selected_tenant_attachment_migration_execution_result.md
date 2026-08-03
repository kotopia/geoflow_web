# Selected Tenant Attachment Migration Execution Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 4bb8737 phase3: plan selected tenant attachment migration execution
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Record the guarded selected-tenant-only attachment migration execution.
- Confirm that only the expected `webgisapp` 0015 through 0018 range was applied.
- Confirm the expected tables, columns, indexes, and constraints after execution.
- Record only sanitized counts and pass or fail states.

## 3. Execution Authorization and Scope

- The user explicitly approved migration execution for exactly one selected tenant.
- Selected tenant prechecks had passed.
- Backup and restore readiness had been confirmed.
- The responsible recovery operator had been confirmed.
- Target application: `webgisapp`.
- Target migration: 0018.
- Expected applied range: 0015, 0016, 0017, and 0018.
- Central, representative, and all-tenant migration targets were prohibited.
- A guarded local-only wrapper was used instead of a direct CLI or all-tenant command.

## 4. Guarded Pre-execution Result

| check | result |
|---|---|
| selected_target_count | 1 |
| precheck_pass | yes |
| migration_plan_expected | yes |
| selected connection registration | pass |
| router selected-tenant scope | pass |
| central scope denied | yes |
| representative scope denied | yes |
| target conflicts | none |

- The migration plan contained exactly the expected four forward migrations.
- Execution did not proceed until the selected connection, router scope, migration state, table state, and conflict checks passed.
- Preliminary wrapper-launch issues occurred before migration selection or execution and did not perform a database operation.
- The corrected guarded wrapper completed the approved execution.

## 5. Sanitized Execution Result

| check | result |
|---|---|
| execution_attempted | yes |
| execution_success | yes |
| selected_target_count | 1 |
| applied_migrations_count | 4 |
| applied_expected_range | yes |
| target_tables_present | yes |
| expected_columns_present | yes |
| expected_indexes_present | yes |
| expected_constraints_present | yes |
| tenant_connection_postcheck | pass |
| select_1_postcheck | pass |
| postcheck_pass | yes |
| sanitized_failure_category | none |
| missing_ops_attachments_table_resolved_possible | yes |

## 6. Applied Migration Result

- Migration 0015 was applied.
- Migration 0016 was applied.
- Migration 0017 was applied.
- Migration 0018 was applied.
- Exactly four expected migration records were present after execution.
- No unexpected migration was included in the reviewed plan or expected result range.
- Predecessor migrations were not rerun.

## 7. Schema Postcheck Result

- The attachment table is present.
- The process-event table is present.
- The process-event-attachment table is present.
- Expected attachment and process-event columns are present.
- Expected explicit indexes are present.
- Expected foreign keys and the explicit unique constraint are present.
- The prior missing attachment table condition is structurally resolved and ready for application-level confirmation.

## 8. Connection Postcheck Result

- The selected tenant connection passed after migration execution.
- Read-only `SELECT 1` passed after migration execution.
- No connection regression was detected.
- The postcheck did not insert, update, or delete tenant business data.

## 9. Scope Protection Result

- Only one selected tenant was targeted.
- No central database migration was run.
- No representative tenant migration was run.
- No all-tenant migration command was run.
- No fake migration option was used.
- Migration history was not edited manually.
- No table was created, altered, or dropped manually outside the approved Django migration sequence.

## 10. Interpretation

- The selected tenant attachment and process-event schema rollout succeeded.
- The diagnosed `partial_schema_rollout` condition is repaired for the selected tenant through migration 0018.
- The selected tenant now has the schema objects required by the current managed attachment and process-event models.
- The missing attachment table error category can now be retested at the application level.
- This result does not claim that contract detail browser smoke has already passed after migration.
- This result does not authorize rollout to other tenants.

## 11. Recommended Next Action

- Document this migration execution result before any further database operation.
- Prepare a separately approved narrow read-only browser smoke.
- Verify login, tenant selection, tenant home, contracts list, and contract detail.
- Confirm the previous missing attachment table error is not observed.
- Do not intentionally create, update, delete, upload, download, or invoke S3 workflows during the smoke.
- Keep other unapplied tenants out of scope.
- Any broader tenant rollout requires separate inventory, precheck, backup, approval, and execution documentation.

## 12. Not Performed

- No central database migration
- No representative tenant migration
- No all-tenant migration
- No tenant business-data write
- No fake migration
- No manual migration-history edit
- No manual table DDL
- No code or test change
- No endpoint or browser execution
- No S3 or presigned URL operation
- No git add, commit, or push

## 13. Safety Notes

- The approved schema migration affected one selected tenant only.
- Sensitive connection metadata was not printed or recorded.
- No host, database name, database user, password, alias, snapshot name, instance name, ARN, UUID, tenant label, email, session value, or raw traceback was recorded.
- The wrapper restored its process-local routing setting and removed the dynamic connection registration after execution.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 14. Conclusion

- `execution_attempted`: yes.
- `execution_success`: yes.
- Four expected migrations were applied to one selected tenant.
- The expected migration range, tables, columns, indexes, and constraints passed postcheck.
- Tenant connection and read-only `SELECT 1` passed after execution.
- The sanitized failure category is `none`.
- The next safe step is a separately approved read-only application smoke for contract detail.
