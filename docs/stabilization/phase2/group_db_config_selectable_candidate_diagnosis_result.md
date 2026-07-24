# Group DB Config Selectable Candidate Diagnosis Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: e2fac24 phase2: document tenant connection handler verification
- Working tree expected state: clean

## 2. Purpose

- Tenant connection handler verification was implemented.
- Browser and runtime checks showed that only one tenant candidate per tested multi-membership account successfully reached the tenant workflow.
- Other displayed candidates failed with tenant connection unavailable.
- This document records the sanitized read-only central metadata diagnosis.

## 3. Diagnosis Scope

- Central DB `SELECT` only
- No tenant DB access
- No DB write
- No migration
- No endpoint call
- No browser smoke in this documentation task
- No code change

## 4. Sanitized Diagnosis Result

| row | display_name_redacted | has_membership | membership_active | has_group_db_config | config_active | alias_present | db_name_present | host_present | port_present | user_present | password_present | alias_matches_selection | expected_result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| account-1/group-1 | group-1 | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | metadata-pass |
| account-1/group-2 | group-2 | yes | no | no | no | no | no | no | no | no | no | no | metadata-fail |
| account-1/group-3 | group-3 | yes | no | yes | no | yes | yes | yes | yes | yes | no | yes | metadata-fail |
| account-2/group-1 | group-1 | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | metadata-pass |
| account-2/group-2 | group-2 | yes | no | no | no | no | no | no | no | no | no | no | metadata-fail |
| account-2/group-3 | group-3 | yes | yes | yes | yes | yes | yes | yes | yes | no | no | yes | metadata-fail |
| account-2/group-4 | group-4 | yes | yes | yes | yes | yes | yes | yes | yes | no | no | yes | metadata-fail |
| account-2/group-5 | group-5 | yes | no | no | no | no | no | no | no | no | no | no | metadata-fail |
| account-2/group-6 | group-6 | yes | no | no | no | no | no | no | no | no | no | no | metadata-fail |
| account-2/group-7 | group-7 | yes | no | yes | no | yes | yes | yes | yes | yes | no | yes | metadata-fail |

`group_db_config` does not have an independent active flag. `config_active` means the effective precondition of config existence plus active group and membership state used before required field completeness is evaluated. Full metadata eligibility is represented by `expected_result=metadata-pass`.

The table is sanitized and does not record actual identifiers or configuration values.

## 5. Findings

- For each tested multi-membership account, only one candidate fully passed metadata eligibility.
- Other displayed candidates failed due to one or more of:
  - inactive membership
  - missing group DB config row
  - missing required user metadata
  - missing required password metadata
  - combined metadata failures
- The group selection list can currently show candidates that the helper will later reject.
- The helper correctly fails closed when required metadata is missing.
- The current UX problem is that non-selectable groups are still displayed as selectable candidates.

## 6. Interpretation

- This is not the original `group_search` reverse issue.
- This is not primarily a Django connection-handler registry mutation issue.
- This is not proven to be a migration issue.
- The successful tenant candidate appears successful because its central metadata is complete.
- Failed candidates should not be offered as selectable tenant candidates unless their metadata is completed.
- The next code change should align group-selection candidate filtering with helper eligibility rules.

## 7. Proposed Future Fix Direction

- Update candidate query and rendering so only selectable candidates are displayed.
- Filter out inactive membership.
- Filter out missing group DB config.
- Filter out config rows missing required alias, database name, host, port, user, or password metadata.
- Preserve `group_select` fail-closed validation.
- Store only selectable candidates in session `tenant_candidates`.
- If zero selectable candidates remain, show a safe central message instead of broken tenant choices.
- If one selectable candidate remains, evaluate whether direct routing is appropriate, but do not change that behavior without a separate design.
- Do not add static environment-specific aliases to `settings.py`.
- Do not weaken helper validation.

## 8. Safety Notes

- No code was modified.
- No DB write was performed.
- No migration was performed.
- No tenant DB access was performed.
- No endpoint was called.
- No browser smoke was performed by this documentation task.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, or raw identifier was recorded.
- Sandbox or tool error endpoint text was not recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
