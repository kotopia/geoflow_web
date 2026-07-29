# Non-selectable Tenant Metadata Read-only Review Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: a16eb9a phase3: plan work scope
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a future sanitized read-only database metadata review for non-selectable tenant candidates.
- Do not perform any database read in this planning step.
- Do not perform any database write or repair.
- Define only safe output rules and candidate checks for a separately approved future task.

## 3. Background

- Phase 2 documented that only selectable tenant candidates are stored in session and shown in the group-selection page.
- A user may belong to multiple groups but still route directly to one tenant if only one candidate remains selectable.
- Non-selectable tenant metadata may be caused by inactive membership, inactive group, missing database configuration, incomplete connection metadata, alias mismatch, or later connection registration failure.
- The previous analysis did not read real database values.

## 4. Future Review Questions

A future approved read-only review should answer only these sanitized questions:

| question | allowed output |
|---|---|
| how many group memberships exist for the target user | count only |
| how many memberships are active | count only |
| how many linked groups are active | count only |
| how many groups have database configuration | count only |
| how many configurations have complete required fields | count only |
| how many candidate aliases match configuration aliases | count only |
| how many candidates would be selectable | count only |
| whether connection registration would be attempted | yes/no only |
| whether connection registration would fail | yes/no only, no raw error values |

## 5. Prohibited Output

The future review must not print or store:

- real user email
- user ID
- group name
- group UUID
- tenant alias
- connection alias
- database name
- database host
- database user
- database password
- database port if tied to a real host
- session values
- raw exception messages containing runtime values
- contract identifiers
- event identifiers
- attachment identifiers
- S3 bucket or key
- presigned URL
- raw identifiers of any kind

## 6. Safe Output Format

The future review should report only:

- counts
- boolean values
- masked status labels
- generic category names
- pass/fail by condition
- no raw identifiers
- no hostnames
- no passwords
- no aliases
- no session values

Example safe result shape:

| check | result |
|---|---|
| memberships_found | count only |
| active_memberships | count only |
| active_groups | count only |
| db_configs_present | count only |
| complete_db_configs | count only |
| alias_consistency | count only |
| selectable_candidates | count only |

## 7. Future Execution Rules

Before any future DB read:

- obtain explicit user approval
- confirm the exact environment
- confirm that the task is read-only
- do not print secrets
- do not print identifiers
- do not write to DB
- do not run migration commands
- do not call endpoints
- do not perform browser smoke
- do not access S3
- do not generate presigned URLs

## 8. Review Scope Boundaries

Allowed in future approved read-only review:

- central metadata existence checks
- active status checks
- completeness checks
- alias consistency checks using masked counts
- connection readiness checks without printing raw config

Not allowed without separate approval:

- DB write
- metadata repair
- password change
- alias change
- group activation change
- membership activation change
- migration
- model change
- endpoint or browser test
- S3 or presigned URL work

## 9. Decision After Future Review

Possible outcomes:

| outcome | next action |
|---|---|
| all metadata complete | investigate connection registration separately |
| missing configuration | prepare metadata repair plan |
| incomplete configuration | prepare metadata repair plan |
| inactive membership or group | confirm business decision before repair |
| alias mismatch | prepare alias consistency repair plan |
| uncertain result | defer and expand read-only analysis only |

No repair should be performed automatically.

## 10. Safety Notes

- No code was modified by this planning task.
- No test was modified by this planning task.
- No database SELECT was performed.
- No database write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No sensitive runtime identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 11. Conclusion

- This document defines a safe future read-only metadata review.
- Actual database reading remains blocked until explicit approval.
- Metadata repair remains blocked until a separate repair plan and explicit approval.
- The immediate next step after this plan is user approval or deferral.
