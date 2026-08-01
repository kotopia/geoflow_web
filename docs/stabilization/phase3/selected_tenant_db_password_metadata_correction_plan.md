# Selected Tenant DB Password Metadata Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 6a21d51 phase3: document selected tenant target reidentification
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- The previous combined metadata correction attempt was rolled back because the selected local target was incorrect.
- A read-only target re-identification diagnostic was then performed.
- Exactly one candidate matched the pgAdmin comparison input across host, port, database name, and DB user.
- The selected target was re-identified successfully.
- No database metadata was updated during re-identification.
- No tenant DB connection test was performed during re-identification.
- Since host, port, database name, and DB user matched, the remaining likely metadata issue is the DB password.

## 3. Purpose

- Define a safe correction plan for the selected target DB password metadata only.
- Future correction must update the DB password only for exactly 1 re-identified selected row.
- Host, port, database name, DB user, alias, group code, and group name must not be changed.
- Tenant DB schema, data, accounts, and permissions must not be changed.
- The correction must be verified by a read-only tenant DB connection and `SELECT 1` before commit.

## 4. Current Sanitized Finding

| check | result |
|---|---|
| selected_target_reidentified | yes |
| all_four_exact_match_count | 1 |
| selected_target_host_match | yes |
| selected_target_port_match | yes |
| selected_target_database_name_match | yes |
| selected_target_db_user_match | yes |
| selected_target_all_four_match | yes |
| current_primary_repair_candidate | db_password_metadata_only |

## 5. Future Correction Scope

Allowed after separate user approval:

- Central DB SELECT to locate selectable candidates.
- Local-only target number selection.
- Local-only confirmation that the selected target is the re-identified target.
- Local-only hidden input of the correct DB password.
- Central DB UPDATE of the DB password only for exactly 1 selected `group_db_config` row.
- Preserve the existing host, port, database name, DB user, alias, group code, and group name.
- Read-only tenant DB connection verification after the temporary update.
- `SELECT 1` only if the connection succeeds.
- Transaction commit only if the connection and `SELECT 1` both pass.
- Transaction rollback if the connection or `SELECT 1` fails.

Not allowed:

- Updating the host.
- Updating the port.
- Updating the database name.
- Updating the DB user.
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
| db_password_input_received | yes |
| db_password_update_rows | 1 |
| host_updated | 0 |
| port_updated | 0 |
| database_name_updated | 0 |
| db_user_updated | 0 |
| alias_updated | 0 |
| tenant_connection_after_update | pass |
| select_1_after_update | pass |
| transaction_committed | 1 |
| transaction_rolled_back | 0 |
| repair_success | 1 |

## 7. Future Rollback Criteria

Rollback if any of the following occurs:

- `selected_target_count` is not 1.
- DB password input is empty.
- The DB password update affects anything other than 1 selected row.
- Host changes.
- Port changes.
- Database name changes.
- DB user changes.
- Alias changes.
- Group code or group name changes.
- The post-update tenant connection fails.
- The post-update `SELECT 1` fails.
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

- The next repair candidate is selected-target DB password metadata only.
- The correction requires separate user approval.
- The correction must be limited to exactly 1 re-identified selected row.
- The transaction must commit only if the read-only tenant DB connection and `SELECT 1` both pass.
- Host, port, database name, DB user, alias, group code, group name, tenant DB schema, tenant DB accounts, and tenant DB permissions must remain unchanged.
