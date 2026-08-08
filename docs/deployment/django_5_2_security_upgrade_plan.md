# Django 5.2 LTS security upgrade result

Status date: 2026-08-09

## Repository state

- `requirements.txt` now pins `Django==5.2.16`.
- GeoFlow remains on the reviewed Django 5.2 LTS feature series for this release-stabilization phase.
- `check_release_preflight --strict` requires at least Django 5.2.16 and rejects older 5.2 patches or an unreviewed feature series.
- No GeoFlow migration file was added or changed as part of the patch-only framework pin update.

## Security basis

Django 5.2.16 is the current 5.2 LTS patch listed by the official Django 5.2 release documentation as of 2026-08-09. The patch pin was updated independently from schema/data work so application rollback remains separable from migration rollback.

Official references:

- https://docs.djangoproject.com/en/5.2/releases/
- https://www.djangoproject.com/download/

## Change boundary completed

Only the Django requirement was changed in `requirements.txt`:

```text
Django==5.2.4
```

became:

```text
Django==5.2.16
```

Unrelated dependency pins were left unchanged.

## Validation still requiring an executable GeoFlow runtime

The connected execution container used for repository work does not contain the GeoFlow checkout, Django runtime dependencies, or GeoFlow environment variables, and outbound DNS is unavailable. Therefore package installation and Django execution were not fabricated or replaced by production access.

When an isolated executable checkout is available, run in this order:

1. install the exact `requirements.txt`;
2. `python manage.py check`;
3. Phase 1 signup/security regression tests;
4. `python manage.py check_release_preflight --strict`;
5. read-only DB audits only after a specifically selected non-production DB is available;
6. application smoke tests in non-production before production deployment.

## Stop conditions

Do not proceed to public release when any of the following is true:

- the installed runtime is not Django 5.2.16 or a later explicitly reviewed 5.2 security patch;
- `manage.py check`, regression tests, or strict release preflight fail;
- a framework patch changes behavior in login/session/CSRF/email/upload flows;
- validation depends on exposing a production secret; or
- application rollback cannot be performed independently from irreversible database work.
