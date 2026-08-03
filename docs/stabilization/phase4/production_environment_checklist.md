# Production Environment Checklist

## 1. Usage

- Complete this checklist before production deployment.
- Record only completion status in deployment records.
- Never copy environment values, credentials, keys, tokens, or connection strings into this document.
- Do not print or attach the actual `.env` file.

## 2. Django Core Settings

- [ ] `DJANGO_DEBUG` is explicitly false in production.
- [ ] `DJANGO_SECRET_KEY` exists and is supplied through an approved secret-management process.
- [ ] `DJANGO_ALLOWED_HOSTS` contains only the required production hostnames.
- [ ] `DJANGO_ALLOWED_HOSTS` does not use an unnecessarily broad wildcard.
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` contains the required HTTPS origins when the deployment topology requires them.
- [ ] CSRF trusted origins are narrowly scoped and include the URL scheme.
- [ ] No secret or actual environment value is included in deployment documentation.

## 3. Secure Cookies

- [ ] `DJANGO_SESSION_COOKIE_SECURE` remains true in production.
- [ ] `DJANGO_CSRF_COOKIE_SECURE` remains true in production.
- [ ] Production traffic is served over HTTPS before secure-cookie behavior is validated.
- [ ] No production override disables secure session or CSRF cookies.

## 4. HTTPS Redirect and Trusted Proxy

- [ ] The TLS termination point is documented without recording sensitive infrastructure identifiers.
- [ ] HTTPS redirect responsibility is assigned to either the trusted edge or Django.
- [ ] Redirect behavior is decided only after the edge and proxy request flow is confirmed.
- [ ] If the edge enforces HTTPS, its redirect and health-check behavior is validated operationally.
- [ ] If Django must enforce HTTPS, a separately reviewed environment-driven `SECURE_SSL_REDIRECT` implementation is approved before deployment.
- [ ] `SECURE_PROXY_SSL_HEADER` is used only when Django receives traffic exclusively through a trusted proxy that overwrites the forwarded protocol header.
- [ ] Proxy secure-request detection and redirect behavior are tested together to prevent redirect loops.
- [ ] Client-supplied forwarded protocol headers cannot bypass the trusted proxy boundary.

## 5. Central Database Environment Variable Names

Record presence and secret-manager ownership only. Do not record values.

- [ ] `CENTRAL_DB_NAME`
- [ ] `CENTRAL_DB_HOST`
- [ ] `CENTRAL_DB_PORT`
- [ ] `CENTRAL_DB_USER`
- [ ] `CENTRAL_DB_PASSWORD`

## 6. Tenant Database Environment Variable Names

Record presence and secret-manager ownership only. Do not record values.

- [ ] `TENANT_DB_NAME`
- [ ] `TENANT_DB_HOST`
- [ ] `TENANT_DB_PORT`
- [ ] `TENANT_DB_USER`
- [ ] `TENANT_DB_PASSWORD`

## 7. Provisioner Database Environment Variable Names

These variables are security-sensitive and require least-privilege review. Record no values.

- [ ] `PROVISIONER_DB_HOST`
- [ ] `PROVISIONER_DB_PORT`
- [ ] `PROVISIONER_DB_USER`
- [ ] `PROVISIONER_DB_PASSWORD`
- [ ] Provisioner credentials are unavailable to application processes that do not require them.
- [ ] Provisioner permissions are limited to the explicitly approved operational scope.

## 8. RRN Encryption Key

- [ ] `RRN_SYM_KEY` exists in the approved production secret store.
- [ ] The application process can access the key through the approved runtime mechanism.
- [ ] The key value is not printed, logged, committed, or copied into documentation.
- [ ] The key is not rotated as part of deployment unless a separately approved data-migration plan exists.

## 9. S3 Environment Variable Names

Record presence and secret-manager ownership only. Do not record values.

- [ ] `AWS_ACCESS_KEY_ID`
- [ ] `AWS_SECRET_ACCESS_KEY`
- [ ] `AWS_REGION`
- [ ] `AWS_S3_BUCKET`
- [ ] `AWS_KMS_KEY_ID`, when KMS encryption is required
- [ ] Runtime IAM permissions follow least privilege.
- [ ] Bucket and object access are not made public by deployment configuration.
- [ ] No presigned URL, object key, bucket identifier, or credential value is placed in deployment records.

## 10. Secret Handling

- [ ] The actual `.env` contents are never printed or attached to tickets, logs, or documentation.
- [ ] Database passwords, Django secrets, encryption keys, AWS credentials, and tokens are stored in an approved secret-management system.
- [ ] Application logs do not include environment values, database connection details, credentials, session values, or raw debug tracebacks.
- [ ] Secret access is limited to the runtime identity and responsible operators.
- [ ] Secret rotation and rollback procedures are documented separately without including secret values.

## 11. Pre-deployment Decision Gate

- [ ] Production hostnames and CSRF origins are approved.
- [ ] `DJANGO_DEBUG` is false.
- [ ] Secure cookies remain enabled.
- [ ] TLS termination and redirect ownership are confirmed.
- [ ] Trusted proxy behavior is confirmed before configuring `SECURE_PROXY_SSL_HEADER`.
- [ ] Required database, encryption, and S3 environment variable names are present.
- [ ] No secret value appears in source control or deployment documentation.
- [ ] A responsible operator has approved the completed checklist.

## 12. Safety Notes

- This checklist records environment variable names only.
- No `.env` content was read or printed.
- No host, database name, user, password, key, token, bucket identifier, tenant alias, UUID, email, session value, or raw error was recorded.
- No code or test was modified.
- No database write, migration, or schema operation was performed.
- No endpoint or browser execution was performed.
- No S3 access was performed.
- No git add, commit, or push was performed.
