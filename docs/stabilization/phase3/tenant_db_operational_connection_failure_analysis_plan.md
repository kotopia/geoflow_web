# Tenant DB Operational Connection Failure Analysis Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: d627bd7 phase3: document post-repair readonly manual smoke result
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- Connection metadata repair succeeded.
- Post-repair selectable candidate count is 8.
- Login passed.
- Multiple-candidate tenant selection passed.
- Tenant route loading passed.
- Tenant home loading passed.
- Contracts list loading failed.
- The sanitized failure category is tenant database operational connection failure.
- Connection registration error was not observed.
- `ConnectionDoesNotExist` was not observed.
- The failure is after tenant selection and before contracts list data loading.

## 3. Purpose

- Define a safe read-only analysis plan for tenant database operational connection failure.
- Separate metadata registration success from actual tenant database connectivity failure.
- Avoid printing secrets, raw identifiers, hostnames, database names, aliases, or raw exceptions.
- Do not perform analysis in this planning step.

## 4. Candidate Failure Categories

| category | meaning |
|---|---|
| network_unreachable | tenant database host or port cannot be reached |
| firewall_or_security_group_block | network route exists but access is blocked |
| database_server_unavailable | server endpoint is reachable but DB service is not available |
| database_name_invalid_or_missing | configured database does not exist or is unavailable |
| credential_invalid | database user or password is rejected |
| insufficient_privilege | connection succeeds but required schema/table access fails |
| ssl_or_connection_option_mismatch | connection requires different SSL or connection options |
| timeout | connection attempt does not complete within expected time |
| unknown_operational_error | sanitized category when exact cause cannot be safely classified |

## 5. Future Read-only Diagnostic Scope

Allowed future diagnostics after separate approval:

- Check sanitized central metadata completeness counts.
- Check whether the selected repaired candidate belongs to the expected selectable category.
- Perform a sanitized tenant DB connection test with a short timeout.
- If connection succeeds, run only a minimal read-only verification such as `SELECT 1`.
- If safe, check whether required schemas or tables are accessible using count or pass-fail only.
- Record only sanitized categories and pass-fail outcomes.

Not allowed:

- DB write.
- Migration.
- Tenant provisioning.
- Credential printing.
- Hostname printing.
- Database name printing.
- Alias printing.
- Raw traceback printing.
- Broad schema dump.
- Broad table scan.
- Browser smoke in the diagnostic step.
- Endpoint smoke in the diagnostic step.

## 6. Future Diagnostic Output Rules

Allowed output:

| check | allowed output |
|---|---|
| metadata_complete | yes/no |
| target_count | count |
| connection_attempt_result | pass/fail |
| sanitized_failure_category | category only |
| select_1_result | pass/fail/not_tested |
| required_schema_access | pass/fail/not_tested |
| required_table_access | pass/fail/not_tested |
| credential_rejected | yes/no/unknown |
| network_reachable | yes/no/unknown |
| timeout_observed | yes/no |
| repair_needed | yes/no/unknown |

Prohibited output:

- real DB host
- real DB name
- real DB user
- real DB password
- real tenant alias
- connection alias
- group name
- group UUID
- user email
- session value
- connection string
- raw exception message
- raw traceback
- local-only label
- raw identifier

## 7. Future Diagnostic Sequence

1. Confirm working tree is clean.
2. Confirm no forbidden files exist.
3. Run sanitized central metadata precheck.
4. Select the target internally without printing raw identifiers.
5. Attempt tenant DB connection with short timeout.
6. Classify failure using sanitized category only.
7. If connection succeeds, run minimal read-only verification only.
8. Do not run migrations.
9. Do not modify central DB or tenant DB.
10. Do not run browser smoke in the same step.
11. Document sanitized diagnostic result.

## 8. Decision Rules After Future Diagnostic

- If network is unreachable, check infrastructure or security group outside application code.
- If credentials are rejected, prepare a secure local credential correction plan.
- If database name is invalid, prepare a metadata correction plan.
- If connection succeeds but table or schema access fails, prepare a tenant permission or schema analysis plan.
- If diagnostic passes, rerun a separately scoped read-only manual smoke.
- Do not combine diagnosis, repair, and browser smoke in one step.

## 9. Out of Scope

- Running the diagnostic in this planning step.
- DB SELECT in this planning step.
- DB write in this planning step.
- Tenant DB connection attempt in this planning step.
- Browser smoke in this planning step.
- Endpoint smoke in this planning step.
- Migration.
- Tenant provisioning.
- S3 or presigned URL work.
- Inactive membership activation.
- Group activation.
- Broad template cleanup.
- W342 warning cleanup.

## 10. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No database connection test was performed.
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

## 11. Conclusion

- The next step should be a separately approved read-only tenant DB operational connection diagnostic.
- The diagnostic must classify the failure without exposing hostnames, credentials, aliases, database names, or raw exceptions.
- No repair should be performed until the sanitized failure category is known.
