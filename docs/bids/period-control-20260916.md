# Central historical collection period

The administrator can choose a start/end date for all active central rules, or apply recent 1/3/6/12/24 calendar months. The selector is on the existing central bid dashboard, protected by its real central-admin authorization and CSRF checks. It never issues G2B requests during a page request.

## Default and boundaries

With no saved setting, historical backfill is restricted to the recent calendar month. Saving makes the selected dates persistent in central CollectionPeriod (singleton row). Both dates use Asia/Seoul; a past end date includes 23:59, today's upper bound is the current minute. Future dates, reversed dates and starts older than the rolling two-year boundary are rejected server-side. A previously saved start can age out; collection clamps it to the current two-year cutoff without deleting data.

The selected range intersects each job's historical backfill start/end. Notices after that job's original backfill end remain the responsibility of its independent incremental cursor. Newly posted and changed notices continue to be collected regardless of the historical selection. The dashboard distinguishes historical completion from the last incremental success time. A shorter selected range reaching completion is RANGE_COMPLETE, not a claim that two years are complete.

## Resume and scope changes

The newest uncovered daily interval within the selected bounds runs first. Existing verified receipts are reused and original notices remain unique. An unfinished page/window outside newly selected bounds is retained under backfill_progress.suspended_windows, including its page cache and outcomes. It is not requested while out of scope. Expansion restores compatible suspended windows before opening another window. Partial-overlap windows are preserved while the currently allowed subrange is collected independently.

A running collector checks for a saved range change before each external request, between notice processing and before committing a completed window. It records SCOPE_CHANGED and stops the job; an already in-flight request can complete, with its received page retained. The next execution uses the new range. No job generation or incremental checkpoint is reset.

## Storage and migration

0004 adds only the central CollectionPeriod table and date-order/singleton constraints. It does not update existing rules, jobs, notices, receipts, tenant records or settings. No saved row is required for the bounded default. Code rollback keeps the additive table and all data; do not reverse-migrate to delete settings or checkpoints. The previous release has broader historical collection behavior, so pause the collector before any rollback that removes period enforcement.

This is a historical API collection boundary, not a deletion policy or a maximum database-size guarantee. Existing originals and business-linked records remain preserved. API budgets and request pacing from PR #325 are unchanged.

## Verification

67 isolated collection tests pass, including default-month stopping, full-two-year distinction, Korean date inclusivity, period validation and presets, paused checkpoint restoration, in-flight changes, continued incremental updates, central authorization and CSRF. Migration drift is clean and seven deployment contract tests pass. PostgreSQL CI must pass before merge. Protected production deployment is required before claiming this is active.
