# GeoFlow Phase 2 Codex Autopilot

## Purpose

This document is the durable handoff for unattended Phase 2 work in Codex Local and Codex Cloud.

Always read the repository-root `AGENTS.md` first. It contains the controlling authorization, safety boundaries, and the full Phase 2 completion definition.

## Current baseline

- repository: `kotopia/geoflow_web`
- release branch: `release/stabilized-deploy`
- Phase 1: complete
- repository-level Phase 2 IAM/authorization hardening: complete unless a new confirmed defect is found
- full Phase 2 remains open until the operational acceptance criteria in `AGENTS.md` are satisfied, especially issues `#10`, `#11`, and `#28`
- do not assume the SHA written in an older chat is still current; fetch the remote release HEAD at task start
- the separate legacy iroomsng incident is closed and out of scope

## Cloud / Local task prompt

Use this as the starting task for Codex Cloud or a long-running local Codex thread:

> Continue GeoFlow Phase 2 autonomously from the exact current `release/stabilized-deploy` HEAD until the **full** Definition of Phase 2 Done in `AGENTS.md` is satisfied.
>
> First read `AGENTS.md`, then inspect the current release history, open Phase 2 issues (especially `#10`, `#11`, `#28`), open PRs, CI/workflow status, and the reviewed operational runbooks. Do not repeat fixes already merged.
>
> Repository authorization hardening may already be complete. Do **not** stop or disable the Phase 2 completion loop merely because repository-level IAM/authorization review is green. Continue independent preparation and verification for the remaining operational gates until their acceptance evidence exists.
>
> For each confirmed repository gap: create a topic branch from the exact current release HEAD; make the minimum code/test/CI/documentation change; run focused regression and safe repository checks; push the branch; open/update a PR; repair CI failures without weakening security; merge the PR only when latest-head required checks are green and the diff remains in scope; then re-read the new release HEAD.
>
> For operational work, use only the reviewed production-gated procedures. Never bypass the protected `production` Environment. If a production gate is waiting, leave it waiting for the authorized user approval and continue every independent safe item. If an AWS or repository-administration action cannot be executed with available tools, state the smallest exact user-only action required and continue other work instead of declaring Phase 2 complete.
>
> The remaining full-Phase-2 acceptance areas are: `#10` minimum-permission EC2 instance profile/runtime-role readiness and role-only cutover with post-cutover smoke; `#28` proxy/HTTPS/HSTS staged activation with post-activation smoke; `#11` actual release branch protection/ruleset enforcement and validation by a normal feature PR; then exact-latest-HEAD CI/preflight and public production smoke.
>
> Do not access or mutate production DBs, run production migrations, expose secrets, force-push release, bypass GitHub protections, or modify legacy iroomsng. Production EC2/IAM/Nginx/systemd/S3/credential mutations require the applicable protected operational approval and exact reviewed runbook.
>
> Do not create new permission codes, roles, tables, or migration/schema changes unless the existing canonical model cannot express a proven requirement. If a schema change is truly necessary, stop only that dependency at a concise design boundary and continue other independent Phase 2 work.
>
> When both repository-level and operational acceptance criteria in `AGENTS.md` are satisfied, perform a final exact-release audit, ensure latest release CI/preflight and public production smoke are green, record completion evidence on the relevant Phase 2 issues, and only then stop creating new Phase 2 changes.

## Operational issue map

### #10 — minimum-permission EC2 instance profile / role-only cutover

Use the reviewed templates and runbooks, including:

- `docs/phase2-runtime-iam-policy-template.json`
- `docs/phase2-ec2-trust-policy-template.json`
- `docs/phase2-ec2-instance-profile-setup.md`
- `.github/workflows/phase2-aws-role-readiness-diagnostic.yml`

Do not substitute production identifiers into repository files. Existing long-lived credentials remain available until role readiness, guarded cutover, and post-cutover validation have all succeeded.

### #28 — trusted proxy / HTTPS / HSTS

Run the reviewed read-only readiness diagnostic first. Activation order is:

1. proxy trust
2. Django SSL redirect
3. short-duration HSTS

Keep `includeSubDomains` and `preload` disabled unless every relevant subdomain has separately been proven HTTPS-only.

### #11 — release branch protection

Apply the reviewed Stage B repository policy through an approved repository-administration path and prove it with a normal feature PR. A repository contract file by itself is not acceptance evidence; GitHub must report the branch/ruleset as actually enforced.

## Checkpoint format

For each merged or operational unit of work, record internally or in the relevant issue/PR:

- confirmed gap or gate
- exact reviewed release SHA
- minimal change/action
- validation run and result
- PR number / merge SHA where applicable
- protected production gate status
- smallest remaining user-only action, if any

## User-facing completion report

When full Phase 2 is done, report only:

1. completion percentage (100% only when repository and operational criteria are all met)
2. merged PRs / key fixes and operational hardening completed
3. tests, release-preflight, and production smoke status
4. confirmation that `#10`, `#11`, and `#28` acceptance criteria are satisfied
5. Phase 3 entry point
