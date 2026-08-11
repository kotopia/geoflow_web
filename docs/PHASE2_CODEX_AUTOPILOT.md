# GeoFlow Phase 2 Codex Autopilot

## Purpose

This document is the durable handoff for unattended Phase 2 work in Codex Local and Codex Cloud.

Always read the repository-root `AGENTS.md` first. It contains the controlling authorization and safety boundaries.

## Current baseline

- repository: `kotopia/geoflow_web`
- release branch: `release/stabilized-deploy`
- Phase 1: complete
- Phase 2: IAM / authorization hardening in progress
- do not assume the SHA written in an older chat is still current; fetch the remote release HEAD at task start
- the separate legacy iroomsng incident is closed and out of scope

## Cloud / Local task prompt

Use this as the starting task for Codex Cloud or a long-running local Codex thread:

> Continue GeoFlow Phase 2 autonomously from the exact current `release/stabilized-deploy` HEAD until the Definition of Phase 2 Done in `AGENTS.md` is satisfied.
>
> First read `AGENTS.md`, then inspect the current release history, open PRs, CI workflows, canonical permission definitions, tenant URL routing, authorization helpers, and existing security regression tests. Do not repeat fixes already merged.
>
> Work in small independent authorization issues. For each confirmed gap: create a topic branch from the exact current release HEAD; make the minimum code/test/CI change; run focused regression and safe repository checks; push the branch; open/update a PR; repair CI failures without weakening security; merge the PR only when latest-head required checks are green and the diff remains in scope; then re-read the new release HEAD and continue with the next unfinished Phase 2 item.
>
> Prioritize: cross-tenant or direct-route bypasses, missing write authorization, missing read authorization, permission-taxonomy mismatches, role-to-effective-permission inconsistencies, stale-cache/fail-closed defects, then CI/preflight coverage.
>
> Do not stop for routine progress reports. Do not ask for per-PR approval. The user has granted Phase 2 code/test/branch/PR/CI retry/merge authority as recorded in `AGENTS.md`.
>
> Keep production boundaries intact. Do not access or mutate production DBs, run production migrations, restart/deploy production services, alter EC2/Nginx/systemd, change S3/IAM/credentials, expose secrets, bypass GitHub Environment protection, or modify legacy iroomsng. If a protected production gate is generated, leave it waiting and continue all independent repository work.
>
> Do not create new permission codes, roles, tables, or migration/schema changes unless the existing canonical model cannot express a proven requirement. If a schema change is truly necessary, stop only that dependency at a concise design boundary and continue other independent Phase 2 work.
>
> When all Definition of Phase 2 Done criteria are met, perform a final repository-wide authorization audit, ensure latest release CI/preflight is green, write a concise completion report, and stop creating new Phase 2 changes.

## Checkpoint format

For each merged unit of work, record internally or in the PR:

- confirmed gap
- why it was reachable
- minimal fix
- regression added
- validation run
- PR number
- merge SHA
- whether a production gate is waiting

## User-facing completion report

When Phase 2 is done, report only:

1. completion percentage (100% if all criteria are met)
2. merged PRs / key fixes
3. tests and release-preflight status
4. any protected production action still waiting
5. Phase 3 entry point
