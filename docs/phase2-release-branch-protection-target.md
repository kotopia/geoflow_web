# Phase 2 release branch protection target

Target branch: `release/stabilized-deploy`

This file records the intended protection contract after PR validation. It does not apply repository settings by itself.

## Required pull-request checks

Require these exact job/check names before merge:

- `release-preflight`
- `migration-rehearsal`
- `public-https-smoke`

These checks have been proven to run on a real pull request targeting the release branch.

## Target merge policy

- Require a pull request before merging.
- Require the three checks above to pass.
- Block force pushes.
- Block branch deletion.
- Do not allow bypass by default.
- Keep the existing `production` GitHub Environment protection for operational workflows.
- Prefer requiring the branch to be up to date before merge once the normal PR workflow is stable enough that this does not create excessive churn.

## Rollout order

1. Enable force-push and deletion protection first if not already enforced.
2. Confirm at least one real PR continues to emit all three checks.
3. Require pull requests and the three checks.
4. Confirm a normal feature PR can merge only after the required checks pass.
5. Retain a documented break-glass procedure instead of routine administrator bypass.

## Current connector limitation

The connected GitHub tooling used for this maintenance session can inspect repository rulesets and PR/CI state but does not expose a branch-protection or ruleset mutation action. Repository protection must therefore remain a repository-administration step unless that capability becomes available through an approved management path.
