# GeoFlow Phase 2: release branch protection Stage B

## Verified state

As of 2026-08-10, `release/stabilized-deploy` has no repository ruleset configured. The release workflow is configured to run for every pull request targeting that branch, and real pull requests have emitted and passed the three intended required checks.

Required status-check job IDs:

- `release-preflight`
- `migration-rehearsal`
- `public-https-smoke`

These identifiers are branch-protection API/UI contracts. Renaming any of them after protection is enabled can leave pull requests waiting for a status that no workflow emits. `control/test_release_branch_protection_contract.py` therefore guards both the exact job IDs and the absence of pull-request path filters.

## Stage B target configuration

Apply protection only to `release/stabilized-deploy` with the following behavior:

1. Require a pull request before changes reach the branch.
2. Require the three checks listed above to pass.
3. Block force pushes / non-fast-forward updates.
4. Block branch deletion.
5. Do not configure a normal administrator bypass. A break-glass path should be explicit and separately documented if it is ever needed.
6. Keep the existing GitHub `production` Environment approval gate separate from branch protection. Release CI itself must not require production approval.

Whether to require the pull-request branch to be fully up to date with `release/stabilized-deploy` before merge is an operational strictness choice. Enabling it gives the strongest merge-base assurance but causes an additional CI cycle when the release branch moves. It can be enabled independently without changing the three required check identifiers.

## Pre-apply acceptance checklist

Before turning on Stage B:

- repository rulesets are still absent or the existing ruleset has been explicitly reviewed;
- `release-preflight.yml` contains an unfiltered `pull_request` trigger for `release/stabilized-deploy`;
- `release-preflight`, `migration-rehearsal`, and `public-https-smoke` all exist as top-level jobs;
- a current real PR to `release/stabilized-deploy` emits and passes all three;
- no required release check waits on the `production` Environment;
- the branch-protection contract test is green.

## Post-apply validation

After protection is enabled, create a small repository-only PR targeting `release/stabilized-deploy` and verify:

- direct merge is blocked until required checks pass;
- all three required checks are emitted automatically;
- successful checks allow merge according to the configured review policy;
- force push and branch deletion are blocked;
- production workflows continue to use their independent `production` Environment gate.

Do not test branch protection by force-pushing or deleting the real release branch. Validation should be through the ruleset configuration and ordinary PR behavior.
