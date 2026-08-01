# Selected Tenant Database Name and Credential Metadata Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 49863e3 phase3: document selected tenant database name correction rollback
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- The selected tenant database name-only correction was attempted in a transaction.
- The temporary database name update affected exactly 1 row.
- Host, port, DB user, DB password, and alias were not updated.
- Post-update tenant DB connection failed with sanitized category `credential_invalid`.
- The transaction was rolled back.
- Therefore, no database name metadata change was committed.
- The database name input was not classified as invalid.
- The remaining likely issue is that the corrected database name must be paired with the pgAdmin-confirmed DB user and DB password.

## 3. Purpose

- Define a safe correction plan for the selected tenant central metadata.
- Future correction should update the database name, DB user, and DB password together for exactly 1 selected row.
- Host, port, alias, group code, and group name must not be changed.
- Tenant DB schema, data, accounts, and permissions must not be changed.
- The correction must be verified by a read-only tenant DB connection and `SELECT 1` before commit.

## 4. Current Sanitized Finding

| check | result |
|---|---|
| database_name_only_update_rows | 1 |
| database_name_only_transaction_committed | 0 |
| database_name_only_transaction_rolled_back | 1 |
| database_name_only_connection_result | fail |
| database_name_only_select_1_result | not_tested |
| database_name_only_failure_category | credential_invalid |
| current_primary_repair_candidate | database_name_and_credential_metadata_combination |

## 5. Future Correction Scope

Allowed after separate user approval:

- Central DB SELECT to locate selectable candidates.
- Local-only target number selection.
- Local-only confirmation that the selected target matches the pgAdmin connection target.
- Local-only input of the correct PostgreSQL database name.
- Local-only input of the correct DB user.
- Local-only hidden input of the correct DB password.
- Central DB UPDATE of the database name, DB user, and DB password only for exactly 1 selected `group_db_config` row.
- Read-only tenant DB connection verification after the temporary update.
- `SELECT 1` only if the connection succeeds.
- Transaction commit only if the connection and `SELECT 1` both pass.
- Transaction rollback if the connection or `SELECT 1` fails.

Not allowed:

- Updating the host.
- Updating the port.
- Updating the alias.
- Updating the group code or group name.
- Creating a tenant DB.
- Creating a tenant DB account.
- Granting tenant DB permissions.
- Running migration.
- Running endpoint or browser smoke.
- Running tenant provisioning.
- Modifying code or tests.
- Creating a new tenant.

## 6. Future Success Criteria

| check | required result |
|---|---|
| selected_target_count | 1 |
| metadata_complete_before_update | yes |
| database_name_input_received | yes |
| db_user_input_received | yes |
| db_password_input_received | yes |
| database_name_update_rows | 1 |
| db_user_update_rows | 1 |
| db_password_update_rows | 1 |
| host_updated | 0 |
| port_updated | 0 |
| alias_updated | 0 |
| tenant_connection_after_update | pass |
| select_1_after_update | pass |
| transaction_committed | 1 |
| transaction_rolled_back | 0 |
| repair_success | 1 |

## 7. Future Rollback Criteria

Rollback if any of the following occurs:

- `selected_target_count` is not 1.
- Any required local input is empty.
- Any update affects anything other than 1 selected row.
- Host changes.
- Port changes.
- Alias changes.
- Group code or group name changes.
- Post-update tenant connection fails.
- Post-update `SELECT 1` fails.
- A timeout occurs.
- An unknown operational error occurs.
- Any prohibited field is changed.

## 8. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed in this planning step.
- No database write was performed in this planning step.
- No tenant DB connection test was performed in this planning step.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No legacy code was executed.
- No new tenant was created.
- No S3 access was performed.
- No presigned URL was generated.
- No secrets were recorded.
- No local-only labels were recorded.
- No raw identifiers were recorded.
- `.env` contents were not printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 9. Conclusion

- The next repair candidate is a combined selected-row correction of the database name, DB user, and DB password.
- The correction requires separate user approval.
- The correction must be limited to exactly 1 selected row.
- The transaction must commit only if the read-only tenant DB connection and `SELECT 1` both pass.
- Host, port, alias, group code, group name, tenant DB schema, tenant DB accounts, and tenant DB permissions must remain unchanged.
