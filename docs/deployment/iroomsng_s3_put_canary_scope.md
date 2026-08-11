# iroomsng S3 zero-byte put canary scope

Purpose: determine whether the legacy iroomsng AWS principal can perform a plain authenticated `s3:PutObject` after read-only diagnostics confirmed valid credentials and readable bucket access but IAM policy introspection was denied.

Mutation boundary:
- one zero-byte object only;
- key is generated under the fixed `__iroomsng_diagnostic__/zero-byte-put-canary-` prefix;
- no ACL header;
- no KMS or explicit server-side encryption header;
- no overwrite of known application objects;
- immediate `DeleteObject` cleanup only if the put succeeds;
- report a bounded cleanup-required flag if deletion fails.

Safety boundary:
- protected `production` Environment approval;
- exact triggering release SHA;
- no service restart, start, stop, enable, disable, or reload;
- no Nginx changes;
- no database access or migration;
- no repository mutation on the server;
- no AWS credential, bucket name, object key, ARN, account ID, policy document, or raw exception output.

Interpretation:
- `AccessDenied` on the plain zero-byte put strongly points to identity/bucket authorization rather than application payload handling, ACL, or KMS request headers.
- a successful put followed by successful cleanup shows the principal has basic `PutObject` capability, shifting investigation to request shape used by the web/QGIS clients.
