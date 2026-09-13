# Central collection audit and resume correction

The September 11 deployment proved schema installation, five initial active rules,
API linkage and timer activation. It did not prove the two-year backfill completed.
Production checkpoint/count data as of September 13 has not yet been read.

Code findings at release 749eb86e:

- Central dashboard total is Notice.count(), with no 200-row cap. Per-rule counts
  are database aggregates. Tenant lists still use their existing database until
  explicitly enabled for central reads; pagination is 15/30.
- Each rule starts a two-year backfill, advances in day-sized windows and commits
  its cursor only after the full window succeeds. Five rules need roughly 3,650
  initial posting-search windows before any detail requests or incremental work.
- Default worker budget is 100 requests per invocation, daily central budget 500;
  these are request limits, not notice limits. The provider's actual quota and
  production overrides must be read separately and must not be assumed to be 10,000.
- Failed live windows previously recomputed their end time. Rejected changed
  notices were not stored, so their detail requests could consume budget repeatedly.
- A rule-level API error stopped the entire worker and could block later rules.

Correction uses the existing job progress JSON: preserve the failed window bounds
and content hashes of successfully processed notices, including rejected notices.
On retry skip unchanged completed rows, recheck changed content, and advance the
cursor only after success. Preserve source notices and all existing cursor data.
No schema migration or deletion is introduced. Non-global API errors permit later
rules to run; authentication/quota/network failures still stop the worker.

`python manage.py report_central_bids` performs aggregate SELECTs only (a read-only
repeatable-read transaction when standalone on PostgreSQL). It reports actual total,
per-rule counts/date range, backfill and live cursors, last success, remaining range,
error code, current progress and the previous seven days plus today of API usage.
It excludes notice payloads, credentials and tenant records. No external API call.
Deployment prints this report before central migrations/seeding and after timer
installation, plus whitelisted service result/exit-status properties. The existing
production Environment gate remains mandatory; no deployment success alone may be
reported as proof of complete backfill. A cursor proves collection-window traversal,
not an independent provider-total reconciliation.
