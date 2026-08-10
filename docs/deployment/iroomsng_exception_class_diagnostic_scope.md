# iroomsng exception class diagnostic scope

This diagnostic exists only to narrow the already-confirmed legacy iroomsng Gunicorn worker-boot failure.

It is read-only and production-gated. It reads bounded recent journal data for the two already-attributed legacy service units and emits only counts for a fixed allowlist of exception class names, aggregate unknown-terminal-exception counts, traceback counts, and exception-chain markers.

It must not output journal lines, exception messages, filesystem paths, service users, ExecStart values, environment values, Nginx configuration, database rows, credentials, object-storage identifiers, or presigned URLs.

It must not start, stop, restart, reload, enable, disable, or otherwise mutate services; change Nginx; access or mutate application databases or S3; modify server repositories; or edit environment files.

A merge only creates the protected diagnostic run. The SSH inspection still requires the production Environment approval gate.