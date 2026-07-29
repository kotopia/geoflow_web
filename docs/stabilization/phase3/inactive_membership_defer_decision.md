# Inactive Membership Defer Decision

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 5bd4217 phase3: document inactive membership readonly review
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Decision

- The 6 inactive membership rows will not be activated in the current step.
- The decision is to defer all 6 inactive membership rows.
- No database repair will be performed for these rows now.
- No membership activation will be performed now.
- No group activation will be performed now.
- No database configuration repair will be performed for these rows now.

## 3. Reason

- The read-only review found 6 inactive memberships.
- None of the 6 rows would become selectable through membership activation alone.
- All 6 rows have additional metadata issues.
- None of the 6 rows is linked to an active group.
- None of the 6 rows has complete required connection metadata.
- Activating only membership would not make these candidates safely selectable.
- Automatic activation could expose incomplete or inactive tenant choices.

## 4. Current Treatment

| item | treatment |
|---|---|
| inactive membership rows | defer |
| membership activation | blocked |
| group activation | blocked |
| DB configuration repair for these rows | blocked |
| metadata repair for these rows | blocked |
| future business review | allowed separately |

## 5. Next Recommended Focus

- Focus next on the incomplete connection metadata category from the selectable-candidate review.
- That category contains 2 rows.
- Prepare a separate repair plan before any database write.
- Do not combine inactive membership activation with incomplete metadata repair.
- Do not repair any database metadata automatically.

## 6. Safety Status

- No code was modified.
- No test was modified.
- No database SELECT was performed in this decision step.
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

## 7. Conclusion

- The inactive membership rows are deferred.
- This avoids unsafe partial activation.
- The next safe task is an incomplete connection metadata repair plan.
- Any future activation or repair must be separately scoped and explicitly approved.
