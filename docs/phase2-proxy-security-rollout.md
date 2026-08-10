# GeoFlow Phase 2: trusted proxy and HTTPS security rollout

## Current boundary

GeoFlow is publicly served over HTTPS, while Django still leaves `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, and trusted forwarded-proto handling disabled by default. The earlier signup-verification CSRF incident showed that the reverse-proxy/TLS boundary must be proven before Django is told to trust forwarded scheme information.

The goal is to harden this boundary without creating a redirect loop, trusting an unverified client-supplied header, or enabling HSTS before the canonical HTTPS path is stable.

## Step 1 — read-only readiness diagnostic

Run `.github/workflows/phase2-proxy-security-readiness-diagnostic.yml` only from `release/stabilized-deploy` through the protected `production` Environment.

The diagnostic is intentionally read-only. It must:

- verify `geoflow-stabilized.service` is running;
- report only the shape of Django TLS/security settings, never database or credential values;
- inspect the effective Nginx configuration without printing it and prove that `X-Forwarded-Proto` is set from `$scheme` or the constant `https` value;
- prove public HTTP redirects to the canonical HTTPS origin;
- prove the public HTTPS login endpoint remains healthy;
- report whether an HSTS response header is already present at the public boundary, without requiring HSTS yet.

The diagnostic must fail closed when the trusted forwarded-proto boundary cannot be proven.

## Step 2 — Django settings wiring prepared, production activation still disabled

The repository now has explicit environment-driven settings with the current runtime behavior preserved by default:

- `DJANGO_TRUST_X_FORWARDED_PROTO=1` maps only to `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")`; arbitrary proxy header names or values are not accepted;
- `DJANGO_SECURE_SSL_REDIRECT` defaults to `False`;
- `DJANGO_SECURE_HSTS_SECONDS` defaults to `0`;
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` and `DJANGO_SECURE_HSTS_PRELOAD` default to `False`;
- invalid boolean/integer values fail closed during settings loading;
- HSTS preload is rejected unless include-subdomains is enabled and the duration is at least one year.

`SITE_ORIGIN` and `DEFAULT_FROM_EMAIL` also honor their existing runtime environment values while keeping the previous local fallback values.

Repository and CI defaults remain compatible with local/non-proxy development. Production activation is still a separate explicit environment change; merging the settings wiring does not enable proxy trust, Django SSL redirect, or HSTS by itself.

## Step 3 — guarded production activation

Use a separately reviewed production-gated change. In order:

1. run the read-only readiness diagnostic and require the forwarded-proto and public HTTPS boundary checks to pass;
2. enable only `DJANGO_TRUST_X_FORWARDED_PROTO=1`;
3. restart `geoflow-stabilized.service`;
4. verify HTTPS login, signup, resend, verification, password-reset request/reset, and tenant login routes do not redirect-loop or fail CSRF checks;
5. enable `DJANGO_SECURE_SSL_REDIRECT=1` only after the trusted scheme probe is healthy;
6. verify HTTP-to-HTTPS and HTTPS routes again;
7. enable HSTS with a short initial `DJANGO_SECURE_HSTS_SECONDS` value;
8. increase HSTS duration only after a stable observation period;
9. do not enable include-subdomains or preload until every relevant subdomain is verified HTTPS-only.

## Rollback

If Django begins redirect-looping, misclassifies HTTPS requests, or browser POSTs regress:

1. restore the previous runtime environment values;
2. disable Django SSL redirect and the forwarded-proto trust setting;
3. restart only `geoflow-stabilized.service`;
4. verify the public HTTPS routes and CSRF-protected POST boundaries;
5. leave HSTS disabled or at the previously proven duration.

Do not alter Nginx, certificates, `.env`, systemd, or application databases from the read-only readiness diagnostic.
