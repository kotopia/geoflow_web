# GeoFlow Phase 1 Production Closeout

Status: **COMPLETE**

Closed on: 2026-08-09 (Asia/Seoul)

Release branch: `release/stabilized-deploy`

## Scope closed

Phase 1 established and activated the guarded central signup and email-verification path for GeoFlow production.

Completed scope includes:

- central signup schema and migrations for signup requests, events, verification tokens, and verification delivery outbox
- inactive-user creation on signup (`is_active=false`, `email_verified=false`)
- initial signup state `pending_email_verification`
- submitted audit event creation
- password hash stored only on the central `users` record
- invitation code excluded from validation, persistence, and automatic approval
- one-time HMAC-backed email verification tokens
- token expiry, revocation, and replay protection
- email verification transition to `pending_approval`
- SMTP delivery through the production mail account using an application password
- guarded resend flow
- production verification outbox worker and systemd timer
- fail-closed production runtime readiness checks
- guarded production activation with rollback
- rollback-only production E2E closeout verification

## Production activation evidence

Production signup activation completed successfully in GitHub Actions:

- workflow: `Phase 1 signup production activation`
- run: `31314130681`
- reviewed release SHA: `2afd62f8d9b4cae4796a8b742ce693f575641e7d`

Activation verified:

- production runtime readiness
- signup launch schema readiness
- SMTP authentication readiness
- verification HMAC configuration
- signup verification outbox consistency
- public `/signup/` availability
- public `/signup/resend/` availability
- outbox worker/timer installation and activation

## Final production E2E evidence

Final rollback-only E2E closeout completed successfully:

- workflow: `Phase 1 production E2E closeout v2`
- run: `31314685539`
- reviewed release SHA: `384c7ebd9dbad701bba2eac01313b201ced4ba00`

Verified outcomes:

- signup code matched the reviewed release baseline
- public signup endpoint returned ready state
- resend endpoint returned ready state
- signup outbox timer was enabled and active
- production runtime strict check passed
- signup schema strict check passed
- outbox consistency check reported no anomalies
- no pre-existing live outbox item was present before the rollback-only E2E
- test signup request was created
- initial state was inactive and unverified with `pending_email_verification`
- verification delivery outbox item was created and claimed
- verification token/link generation path executed
- email verification transitioned the user to `email_verified=true`
- signup request transitioned to `pending_approval`
- verified event was appended
- verification token replay was rejected
- the entire E2E transaction was rolled back
- no test user residue remained after rollback
- post-test outbox consistency remained clean

Final marker:

`phase1_production_e2e_closeout_complete=yes`

## Release validation

Release preflight run `31314685474` completed successfully for the E2E closeout revision.

All jobs passed:

- `release-preflight`
- `public-https-smoke`
- `migration-rehearsal`

The migration rehearsal covered both central and tenant migration paths on disposable databases.

## Production state at closeout

Phase 1 production signup is considered **live and ready**.

Expected public flow:

1. user submits signup
2. central user remains inactive
3. request enters `pending_email_verification`
4. verification delivery is queued
5. outbox worker sends verification mail
6. one-time token is consumed
7. `email_verified` becomes true
8. signup request enters `pending_approval`
9. administrator approval remains a separate controlled step

## Non-blocking follow-up items

The following warnings were present at closeout and are intentionally not Phase 1 blockers:

- Django `SECURE_SSL_REDIRECT` is not enabled; proxy/TLS termination behavior should be confirmed before changing it
- HSTS is not enabled; stage only after HTTPS/proxy behavior is fully confirmed
- `SECURE_PROXY_SSL_HEADER` is not configured; confirm the trusted reverse-proxy contract first
- `catalog.CategoryParent.child` uses `ForeignKey(unique=True)` and raises Django warning `fields.W342`; consider `OneToOneField` during catalog model cleanup

These items do not invalidate the Phase 1 signup activation or E2E result.

## Security notes

- no SMTP passwords, application passwords, HMAC keys, SSH keys, database passwords, or other secret values are recorded in this document
- production SMTP credentials remain external to Git and are managed through protected runtime/GitHub environment configuration
- production-mutating workflows remain protected by the `production` GitHub Environment approval gate

## Closeout decision

**Phase 1 is closed.**

New signup functionality should now be treated as an active production capability. Further work should proceed under the next phase rather than extending Phase 1, except for production defects or regressions directly attributable to this rollout.
