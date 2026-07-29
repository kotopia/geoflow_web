# Phase 3 Work Scope Plan

## 1. Baseline

- Branch: phase2-clean-base
- Starting point: f9c4947 phase2: checkpoint stabilization final state
- Phase 2 status: closed at documentation level
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define the next work scope after Phase 2 stabilization.
- Separate safe documentation and analysis tasks from risky database, migration, endpoint, browser, S3, and write-flow tasks.
- Prevent unrelated changes from being mixed into one step.
- Require explicit approval before any database read, database write, migration, endpoint smoke, browser smoke, S3 operation, presigned URL operation, or controlled write/upload test.

## 3. Phase 2 Closure Summary

- Login and group-selection stabilization is complete.
- Selectable tenant-candidate filtering is complete.
- Tenant connection registration and fail-closed routing are complete.
- Upload, delete, CSRF, read authorization, and permission hardening are complete within the approved scope.
- Diagnostic log cleanup is complete within the approved scope.
- Inactive legacy middleware cleanup is complete.
- Test-only diagnostic cleanup is complete.
- W342 warning cause was analyzed and deferred.
- Non-selectable tenant metadata conditions were analyzed and deferred.
- Phase 2 final checkpoint was committed.

## 4. Phase 3 Candidate Work Items

| item | risk level | allowed first step | requires explicit approval |
|---|---|---|---|
| database metadata review for non-selectable tenants | medium | read-only plan document | yes, before DB read |
| database metadata repair for non-selectable tenants | high | no direct action | yes, before DB write |
| W342 model warning cleanup | high | model/migration design document | yes, before model or migration work |
| controlled write/upload smoke | high | smoke test plan document | yes, before browser or endpoint execution |
| broad template cleanup | medium | template inventory analysis | yes, before implementation |
| placeholder test cleanup | low | test inventory analysis | yes, before test file changes |
| expected warning capture redesign | medium | test design analysis | yes, before implementation |

## 5. Recommended Order

1. Create a database metadata review plan for non-selectable tenants.
2. If explicitly approved, run sanitized read-only metadata checks.
3. Based on read-only results, decide whether metadata repair is needed.
4. Keep W342 cleanup deferred until a separate model and migration design is approved.
5. Keep controlled write/upload smoke deferred until the user explicitly approves write-flow testing.
6. Keep broad template cleanup separate from security, routing, and database work.

## 6. Rules for Future Phase 3 Work

- One task per step.
- One narrow document, code file, or test file group per step.
- No `git add .`.
- No `git add -A`.
- No `git push` without explicit approval.
- No database read without explicit approval.
- No database write without explicit approval.
- No migration command without explicit approval.
- No endpoint call without explicit approval.
- No browser smoke without explicit approval.
- No S3 or presigned URL work without explicit approval.
- No `.env` printing.
- No secret printing.
- No raw runtime identifier logging.
- No real user email, group name, group UUID, tenant alias, connection alias, database host, database password, session value, S3 key, presigned URL, or raw identifier in documents.

## 7. Recommended Immediate Next Step

- Create a separate plan document for sanitized read-only database metadata review.
- Do not perform the database read in the plan step.
- The database review plan should specify sanitized outputs only:
  - counts
  - boolean completeness checks
  - masked status labels
  - no raw identifiers
  - no passwords
  - no hostnames
  - no session values
- After that plan is reviewed, ask for explicit approval before any DB read.

## 8. Deferred Until Explicit Approval

- real database metadata read
- real database metadata repair
- any DB write
- any migration
- W342 implementation
- controlled write/upload smoke
- browser smoke
- endpoint smoke
- S3 operation
- presigned URL operation
- broad template implementation
- git push

## 9. Safety Notes

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

## 10. Conclusion

- Phase 3 should start with planning and read-only analysis.
- The safest immediate next item is a database metadata review plan for non-selectable tenants.
- Actual database reads, repairs, migrations, endpoint checks, browser checks, and write/upload tests must remain blocked until explicit approval.
