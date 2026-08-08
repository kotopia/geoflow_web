# Signup background jobs plan

Status: design only. No scheduler, server service, cron entry, database command, or mail worker has been activated.

## Goal

Public signup needs three operational loops after the schema and runtime configuration are approved:

1. deliver queued verification mail;
2. expire stale signup requests;
3. purge rejected/expired signup-only identities after the one-year retention period.

These jobs must be operationally independent from the web process and must preserve the repository's bounded-batch/fail-closed behavior.

## Proposed jobs

### Verification outbox worker

Command pattern:

```text
python manage.py process_signup_verification_outbox --limit <bounded batch>
```

Recommended production cadence: frequent, short executions (for example once per minute) rather than one long-running unbounded loop. Runtime settings must already pass the signup readiness gate. The worker should be observed together with `check_signup_verification_outbox` reconciliation output.

### Stale request expiration

Policy:

- `pending_email_verification`: expire after 7 days;
- `pending_approval`: expire after 30 days.

Preview without DB query/write:

```text
python manage.py expire_signup_lifecycle
```

Actual transition requires explicit execution mode:

```text
python manage.py expire_signup_lifecycle --execute --batch-size 100
```

Recommended eventual cadence: daily. Do not enable `--execute` in a production scheduler until the migration state and policy values have been approved.

### One-year retention purge

Default invocation is a dry run:

```text
python manage.py purge_signup_retention --batch-size 100
```

Actual purge requires explicit execution mode:

```text
python manage.py purge_signup_retention --execute --batch-size 100
```

The cutoff is a calendar-year anniversary rather than a fixed 365-day duration, including leap-day handling. Candidate selection and final deletion must exclude identities with active memberships, other signup requests, join-request linkage, group ownership, or audit/decision responsibilities.

Recommended eventual cadence: daily or weekly. Start with scheduled dry-run reporting before enabling execution.

## Safe enablement order

1. Apply signup migrations in an approved change window.
2. Run `check_signup_launch_schema --strict` against the approved environment.
3. Configure NAVER SMTP/HMAC/outbox secrets without exposing them in logs or source control.
4. Run outbox reconciliation in read-only mode.
5. Enable the verification-mail worker and verify delivery with a controlled test account.
6. Run lifecycle-expiry command in preview mode, then approve execution scheduling.
7. Run retention purge in dry-run mode for an observation period, then separately approve `--execute` scheduling.
8. Only after those controls are stable should the final public-signup activation gate be enabled.

## Scheduling mechanism

Use the deployment environment's existing scheduler standard (for example systemd timers or another centrally managed scheduler). Do not introduce an ad-hoc web-request-triggered scheduler. The scheduler definition must run under the same deployed application release and runtime environment as the Django management commands, with logs that contain counts/status only and no email addresses, tokens, passwords, or HMAC key material.

## Expiration/delivery race handling

A signup request with a currently live `processing` verification-delivery lease should be skipped by the stale-request expiration batch. This avoids expiring the request after token issuance but immediately before an in-flight mail send. Once the short lease expires or delivery completes, the next bounded expiration run can process the request normally if it is still stale.
