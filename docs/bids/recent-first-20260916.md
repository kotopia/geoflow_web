# Recent-first central bid collection rollout

The user reported an operating-account application and a daily allowance of 100,000 requests, and authorized collection changes and deployment. The application does not independently read the portal subscription quota. Provider quota/authentication errors remain hard stops; an application is not interpreted as unlimited traffic.

## Order and preservation

New/changed notices run before historical backfill. Backfill chooses the newest unverified one-day interval, walking backwards from each condition's existing backfill end to the current rolling two-year cutoff. Verified CollectionWindow receipts are reused. The legacy forward cursor is retained for rollback compatibility but is not a completeness proof or the next interval indicator.

A previously interrupted window is resumed first, preserving its received pages and notice outcomes. After that bounded window finishes, the next window follows the newest-first order. No notice, rule, generation, receipt or checkpoint is reset. Disabled conditions remain disabled. No DB migration is introduced.

Each rule receives a bounded share of each phase's request budget, up to 100 requests per turn. Rules least recently attempted in that lane are processed first. Exhaustion of one rule's slice does not prevent the other active rules from making progress. Incremental catch-up preserves its existing cursor so changes are not skipped.

## Operational budget

Deployment applies deploy/bids/collector-budget.json to the existing .env using the existing atomic replacement and rollback mechanism. It manages only the six listed non-secret settings, alongside the already-managed API credential. Existing unrelated settings are preserved. This also replaces explicit legacy 500/100 settings if present. Runtime environment variables still take precedence over .env; the deployment's aggregate audit reports effective values.

- Daily central requests: 80,000 (cap, not throughput promise).
- Requests per job: 500; maximum completed windows: 50.
- Daily reserve for incremental collection: 5,000.
- Request starts spaced by at least 1 second within the single locked collector.
- Shared job time budget: 720 seconds; pause before starting a request that could cross the deadline, below systemd's 900-second timeout.

The daily central counter does not include other applications or deployment probes using the same credential. The remaining 20,000 relative to the user-reported quota is headroom, not a verified measurement of those callers. HTTP/provider quota and rate-limit errors stop the job; they do not trigger a request burst.

## Validation and rollout evidence

59 isolated collection tests and 7 deployment contract tests passed locally. Coverage includes backwards windows, receipt-based restart, preservation of an interrupted legacy window, retention boundaries, rule fairness and request pacing/deadline. Migration drift check is clean. PostgreSQL CI is required before merge.

The central dashboard and read-only audit show newest-uncovered-day ordering and the next backfill interval. Old historical counts are not reconstructed or reported as zero collected notices. Actual production counts, effective budget and collector state must be read from the protected deployment audit after rollout; two-year completion is not assumed.

Tenant cutover and physical deletion policies are unchanged. No attachment downloading is added. Rollback preserves DB originals/receipts and uses the existing env backup.
