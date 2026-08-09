# GeoFlow EC2 application-only release runbook

Status date: 2026-08-09

This runbook deploys application code and static assets only. It intentionally does
not run `migrate`, create tenant databases, mutate S3 objects, rotate credentials,
send signup mail, enable a scheduler, or open public signup.

## Preconditions

- Release source is `release/stabilized-deploy` at one explicitly reviewed commit.
- GitHub `release-preflight` job is successful for that exact commit.
- Public HTTPS smoke findings are understood before cutover.
- The host has a reviewed Python runtime, GeoDjango system libraries, Nginx, and
  systemd.
- Runtime configuration is provided outside Git by a restricted environment source.
- No secret value is pasted into terminal history, tickets, logs, or this repository.
- Central/tenant DB migrations remain a separate change with separate approval and
  rollback.

## Host layout assumed by the templates

```text
/srv/geoflow/current        application checkout
/srv/geoflow/venv           Python virtual environment
/run/geoflow/gunicorn.sock  Gunicorn Unix socket
/etc/geoflow/geoflow.env    host-owned runtime environment source
```

If the existing host uses different paths, update the reviewed templates before
installation rather than creating compatibility symlinks ad hoc.

## Application-only deployment sequence

1. Record the currently deployed application commit for rollback.
2. Fetch the reviewed release commit and verify the exact SHA before changing the
   active checkout. Never force-reset to an unreviewed ref.
3. Create/update the isolated virtual environment and install only
   `requirements.txt`.
4. Run `python -m pip check`.
5. Run `python manage.py check`.
6. Run `python manage.py check_release_preflight --strict` using the intended runtime
   environment. Do not print the environment.
7. Run the focused Phase 1 security regression tests used by
   `.github/workflows/release-preflight.yml`.
8. Run `python manage.py collectstatic --noinput`.
9. Do **not** run `migrate` in this application release sequence.
10. Validate the reviewed systemd and Nginx configuration with their native syntax
    checks before reload/restart.
11. Reload or restart Gunicorn and reload Nginx using the host's approved service
    procedure.
12. Verify process health and the Unix socket before public traffic validation.
13. Run public smoke checks for HTTP->HTTPS, root/login behavior, `/terms/`, and
    `/privacy/`.
14. Confirm security-header presence. HSTS should be staged with a short max-age first
    and increased only after the HTTPS topology and rollback behavior are proven.
15. Keep public signup closed unless the DB-backed launch audit, tenant secret-reference
    audit, SMTP/HMAC delivery validation, worker supervision, and legal-page checks have
    all passed.

## Nginx access-log token boundary

The legacy set-password routes can carry raw compatibility tokens in the request
path. The provided Nginx example suppresses access logging for those route prefixes.
Do not enable a new proxy/access-log layer that records those paths while the legacy
routes remain present.

## Separate read-only DB gate

When a specifically selected non-production central DB is available, run:

```text
python manage.py check_signup_launch_schema --strict
python manage.py check_tenant_db_secret_refs --strict
```

These are not part of the generic application deploy command. A successful app
release does not imply that either database audit passed.

## Rollback

1. Stop accepting a new release if health checks fail.
2. Restore the previously recorded application commit and its compatible virtual
   environment/dependency set.
3. Re-run `python manage.py check` and the non-destructive release preflight.
4. Restore/reload the prior Nginx/systemd configuration if those files changed.
5. Re-run public HTTPS/root smoke tests.
6. Do not attempt to roll back an independently executed database migration by
   changing application code alone.

## Current observed production boundary

Read-only GitHub-hosted smoke checks on 2026-08-09 observed:

- HTTP root redirects to HTTPS.
- HTTPS root responds.
- `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` are present.
- HSTS is not currently present.
- `/terms/` and `/privacy/` currently return 404, indicating the Phase 1 legal routes
  are not deployed on the public service yet.

These observations are external behavior only; they do not prove the internal
`SECURE_PROXY_SSL_HEADER` trust contract because that requires host/proxy inspection.
