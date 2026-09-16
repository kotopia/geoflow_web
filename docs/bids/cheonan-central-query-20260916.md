# Cheonan central bid query cutover

## Ownership and user flow

Central `procurement.Notice` and its CollectionRule relation remain the public source.
Tenant `bid.central_preferences` holds only the selected central rule UUID array.
Existing `bid.filter_values` (regions/agencies) and `bid.keyword_rules` remain canonical;
they cannot store central keyword/industry subscriptions cleanly without confusing
central collection scope with tenant post-filtering, hence one additive singleton table.
No external API in tenant list, settings, refresh, or the legacy sync command after cutover.

Central conditions are OR, followed by AND with regions, agency, and include keywords.
Exclude keywords override. Both keyword lists apply to notice titles. An empty selected
condition array means no results; the old scope=all parameter cannot bypass selections.
SQL filters execute before count and pagination; multi-rule matches use DISTINCT.

Region tabs: overall / each enabled existing region / nationwide / region unknown.
Overall includes configured regions, explicitly unrestricted notices, and unknowns.
Named region tabs show that restriction only. Nationwide requires an explicit unrestricted
text value. Missing auxiliary information stays unknown, never inferred as nationwide.
These are review candidates, not guaranteed eligibility. Substring region matching uses
existing names/aliases; legal AND/OR joint-supply participation qualification is not inferred.
Central data coverage is incomplete and the UI says so; this change does not promise all history.

## Deployment and data preservation

Only the database names in `deploy/bids/central-tenants.json` opt in (cheonan_db).
Runtime resolves the already-authorized dynamic connection's NAME; no static tenant alias
or caller-supplied database parameter is introduced. Existing roles/CSRF guards are reused.

The existing protected deployment writes the non-secret allowlist to its atomic .env file,
verifies each target is an active real tenant through GroupDBConfig, then rehearses and
applies additive 0037/0038 in tenant transactions before restart. Other tenants keep legacy
behavior. It seeds selections from currently active matching industry codes, only if no
preference exists. Disabled central rules are not implicitly selected or reactivated.

Legacy reviews are mapped by the canonical official number/order UUID, verified by count,
with ON CONFLICT DO NOTHING preserving newer central reviews. Canonical collisions abort.
Legacy notices, reviews, filters, keywords are never deleted. A read-only '기존 검토기록'
view exposes old records even when a corresponding central notice has not been collected.
New reviews live only in tenant central_reviews. Mapped reviews are not all guaranteed to
appear under current filters; use the history screen for the preserved legacy snapshot.

Rollback restores the old .env and code through existing deployment compensation. Keep
additive tables and rows; do not reverse or delete business records. New central reviews
remain stored if reverting temporarily to legacy UI.

## Verification

Focused suite covers condition identity/OR/deduplication, empty selection, tenant isolation,
region tabs and unknown/nationwide separation, keyword boundary, invalid/disabled selections,
zero network calls on list/refresh and legacy sync blocking. PostgreSQL CI additionally
rehearses preference writes and idempotent review preservation using the actual legacy SQL.
Deployment emits only mapping counts and selected condition counts, not notes or API keys.
