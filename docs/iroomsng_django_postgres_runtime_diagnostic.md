# iroomsng Django/PostgreSQL runtime diagnostic

This repository-only diagnostic is read-only and production-gated.

It exists to determine whether the legacy iroomsng Gunicorn worker failure is the Django database-version compatibility check introduced by the currently deployed Python runtime.

It emits only bounded compatibility signals:
- whether the journal contains the Django `PostgreSQL 14 or later is required` fingerprint;
- the PostgreSQL major version contained in that already-recorded exception, when available;
- whether the traceback includes Django's database-version compatibility check;
- the Django version imported by the interpreter referenced by the service executable, when safely derivable;
- whether that executable path has an explicit virtual-environment marker.

It does not print journal lines, exception messages, service paths, executable paths, database endpoints, database credentials, environment values, or application records. It performs no database query and no service, Nginx, S3, repository, or runtime mutation.
