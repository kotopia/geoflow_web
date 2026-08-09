# Phase 1 GitHub Actions host preflight

Status date: 2026-08-09

This workflow provides a read-only SSH bridge from GitHub Actions to the reviewed GeoFlow application host before any Phase 1 deployment is attempted.

Workflow:

- `.github/workflows/phase1-host-preflight.yml`
- manual `workflow_dispatch` only
- restricted to `release/stabilized-deploy`
- uses the GitHub `production` environment

## Required production environment secrets

Create the GitHub environment `production`, then add these environment secrets without pasting their values into chat, source files, issues, or workflow logs:

- `GEOFLOW_DEPLOY_HOST`
- `GEOFLOW_DEPLOY_USER`
- `GEOFLOW_DEPLOY_SSH_KEY`
- `GEOFLOW_DEPLOY_KNOWN_HOSTS`

`GEOFLOW_DEPLOY_KNOWN_HOSTS` must come from a previously trusted host-key source. Do not replace strict host verification with `StrictHostKeyChecking=no` merely to make the workflow connect.

Prefer a dedicated deployment SSH key with only the host permissions needed for GeoFlow release operations. Do not commit the key or copy it into repository files.

The workflow accepts an SSH port input and defaults to 22.

## What the workflow reads

It verifies only non-secret host/runtime metadata needed to establish the deployment path:

- candidate repository SHA in the Actions runner
- SSH connectivity under strict known-host verification
- presence of Git, Python, systemd, and Nginx commands
- expected checkout at `/srv/geoflow/current`
- currently deployed commit and branch
- count of uncommitted files, without printing their contents
- expected virtualenv at `/srv/geoflow/venv`
- existence of `/etc/geoflow/geoflow.env`, without reading or printing the file
- selected `geoflow` systemd state/path metadata
- Nginx version and configuration syntax test when permissions allow it

## What it never does

The host preflight does not:

- fetch or checkout a new application commit on the host
- install packages
- run `collectstatic`
- run migrations or DDL
- read `.env` or `/etc/geoflow/geoflow.env` contents
- query a database
- mutate S3
- send SMTP mail
- restart or reload Gunicorn, systemd services, or Nginx
- rotate credentials
- enable public signup

## Execution order

1. Confirm the latest `release/stabilized-deploy` preflight and disposable migration rehearsal still pass.
2. Configure the `production` environment and required secrets through the GitHub UI or another trusted GitHub secret-management path.
3. Manually run **Phase 1 host preflight** on `release/stabilized-deploy`.
4. Review the read-only output. If expected paths or service names differ from the prepared templates, update the deployment procedure before performing any mutation.
5. Only after this host preflight succeeds should Approval A application deployment commands be enabled/executed.
6. Approval B and later phases remain blocked until Approval A finishes successfully.

This workflow is intentionally separated from automatic push deployment so repository commits cannot restart production merely by being pushed.
