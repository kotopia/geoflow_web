# Phase 2 release PR check validation

This documentation-only change exists to verify that pull requests targeting `release/stabilized-deploy` emit the three required release checks before branch protection Stage B is enabled.

Expected checks:

- `release-preflight`
- `migration-rehearsal`
- `public-https-smoke`

No production configuration, database, credentials, deployment files, or application runtime behavior are changed by this validation.
