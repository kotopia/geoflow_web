# Django 5.2 LTS security upgrade plan

Status date: 2026-08-08

## Current repository state

- `requirements.txt` currently pins Django 5.2.4.
- GeoFlow is intentionally staying on the Django 5.2 LTS feature series for this release-stabilization phase.
- The repository-side release preflight requires at least Django 5.2.16 and fails closed on older 5.2 patches or on an unreviewed feature series.

## Why this blocks release

Django 5.2.16 was issued on 2026-07-07 as a security release for the supported 5.2 LTS series. The Django project recommends upgrading supported users to the latest patch release. GeoFlow's current 5.2.4 pin predates multiple 2026 security fixes, so it must not be treated as a production-ready dependency baseline.

Official references:

- https://www.djangoproject.com/weblog/2026/jul/07/security-releases/
- https://www.djangoproject.com/download/
- https://docs.djangoproject.com/en/5.2/releases/security/

## Exact change boundary

`requirements.txt` is a protected file under the repository operating rules. This document does not authorize changing it. The dependency pin should be changed only after explicit approval naming the dependency update.

Expected narrow change after approval:

```text
Django==5.2.4
```

to:

```text
Django==5.2.16
```

Do not opportunistically upgrade unrelated dependencies in the same change.

## Validation sequence after approval

1. Change only the Django patch pin.
2. Create or use an isolated non-production Python environment.
3. Install the exact requirements without exposing environment secrets.
4. Run `python manage.py check` with a non-production configuration.
5. Run the GeoFlow Django test suite and the Phase 1 security/signup regression tests.
6. Run `python manage.py check_release_preflight --strict` with secret-safe non-production runtime configuration.
7. Exercise login, signup-unavailable, signup, verification, central approval, tenant selection, logout, event/attachment upload, and central-admin authorization smoke paths.
8. Confirm there is no migration requirement caused by the patch-only framework upgrade.
9. Deploy to a non-production environment first and observe application logs for framework-level regressions.
10. Only after the above passes should the production application deployment be considered.

## Rollback

The application package/version rollback must be possible independently from database migration rollback. This Django patch update is not expected to introduce a GeoFlow schema migration, so do not combine it with signup migrations or data cleanup in one production change window.

## Stop conditions

Do not proceed to public release when any of the following is true:

- runtime Django is below the approved 5.2 LTS security baseline;
- an unreviewed Django feature series is installed;
- `manage.py check` or the security regression suite fails;
- a framework patch changes behavior in login/session/CSRF/email/upload flows;
- a production-only secret or database connection is required merely to complete dependency validation.
