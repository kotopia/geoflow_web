# Phase 2 proxy security staged activation

This runbook is the guarded continuation of the Phase 2 proxy/TLS readiness work.
It does not change Nginx configuration. It only enables Django-side settings after
the production proxy boundary has already been proven ready.

## Mandatory order

Run `.github/workflows/phase2-proxy-security-readiness-diagnostic.yml` first and
require its proxy/public HTTPS checks to pass. Then execute the staged activation
workflow through the protected `production` Environment, one invocation per stage:

1. `trust-proxy`
   - requires the current Django proxy/redirect/HSTS state to be fully disabled;
   - requires effective Nginx `X-Forwarded-Proto` forwarding;
   - enables only the fixed Django trusted-proxy contract;
   - leaves SSL redirect and HSTS disabled.
2. `ssl-redirect`
   - requires the trust-proxy stage to already be active and HSTS disabled;
   - enables Django HTTPS redirect;
   - leaves HSTS disabled.
3. `short-hsts`
   - requires trusted proxy and Django SSL redirect already active;
   - enables only `max-age=300`;
   - keeps `includeSubDomains` and `preload` disabled.

Every invocation requires the explicit confirmation string
`PHASE2_PROXY_ACTIVATE` and a separate protected production approval.

## Guardrails

The workflow verifies public HTTP-to-HTTPS redirect and HTTPS login health before
mutation, verifies that the production service is running, requires the reviewed
proxy-security code blobs, rejects systemd-level overrides for the managed Django
security settings, and reads effective Nginx configuration only to prove
`X-Forwarded-Proto` forwarding.

Before changing `.env`, the workflow stores a mode-preserving backup under a
run-specific temporary path. It changes only these keys:

- `DJANGO_TRUST_X_FORWARDED_PROTO`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_SECURE_HSTS_SECONDS`
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `DJANGO_SECURE_HSTS_PRELOAD`

It runs Django checks, restarts only `geoflow-stabilized.service`, verifies the
resulting settings, and performs runner-side public HTTP/HTTPS smoke checks. The
backup is deleted only after those public checks pass. If any post-mutation step
fails while the backup remains, the failure handler restores `.env` and restarts
the GeoFlow stabilized service.

The workflow does not run migrations, pull/reset the server repository, mutate
Nginx, enable HSTS subdomains/preload, or print `.env`/systemd environment values.

## HSTS expansion

Do not increase the HSTS lifetime and do not enable `includeSubDomains` or
`preload` as part of this Phase 2 activation. Those settings require separate
review after every relevant subdomain is proven HTTPS-only and rollback risk is
accepted.
