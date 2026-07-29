# Non-selectable Tenant Metadata Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 0617a47 phase2: analyze w342 model warning
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze why some groups are excluded from selectable tenant candidates after login.
- Identify code-level exclusion conditions without reading real database values.
- Document metadata checks that may be needed later.
- Do not change code, tests, settings, templates, static files, migrations, endpoints, S3, or database state in this step.

## 3. Background

- Only selectable tenant candidates are stored in session and rendered on the group-selection page.
- Non-selectable candidates are excluded from session and UI.
- If there are zero selectable candidates, the user falls back to the central route.
- If there is one selectable candidate, the user is routed directly to that tenant.
- If there are two or more selectable candidates, the group-selection page is shown.
- Therefore, a user can belong to multiple groups but still route directly to one tenant if only one candidate remains selectable after filtering.
- This is expected behavior under the current Option A policy.

## 4. Files Reviewed

| file | role | treatment |
|---|---|---|
| `control/views_auth.py` | builds candidates after login and decides route behavior | read-only |
| `control/views_groups.py` | renders and validates selectable session candidates | read-only |
| `control/tenant_connections.py` | prepares tenant database connection settings | read-only |
| `control/middleware.py` | applies tenant route safety and fail-closed behavior | read-only |
| `control/test_group_search_login_fix.py` | regression coverage for candidate filtering and group selection | read-only |
| `control/test_tenant_connection_registration.py` | regression coverage for tenant connection and routing safety | read-only |
| stabilization documents | previous selectable-candidate policy and diagnosis references | read-only |

No database values were queried or printed.

## 5. Selectable Candidate Conditions

A candidate must satisfy the code-level metadata requirements below.

1. The candidate object must have the expected structure.
2. The user-group membership must exist.
3. The membership must belong to the candidate group.
4. The membership must be active.
5. The group object must exist.
6. The group must be active.
7. A group database configuration must exist.
8. Candidate display metadata must be complete enough for safe UI use.
9. Required connection metadata must be complete enough for later tenant routing.
10. The candidate alias and database configuration alias must match.

If candidate lookup itself fails, the safe result is an empty selectable-candidate list.

## 6. Candidate Filtering vs Connection Fail-closed

Metadata filtering and tenant connection validation are related but separate stages.

- Candidate filtering happens during login candidate preparation.
- Connection preparation happens when entering or selecting a tenant.
- A candidate can pass metadata filtering but still fail later if the connection cannot be registered or verified.
- Later connection failure is handled by fail-closed behavior.
- Fail-closed behavior clears unsafe tenant state and routes back to the central route.

Operationally, both stages can make a tenant unavailable to the user, but they should be diagnosed separately.

## 7. Possible Exclusion Causes

| cause | explanation | user-visible result | future check |
|---|---|---|---|
| malformed candidate metadata | candidate lacks required shape or safe display fields | may not appear on selection page | metadata review |
| missing user-group membership | candidate has no matching membership | may not appear on selection page | metadata review |
| inactive membership | membership exists but is inactive | may not appear on selection page | metadata review |
| missing group | group object is unavailable | may not appear on selection page | metadata review |
| inactive group | group exists but is inactive | may not appear on selection page | metadata review |
| missing group database config | group has no tenant database configuration | may not appear on selection page | configuration review |
| missing required connection metadata | required connection fields are incomplete | may not appear on selection page | configuration repair |
| candidate alias mismatch | candidate alias does not match configuration alias | may not appear on selection page | alias consistency review |
| metadata lookup failure | central metadata lookup fails safely | central fallback may occur | read-only diagnosis |
| connection registration failure | metadata passes but tenant connection setup fails later | tenant entry is blocked and central fallback may occur | separate connection diagnosis |

No real aliases, group identifiers, database hostnames, database names, passwords, session values, or raw identifiers were recorded.

## 8. Current Behavior Interpretation

- Multiple group membership does not guarantee that the group-selection page will be shown.
- The group-selection page appears only when two or more candidates remain selectable after filtering.
- Direct tenant routing with one selectable candidate is expected behavior.
- Central fallback with zero selectable candidates is expected fail-safe behavior.
- Excluding non-selectable candidates avoids exposing incomplete or unsafe tenant choices.
- The current behavior is primarily a metadata completeness and consistency issue, not necessarily a code defect.

## 9. Risk Assessment

| area | impact |
|---|---|
| login behavior | no impact because no code was changed |
| group-selection page | no impact because no code was changed |
| tenant routing | no impact because no code was changed |
| database connection | no impact because no database operation was performed |
| permissions | no impact because no authorization code was changed |
| data | no impact because no database query or write was performed |
| security | sensitive values were not recorded |

## 10. Future Review Direction

A future separately approved review may check:

- number of groups linked to a specific user
- active status of each user-group membership
- active status of each group
- existence of each group database configuration
- completeness of required connection metadata
- consistency between candidate alias and configuration alias
- whether connection registration succeeds
- whether metadata changed between login filtering and tenant entry

Future review rules:

- database read requires separate approval
- database write requires separate approval
- only sanitized counts and boolean results should be recorded
- real aliases, identifiers, hostnames, passwords, and session values must not be printed

## 11. Recommendation

- Do not change code for this item now.
- The current exclusion behavior is a safe policy.
- Most issues are likely caused by incomplete or inconsistent metadata rather than login-routing code.
- Actual repair would be a database metadata task and must be separated from the current stabilization cleanup.
- Keep this item documented and deferred until a controlled metadata review is explicitly approved.

## 12. Deferred Items

- real database metadata read
- real database metadata repair
- group-selection policy change
- candidate-exclusion policy change
- detailed connection-failure logging
- W342 warning fix
- Level 2 controlled write/upload smoke
- broad template cleanup

## 13. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No database write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No real user email, group name, group identifier, tenant alias, connection alias, database host, database password, session value, contract identifier, event identifier, attachment identifier, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 14. Conclusion

- Non-selectable tenant behavior is explained by candidate metadata filtering and later fail-closed connection validation.
- Direct tenant routing is expected when only one selectable candidate remains.
- Missing or inconsistent metadata is the main future review target.
- No implementation is recommended in this step.
