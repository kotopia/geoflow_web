# Incomplete Connection Metadata Repair Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 56b2fba phase3: defer inactive membership repair
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a safe repair plan for the incomplete connection metadata category.
- The previous read-only review found 2 rows with incomplete connection metadata.
- Do not perform database read or write in this planning step.
- Do not repair metadata automatically.
- Require explicit approval before any future database write.

## 3. Background

- The non-selectable tenant metadata review found 14 candidate relationships.
- 6 candidates were selectable.
- 8 candidates were non-selectable.
- 6 non-selectable candidates were inactive membership rows and have been deferred.
- 2 non-selectable candidates had incomplete connection metadata.
- The next repair focus is the 2 incomplete connection metadata rows.

## 4. Repair Target

| category | count | current treatment |
|---|---:|---|
| incomplete connection metadata | 2 | plan only |
| inactive membership rows | 6 | deferred |
| alias mismatch | 0 | no repair currently indicated |
| missing DB config | 0 in selectable-candidate filter result | no immediate repair currently indicated |
| inactive group | 0 in selectable-candidate filter result | no immediate repair currently indicated |

## 5. Required Future Information

Before repair, a separately approved read-only check must identify missing field categories without printing raw values.

Allowed future output:

| check | allowed output |
|---|---|
| row count | count only |
| missing alias | yes/no count |
| missing database name | yes/no count |
| missing host | yes/no count |
| missing port | yes/no count |
| missing user | yes/no count |
| missing password | yes/no count |
| alias consistency | pass/fail count |
| repair readiness | ready/not ready count |

Prohibited output:

- real tenant alias
- connection alias
- database name
- database host
- database user
- database password
- database port tied to a real host
- group name
- group UUID
- user email
- user ID
- session value
- raw exception message
- raw identifier of any kind

## 6. Future Repair Options

### Option A: Fill missing non-secret metadata only

- Use only when missing fields are non-secret and known.
- Requires explicit DB write approval.
- Must not print raw values.
- Must document changed field categories only.

### Option B: Fill missing secret metadata

- Use only when password or other secret fields are missing.
- Requires explicit DB write approval.
- Must obtain values through a secure local process.
- Must not paste secrets into GPT.
- Must not record secrets in documents or logs.

### Option C: Defer repair

- Use when the tenant is no longer needed.
- Use when metadata source is uncertain.
- Use when business ownership is unclear.
- No DB change.

## 7. Recommended Future Sequence

1. Prepare a local-only missing-field review.
2. Run read-only check only after explicit approval.
3. Report only missing-field category counts.
4. Decide whether the 2 rows should be repaired or deferred.
5. If repair is approved, prepare a DB write script that updates only approved fields.
6. Review the script before execution.
7. Execute DB write only after explicit approval.
8. Verify with a sanitized read-only check.
9. Document the result.

## 8. Safety Rules for Future DB Write

- One approved repair step only.
- No bulk update without exact scope.
- No update to inactive membership rows.
- No group activation.
- No membership activation.
- No migration.
- No endpoint call.
- No browser smoke.
- No S3 operation.
- No presigned URL generation.
- No secret printing.
- No raw identifier recording.
- Verify with SELECT after repair.
- Record only sanitized counts and boolean outcomes.

## 9. Out of Scope

- Repair implementation in this planning step.
- DB SELECT in this planning step.
- DB write in this planning step.
- Inactive membership repair.
- Group activation.
- Membership activation.
- W342 warning cleanup.
- Controlled write/upload smoke.
- Browser smoke.
- Endpoint smoke.
- S3 or presigned URL work.
- Broad template cleanup.

## 10. Safety Notes

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
- No raw identifiers were recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 11. Conclusion

- The next repair focus is the 2 incomplete connection metadata rows.
- This document does not approve or perform repair.
- A future read-only missing-field review is required before any database write.
- Any database repair must be separately approved and must avoid printing secrets or raw identifiers.
