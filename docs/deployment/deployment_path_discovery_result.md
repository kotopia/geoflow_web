# Deployment Path Discovery Result

## 1. Scope

- Performed a read-only repository and Git configuration review.
- Did not contact the configured Git remote.
- Did not connect to a server or execute a deployment.
- Did not read or print `.env` contents.
- Did not record remote URLs, domains, credentials, connection values, or infrastructure identifiers.

## 2. Repository Discovery

| check | result |
|---|---|
| Git remote configured | yes |
| configured remote count | 1 |
| current branch | `phase2-clean-base` |
| `manage.py` | present at repository root |
| `requirements.txt` | present at repository root |
| WSGI entry point | present |
| ASGI entry point | present |
| deployment-specific documentation | not found |
| deployment script | not found |

- The remote URL was intentionally not printed or recorded.
- The configured remote target and deployment branch policy must be confirmed locally before any clone, fetch, pull, or push operation.

## 3. Python Runtime Dependency Discovery

- `requirements.txt` exists and contains the Django and PostgreSQL adapter foundation.
- A production WSGI server package is not declared.
- Gunicorn is not declared.
- uWSGI is not declared.
- Uvicorn and Daphne are not declared.
- WhiteNoise is not declared.
- The repository includes S3 integration code, but its required AWS SDK package is not declared in the inspected requirements file.
- Production deployment must not rely on undeclared packages installed manually on an operator workstation or server.

## 4. Static File Discovery

| setting | result |
|---|---|
| `STATIC_URL` | configured |
| `STATICFILES_DIRS` | configured |
| `STATIC_ROOT` | configured |
| `collectstatic` procedure in repository | not found |
| WhiteNoise integration | not found |

- The settings provide the paths required for Django static collection.
- A production deployment needs an explicit `collectstatic` step.
- The collected static directory should be served by Nginx or another reviewed static-file layer rather than the Django development server.
- Static collection must be validated in a release workspace without recreating intentionally removed or prohibited artifacts.

## 5. Deployment Artifact Discovery

| artifact category | result |
|---|---|
| Gunicorn configuration | absent |
| Nginx configuration | absent |
| systemd service or socket unit | absent |
| uWSGI configuration | absent |
| Dockerfile | absent |
| Docker Compose configuration | absent |
| Procfile | absent |
| repository deployment script | absent |

- The repository is not currently packaged as a container deployment.
- It also does not contain a complete host-based service definition.
- Deployment is therefore not a single existing command and requires a separately reviewed production runbook and infrastructure configuration.

## 6. EC2 Deployment Candidate Procedure

The following is a candidate procedure only. It was not executed.

1. Confirm the release branch and exact reviewed commit without changing the current worktree.
2. Confirm the configured Git remote locally without copying its URL into documentation.
3. Provision a supported Python runtime and required operating-system libraries for Django, PostgreSQL, and GeoDjango.
4. Create an isolated virtual environment owned by the application deployment identity.
5. Install only pinned and reviewed dependencies from the repository dependency definition.
6. Add and review a production WSGI server dependency before deployment; Gunicorn is the primary candidate for a Linux EC2 host.
7. Resolve the undeclared AWS SDK dependency before enabling repository S3 flows.
8. Supply production configuration through an approved secret-management mechanism without printing `.env` contents.
9. Complete the production environment checklist, including debug, allowed hosts, CSRF origins, secure cookies, TLS termination, and trusted proxy decisions.
10. Run safe Django configuration and deployment checks in the release environment.
11. Run `collectstatic` as an explicit release step and verify the collected output path.
12. Configure Gunicorn to load the repository WSGI application under a restricted service account.
13. Configure a systemd service with explicit working directory, environment source, restart policy, and least-privilege ownership.
14. Configure Nginx as the trusted reverse proxy, TLS endpoint, and static-file server.
15. Confirm whether HTTPS redirect is enforced at Nginx or Django and avoid duplicate or looping redirects.
16. Configure `SECURE_PROXY_SSL_HEADER` only if the trusted proxy overwrites the forwarded protocol header and direct application access is blocked.
17. Configure security groups and host firewall rules so the application server is not directly exposed when Nginx is the public entry point.
18. Validate health, login, tenant routing, static assets, and controlled read-only application paths.
19. Keep database migration execution outside the generic deployment command until each central or tenant migration scope is separately reviewed and approved.
20. Record rollback steps for application release, static assets, service configuration, and database operations separately.

## 7. Database and Multi-tenant Deployment Constraints

- This repository uses central and tenant database routing and dynamic tenant connection behavior.
- A generic `migrate` command must not be assumed to cover the correct database scope.
- Broad all-tenant migration remains prohibited under the current stabilization policy.
- Central and tenant migration plans require separate target selection, precheck, backup readiness, execution approval, and postcheck.
- Application deployment and database migration should remain separate release gates.
- No database operation was performed during this discovery task.

## 8. Current Recommended Deployment Path

- Recommended host model: Linux EC2 with an isolated Python virtual environment.
- Recommended application server: Gunicorn using the existing WSGI entry point, after adding and pinning the dependency in a separately approved change.
- Recommended service manager: systemd with a restricted application identity.
- Recommended reverse proxy and static server: Nginx.
- Recommended TLS model: terminate TLS at a reviewed trusted edge or Nginx configuration, then configure Django secure-request detection consistently.
- Recommended release source: an explicitly approved commit from the configured Git remote and release branch policy.
- Recommended static flow: explicit `collectstatic`, followed by Nginx serving the collected directory.
- Recommended secret flow: a reviewed secret-management mechanism; never copy secret values into Git or documentation.
- Docker is not the immediate recommendation because the repository contains no container build or orchestration artifacts.

## 9. Blocking Gaps Before Deployment

- No production WSGI server dependency or configuration is present.
- No systemd unit is present.
- No Nginx configuration is present.
- No deployment runbook or script is present.
- No repository `collectstatic` procedure is present.
- HTTPS redirect ownership and trusted proxy behavior are not yet decided.
- Production hostnames and CSRF origins require deployment-specific configuration.
- The S3 runtime dependency declaration requires review.
- Database migration execution must remain separately controlled for the multi-tenant architecture.

## 10. Recommended Next Work

- Prepare a non-executing EC2 deployment runbook design.
- Separately design the minimal dependency change for a pinned production WSGI server and required S3 runtime packages.
- Prepare reviewed systemd and Nginx configuration templates without embedding domains, paths tied to a person, credentials, or secret values.
- Define the release branch and commit-selection policy.
- Keep deployment execution, server access, dependency installation, and migration execution outside the discovery scope until separately approved.

## 11. Safety Notes

- No code or test was modified.
- No server or Git remote was contacted.
- No git pull, push, add, commit, fetch, or deployment action was performed.
- No database write, migration, or schema operation was performed.
- No endpoint or browser execution was performed.
- No `.env` content was read or printed.
- No remote URL, hostname, database value, user, password, key, token, tenant alias, UUID, email, session value, or raw error was recorded.
