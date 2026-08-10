# GeoFlow Phase 2: trusted proxy and HTTPS security rollout

## Current boundary

GeoFlow is publicly served over HTTPS, while Django currently treats `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, and `SECURE_PROXY_SSL_HEADER` as not yet activated production controls. The earlier signup-verification CSRF incident showed that the reverse-proxy/TLS boundary must be proven before Django is told to trust forwarded scheme information.

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

## Step 2 — wire Django settings, still disabled by default

After Step 1 passes, add explicit environment-driven settings for:

- `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")` only when the reviewed proxy contract is enabled;
- `SECURE_SSL_REDIRECT`, default `False` until the proxy header contract is proven;
- `SECURE_HSTS_SECONDS`, default `0`;
- HSTS include-subdomains/preload flags, default `False`.

Repository and CI defaults must remain compatible with local/non-proxy development. Production activation must be an explicit environment change, not a hard-coded always-on setting.

## Step 3 — guarded production activation

Use a separately reviewed production-gated change. In order:

1. enable only the exact `HTTP_X_FORWARDED_PROTO=https` trust contract;
2. restart `geoflow-stabilized.service`;
3. verify HTTPS login, signup, resend, verification, password-reset request/reset, and tenant login routes do not redirect-loop or fail CSRF checks;
4. enable Django `SECURE_SSL_REDIRECT` only after the trusted scheme probe is healthy;
5. verify HTTP-to-HTTPS and HTTPS routes again;
6. enable HSTS with a short initial duration;
7. increase HSTS duration only after a stable observation period;
8. do not enable `includeSubDomains` or `preload` until every relevant subdomain is verified HTTPS-only.

## Rollback

If Django begins redirect-looping, misclassifies HTTPS requests, or browser POSTs regress:

1. restore the previous runtime environment values;
2. disable Django SSL redirect and the proxy trust setting;
3. restart only `geoflow-stabilized.service`;
4. verify the public HTTPS routes and CSRF-protected POST boundaries;
5. leave HSTS disabled or at the previously proven duration.

Do not alter Nginx, certificates, `.env`, systemd, or application databases from the read-only readiness diagnostic.
