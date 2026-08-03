# Deployment Log Sensitive Exposure Review Result

## 1. Scope

- Performed a read-only static review of repository logging configuration and production code log calls.
- Reviewed likely Django, Gunicorn, Nginx, and systemd exposure paths for a future EC2 deployment.
- Did not read an actual log file, call an endpoint, start a browser, contact a server, or execute a deployment.
- Did not read or print `.env` contents.
- No runtime identifier, secret, raw traceback, or infrastructure value is included in this document.

## 2. Django Logging Configuration

| check | result |
|---|---|
| explicit `LOGGING` setting | present |
| console stream handler | present |
| root logger level | warning |
| `control` logger level | info |
| middleware logger level | info |
| authentication logger level | info |
| database router logger level | debug |
| operational application logger level | debug |
| existing Django loggers disabled | no |

- Django `DEBUG=False` prevents the detailed technical error page from being returned to ordinary clients.
- `DEBUG=False` does not suppress Python exception tracebacks written by `logger.exception()` or framework error loggers.
- Two named production logger families remain configured at DEBUG level independently of the Django `DEBUG` setting.
- A formatter is declared, but the reviewed console handler does not explicitly reference it.
- Console output is the expected input to a future Gunicorn or systemd journal pipeline.

## 3. Production Code Log-call Inventory

The static inventory excluded test and migration files.

| call type | count | dynamically formatted call count |
|---|---:|---:|
| executable `print()` | 0 | 0 |
| `logger.debug()` | 9 | 0 |
| `logger.info()` | 18 | 2 |
| `logger.warning()` | 41 | 10 |
| `logger.error()` | 0 | 0 |
| `logger.exception()` | 10 | 0 |
| `logger.critical()` | 0 | 0 |

- No direct traceback formatting helper was found in the reviewed production Python files.
- The ten `logger.exception()` calls use fixed messages, but Python automatically appends exception details and tracebacks.
- A fixed message does not sanitize the attached exception text.
- Exception text from database, network, filesystem, or object-storage libraries can contain operational identifiers even when the application message is fixed.

## 4. Application-level Sensitive Value Review

| risk category | static finding | assessment |
|---|---|---|
| request path logging | no direct application log call found | low in application code; framework and proxy logs remain relevant |
| query or request payload logging | no direct application log call found | low in application code |
| session logging | no direct application log call found | low in reviewed application code |
| identity values | no direct dynamic UUID, email, or raw user identifier log call found | low in reviewed application code |
| tenant routing | fixed sanitized route-state messages found | currently controlled |
| database routing | fixed messages found, but router logger is DEBUG | content controlled; volume and future regression risk remain |
| S3 and attachment operations | fixed sanitized messages found | current message content controlled |
| presigned URLs and object keys | no direct dynamic logging call found | currently controlled |
| exception tracebacks | ten application exception log calls | medium to high residual exposure risk |

- The reviewed tenant routing messages do not directly interpolate an alias, tenant label, group identifier, session value, or request path.
- The reviewed upload and attachment messages do not directly interpolate a bucket, object key, attachment identifier, or presigned URL.
- The current result does not guarantee future safety; new log calls require review before merge and deployment.

## 5. Settings Initialization Log Risks

- Settings initialization currently emits whether a dotenv file was loaded together with its resolved filesystem path.
- GeoDjango diagnostic branches can emit environment-derived library paths and selected operating-system path entries.
- Tenant database diagnostics can emit a fallback host or port under specific conditions.
- These values are not application business data, but they reveal deployment layout or connection metadata and should not be emitted at production INFO or WARNING levels.
- The settings module also contains warning branches that include imported library exception text, which can reveal filesystem details.
- No actual setting value or exception text was copied into this document.

## 6. Django Request and Exception Logging

- No repository-specific `django.request` masking filter or formatter was found.
- No repository-specific `django.server` production configuration was found.
- A Django error response with `DEBUG=False` is sanitized for the client, but the server-side exception logger can still record the path and traceback.
- Query strings should be treated as sensitive because authentication tokens, search terms, identifiers, or callback values can be placed in a URL by mistake.
- Application routes should not accept secrets in URL paths or query parameters.
- Framework exception logs must be protected through access control, retention, and downstream redaction rather than relying only on `DEBUG=False`.

## 7. Gunicorn Log Exposure Review

- No Gunicorn package, configuration file, or service command is currently present in the repository.
- Gunicorn error output can contain application exception tracebacks and is commonly forwarded to systemd journal.
- Gunicorn access logging is often disabled by default but may be enabled during deployment.
- A common access-log request-line field contains the complete request target, including the query string.
- Production access logging must not include request headers, cookies, authorization values, request bodies, or full query strings.
- If an access log is required, use a reviewed minimal format containing method, sanitized path, status, response size, duration, and a non-sensitive correlation identifier.
- Do not place credentials or tokens in the Gunicorn command line or environment arguments displayed by process-management tools.

## 8. Nginx Log Exposure Review

- No Nginx configuration is currently present in the repository.
- Standard combined access formats commonly log the full request line, which includes query strings.
- A future Nginx access format should use a query-free path field where feasible and must not log cookies, authorization headers, request bodies, or upstream secret headers.
- Sensitive endpoints can use access-log suppression or a separate strictly minimized log policy when operationally justified.
- Error log level should normally remain at warning or error in production rather than debug.
- Nginx configuration dumps and diagnostic commands must not be copied into tickets if they contain environment-specific endpoints or credentials.

## 9. systemd Journal Exposure Review

- No systemd unit is currently present in the repository.
- Future Gunicorn stdout and stderr will normally be captured by the journal unless configured otherwise.
- Application tracebacks, settings initialization messages, and proxy diagnostics can therefore persist in journal storage.
- Secrets must never be passed as command-line arguments in `ExecStart`.
- A protected environment file or an approved secret-delivery mechanism should be used instead of embedding values in a unit file.
- Unit files, environment files, and journal access require least-privilege filesystem and operator permissions.
- Journal retention, rotation, forwarding, and deletion policies must be defined before production launch.
- Operators must not use commands that dump the complete service environment into support logs.

## 10. Risk Classification

| risk | current level | reason |
|---|---|---|
| detailed client debug page | low | debug defaults to false |
| application fixed-message identifier leakage | low | reviewed route, upload, contract, event, and employee messages are sanitized |
| traceback and exception-text leakage | medium to high | ten `logger.exception()` calls and framework error logging remain |
| settings and filesystem diagnostic leakage | medium | environment-derived paths and limited connection diagnostics can be logged |
| access-log query-string leakage | unresolved | Gunicorn and Nginx policy is not yet defined |
| journal persistence and operator access | unresolved | systemd unit and retention policy are not yet defined |
| future logging regression | medium | two application logger families are configured at DEBUG level |

## 11. Required Pre-deployment Log Policy

- Keep `DJANGO_DEBUG` false in production.
- Set normal application logger levels to INFO or WARNING; do not keep broad application or router DEBUG logging enabled.
- Preserve WARNING or ERROR visibility for authorization denial, fail-closed routing, and connection-unavailable events using fixed messages.
- Review each `logger.exception()` site and decide whether a fixed sanitized error log without traceback is sufficient for expected failures.
- For unexpected failures that retain tracebacks, restrict storage, access, forwarding, and retention and apply downstream redaction.
- Remove or lower production settings diagnostics that emit environment-derived paths, host data, or port data.
- Define a query-free or query-redacted Gunicorn and Nginx access-log format before enabling access logs.
- Never log request bodies, form errors containing submitted values, cookies, authorization headers, session contents, presigned URLs, object keys, credentials, or database connection dictionaries.
- Use a generated non-sensitive request correlation identifier rather than a business identifier.
- Restrict journal and log-file access to responsible operators and the log-forwarding service identity.
- Define retention and rotation periods appropriate to security and incident-response needs.
- Add a release review that rejects dynamic log interpolation of tenant aliases, labels, database metadata, identity values, storage identifiers, and request data.

## 12. Recommended Next Action

- Prepare a separately scoped minimal production logging hardening design.
- The design should cover logger level overrides, settings diagnostic removal, exception traceback policy, and minimal Gunicorn/Nginx formats.
- Do not implement proxy or service logging until the deployment architecture and trusted operator boundary are confirmed.
- Add DB-free tests for sanitized fixed messages where production log behavior is security-critical.
- Keep any code modification separate from this read-only review.

## 13. Safety Notes

- No code or test was modified.
- No actual log file was opened or printed.
- No server, Git remote, endpoint, browser, database, or S3 service was contacted.
- No database write, migration, or schema operation was performed.
- No `.env` content was read or printed.
- No host, database value, user, password, key, token, tenant alias, tenant label, UUID, email, session value, object key, presigned URL, or raw traceback was recorded.
- No git add, commit, or push was performed.
