# GeoFlow Phase 3 Closeout

Status: **COMPLETE**

Closed on: 2026-08-16 (Asia/Seoul)

Release branch: `release/stabilized-deploy`

Reviewed pre-closeout release SHA: `09c62a5b617b24d5c90c9db0610bd2f6570edb2f`

## Scope closed

Phase 3 stabilized the existing multi-tenant runtime path and completed the reviewed safety contract for future tenant provisioning without enabling a production mutation path.

Completed scope includes:

- central login and existing-tenant selection/readiness verification
- active-group and active-membership eligibility checks
- existing tenant DB runtime through central `GroupDBConfig` metadata plus Secrets Manager secret references
- removal of the old requirement that a tenant such as `cheonan_db` must exist as a static `settings.DATABASES` entry
- login-account compatibility checks for current central users
- deterministic new-tenant database/role/secret-reference planning
- explicit existing-tenant and identifier-conflict protection
- read-only PostgreSQL, Secrets Manager metadata, IAM-grant, runtime-scope, and central-publication readiness boundaries
- immutable readiness binding to the exact execution target
- mandatory pre-lock readiness attestation
- per-group provisioning lock contract
- fresh read-only JIT readiness revalidation under the lock immediately before the first mutation
- explicit post-IAM-grant exact-policy readback before runtime credential resolution or DB connectivity
- `GroupDBConfig` publication as the final mutation
- publication outcome reconciliation before destructive compensation
- rollback limited to resources created by the current unpublished attempt
- disposable PostGIS/full-orchestrator rehearsals and race/failure regression coverage

## Existing-tenant operational evidence

The protected read-only Cheonan diagnostics completed successfully.

`Phase 3 Cheonan account readiness diagnostic`:

- run: `31841348188`
- job: `94898700411`
- result: success

Verified aggregate state:

- Cheonan group active: yes
- members: 5
- active central users: 5/5
- email verified: 5/5
- active memberships: 5/5
- invalid email syntax: 0
- outer email whitespace: 0
- normalized duplicate emails within Cheonan: 0
- password verifier compatible: 5/5
- full login prerequisites ready: 5/5
- password hashes: 5 PBKDF2, 0 blank/unusable/unknown

An earlier protected Cheonan tenant-readiness diagnostic also verified the current dynamic runtime shape: the central `GroupDBConfig` was complete, secret-reference resolution could connect to the tenant DB, and a static `cheonan_db` settings alias was not required.

## Tenant provisioning contract at closeout

The repository contains a reviewed provisioning orchestrator and backend contract, but **production provisioning remains deliberately unavailable by default**.

The immutable normal plan produced by `tenant_provisioning_contract.py` keeps `execution_available=False`. The public Django runtime also does not opt into `TENANT_PROVISIONING_EXECUTOR_MODE`; therefore an accidental feature-toggle change cannot reach backend mutations.

The reviewed execution sequence is:

1. validate bound read-only readiness attestation
2. acquire per-group provisioning lock
3. revalidate read-only readiness under the lock
4. create database role
5. create database
6. enable PostGIS
7. open explicit dynamic tenant migration context
8. apply tenant schema
9. create external secret
10. grant the runtime role exact secret read
11. read back and verify that exact grant
12. verify runtime secret resolution and DB connectivity
13. publish `GroupDBConfig` last

The reviewed rollback boundary only removes current-attempt resources that have not been published.

## Final repository hardening evidence

The final Phase 3 provisioning regression PR before closeout was:

- PR `#142`: `test: fail closed on JIT tenant publication race`
- merge SHA: `09c62a5b617b24d5c90c9db0610bd2f6570edb2f`

It proves that if the central publication target changes after the earlier readiness observation but before lock-scoped JIT revalidation, the attempt fails closed before the first tenant mutation and performs no destructive rollback because no resource is yet owned by the attempt.

The preceding hardening series included production-shaped read-only probes, exact secret-scope IAM verification, preexisting-grant rollback protection, publication reconciliation, execution-target binding, JIT revalidation, and disposable full-orchestrator rehearsals.

## Release validation

For release SHA `09c62a5b617b24d5c90c9db0610bd2f6570edb2f`, five push workflows completed successfully, including:

- `Tenant provisioning contract` run `31886476290`
- `Static tenant selection regression` run `31886476249`
- `Account security regression` run `31886476160`
- `Account password reset DB integration` run `31886476192`
- `Release preflight` run `31886476256`

No new Phase 3 CI blocker was present at the closeout baseline.

## Production boundary intentionally left closed

Phase 3 completion does **not** authorize or imply live new-tenant provisioning.

The following remain separate future operational work and require their own exact review/approval before any live execution:

- enabling a production-capable provisioning executor
- creating a live tenant database or database role
- running tenant schema migrations against a live new tenant
- creating or deleting live Secrets Manager secrets
- attaching/updating/removing live IAM grants
- publishing a new live `GroupDBConfig`
- any production DB schema/data mutation

Those actions are not required to declare Phase 3 complete. Phase 3 closes on the safety contract, isolated rehearsals, existing-tenant stability, and green release validation.

## Non-blocking follow-up items

These items are intentionally outside the Phase 3 blocker set:

- actual production enablement of new-tenant provisioning
- retirement of old AWS access keys after a separate dependency inventory and irreversible-hardening approval
- cleanup of obsolete Phase 2 launcher/workflow scaffolding
- Django `fields.W342` cleanup for `ForeignKey(unique=True)` models
- Level-2 live upload smoke that would require an approved S3 mutation
- broader product workflow, WebGIS/QGIS, contract/project, employee, and external-API features covered by Phase 4 design

Old stale Phase 2 protected runs that remain `waiting` are historical artifacts and must not be approved or reused.

## Phase 4 handoff

Phase 4 starts from the following stable architecture assumptions:

- central DB remains the control/auth/source-of-tenant-metadata plane
- tenant operational data remains isolated in tenant DBs
- tenant runtime source of truth is `GroupDBConfig -> Secrets Manager -> dynamic tenant connection`
- authorization and project/tenant scope remain fail-closed
- production-mutating operations remain explicit, protected, and separately approved

The current Phase 4 product/architecture draft is recorded in `docs/phase4-design-draft-v0.1.md`.

## Closeout decision

**Phase 3 is closed.**

New feature work should proceed as Phase 4. Phase 3 should only be reopened for a regression directly attributable to the multi-tenant runtime/provisioning safety work documented above.