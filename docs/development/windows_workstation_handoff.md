# GeoFlow Windows Workstation Handoff

Status date: 2026-08-09

This document is for moving GeoFlow development from one Windows PC to another without copying machine-specific state into Git.

## What follows the repository automatically

After cloning `kotopia/geoflow_web` and checking out `release/stabilized-deploy`, the new workstation receives the application code, migrations, tests, deployment templates, CI configuration, documentation, and the reviewed dependency pins in `requirements.txt`.

The current Phase 1 release branch is intentionally designed so that the working directory itself is not a trusted configuration source. A different absolute path on the new PC is acceptable.

## What does NOT follow Git automatically

The following are intentionally ignored or machine-specific and must be configured once on the new PC:

- `.env` and other secret-bearing environment files
- `.venv` / `venv`
- VS Code local workspace settings under `.vscode/`
- GitHub authentication used for push/write operations
- GitHub Copilot or other editor extension sign-in
- native GeoDjango runtime libraries required by Windows (GDAL/GEOS and their DLL search path)
- optional AWS CLI/profile credentials, VPN configuration, certificates, or local DB client configuration if the workstation actually uses them
- any OpenRouter or other local AI-tool credentials stored outside Git

Do not commit any of these simply to make workstation migration easier.

## Recommended new-PC sequence

1. Install Git.
2. Install 64-bit Python 3.12. CI currently validates GeoFlow on Python 3.12.
3. Install VS Code if that remains the development editor.
4. Clone the repository into a normal local path, for example `C:\GeoFlow\geoflow_web`. The exact path is not authoritative.
5. Check out `release/stabilized-deploy` and pull only after confirming the branch.
6. Run `scripts\windows\setup_workstation.ps1 -Bootstrap` from the repository root. This creates a new `.venv` and installs the pinned Python dependencies; it does not create or print `.env`.
7. Configure the native Windows GDAL/GEOS runtime. Run the setup script again to verify whether both libraries can be imported.
8. Transfer or recreate the local `.env` through a secure channel. Do not send its contents through chat, Git, email, tickets, or documentation. The file belongs at the repository root because `settings.py` resolves it relative to `BASE_DIR`.
9. Sign in to GitHub on the new PC using the normal supported credential flow. Do not blindly copy a private SSH key from the old notebook unless there is a specific key-management reason to retain that identity.
10. Sign in to GitHub Copilot/other required editor tooling separately if used.
11. Run `scripts\windows\setup_workstation.ps1 -Validate` after `.env` and GeoDjango libraries are present.
12. Confirm `git status --short` is clean before beginning new work.

## Old notebook shutdown checklist

Before retiring the old notebook as the primary development machine:

- ensure all intended source changes are committed to the correct branch
- ensure no useful source file exists only in an ignored directory
- securely transfer only the local configuration that is genuinely still required
- do not copy `.venv`; recreate it on the new PC
- do not copy `__pycache__`, `staticfiles`, logs, dumps, or other generated data
- do not delete the old `.env` until the new PC has been validated, but keep it protected and remove it when the notebook is decommissioned according to your credential policy

## Validation boundary

The workstation setup script is deliberately non-destructive. It never runs:

- `migrate`
- `makemigrations`
- tenant provisioning/deprovisioning
- S3 object mutation
- SMTP delivery
- EC2 deployment/restart
- credential rotation

`-Validate` runs local configuration checks only. Production/non-production database audits remain separate operational gates.

## Expected result

After the one-time setup above, continuing GeoFlow work from the new PC should be operationally equivalent to continuing from the old notebook. You do not need to recreate project history or manually copy the repository; Git is the source of truth for source-controlled material.
