# Selected Tenant DB Connection Option Analysis Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: b987b58 phase3: document selected tenant db local credential verification
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- Post-repair metadata verification passed.
- The selected tenant target was confirmed locally by the user.
- The user reports direct tenant DB connection succeeds.
- A transient application-style connection test failed.
- The latest sanitized category was `unknown_operational_error`.
- `credential_rejected` was `no`.
- `timeout_observed` was `no`.
- No central DB write was performed.
- No tenant DB write was performed.

## 3. Purpose

- Define a safe read-only plan to compare direct DB connection behavior with application-style connection behavior.
- Focus on SSL, authentication, driver, and connection option differences.
- Do not retry DB user or password updates in this step.
- Do not create a new tenant in this step.
- Do not perform DB connection testing in this planning step.

## 4. Current Diagnostic Summary

| check | result |
|---|---|
| selected_target_count | 1 |
| metadata_complete | yes |
| user_confirmed_target_matches_direct_db | yes |
| transient_connection_attempt_result | fail |
| select_1_result | not_tested |
| credential_rejected | no |
| network_reachable | unknown |
| timeout_observed | no |
| sanitized_failure_category | unknown_operational_error |
| central_db_write_performed | 0 |
| tenant_db_write_performed | 0 |

## 5. Candidate Difference Categories

| category | meaning |
|---|---|
| sslmode_difference | Direct tool and application use different SSL modes. |
| ssl_certificate_requirement | Server requires a certificate or CA option not supplied by the application. |
| driver_option_difference | DB tool and Django or psycopg use different connection options. |
| auth_method_difference | Authentication method behaves differently by client or route. |
| target_option_mismatch | The target label matches, but hidden connection parameters differ. |
| password_encoding_issue | Entered password contains characters handled differently by the client or input path. |
| connection_timeout_option | Timeout options differ between the direct tool and application test. |
| search_path_or_schema_option | Connection succeeds elsewhere, but the application requires schema or search path options. |
| unknown_option_gap | Sanitized fallback when the exact option difference is not yet known. |

## 6. Future Read-only Analysis Scope

Allowed future checks after separate approval:

- Compare sanitized option categories between the direct connection method and application-style connection method.
- Confirm whether SSL is required using local-only tools.
- Run tenant DB connection tests with controlled SSL mode variants using local-only credentials.
- Run `SELECT 1` only if connection succeeds.
- Record only pass or fail and sanitized option categories.
- Do not print connection strings or raw exceptions.

Not allowed:

- Central DB write.
- Tenant DB write.
- Credential update.
- Tenant DB account creation.
- Tenant DB permission change.
- Migration.
- Tenant provisioning.
- Endpoint call.
- Browser smoke.
- S3 or presigned URL work.
- Recording raw values or raw identifiers.

## 7. Future Output Rules

Allowed output:

| check | allowed output |
|---|---|
| direct_connection_reference | pass/fail/user_reported_pass |
| app_style_default_connection | pass/fail/not_tested |
| ssl_disable_result | pass/fail/not_tested |
| ssl_prefer_result | pass/fail/not_tested |
| ssl_require_result | pass/fail/not_tested |
| select_1_result | pass/fail/not_tested |
| suspected_option_category | category |
| credential_rejected | yes/no/unknown |
| timeout_observed | yes/no |
| next_action | category |

Prohibited output:

- Real DB host.
- Real DB name.
- Real DB user.
- Real DB password.
- Real tenant alias.
- Connection alias.
- Group name.
- Group UUID.
- User email.
- Session value.
- Connection string.
- Raw exception message.
- Raw traceback.
- Local-only label.
- Raw identifier.

## 8. Future Decision Rules

- If one SSL mode succeeds, prepare a connection option metadata or code analysis plan.
- If all SSL variants fail but the direct DB tool succeeds, compare the client driver and authentication method locally.
- If credential rejection reappears, stop and verify the credential source outside GPT.
- If connection succeeds and `SELECT 1` passes, prepare a separate central metadata update or application option plan only if needed.
- If connection succeeds with current metadata but the browser still fails later, prepare a separate read-only manual smoke retry plan.
- Do not create a new tenant until the existing target connection option gap is understood.

## 9. Out of Scope

- Running diagnostics in this planning step.
- DB SELECT in this planning step.
- DB write in this planning step.
- Tenant DB connection test in this planning step.
- Browser smoke in this planning step.
- Endpoint smoke in this planning step.
- Migration.
- Tenant provisioning.
- S3 or presigned URL work.
- Inactive membership activation.
- Group activation.
- W342 warning cleanup.
- Broad template cleanup.

## 10. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No tenant DB connection test was performed.
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

- The next step should be a separately approved read-only connection option diagnostic.
- The focus is SSL, authentication, driver, and connection option differences.
- DB credential update should not be retried until the option gap is understood.
- A new tenant should not be created yet.
