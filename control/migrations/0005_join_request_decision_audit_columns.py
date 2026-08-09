from django.db import migrations


ADD_JOIN_REQUEST_DECISION_AUDIT_COLUMNS_SQL = """
ALTER TABLE join_requests
    ADD COLUMN IF NOT EXISTS decided_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS decided_by uuid NULL;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("control", "0004_signup_verification_delivery_outbox"),
    ]

    operations = [
        # join_requests is a pre-existing unmanaged central table.  Keep this
        # migration idempotent so both modern and legacy central schemas can
        # converge without recreating or rewriting existing request rows.
        migrations.RunSQL(
            sql=ADD_JOIN_REQUEST_DECISION_AUDIT_COLUMNS_SQL,
            # Do not drop audit columns on rollback: they can contain reviewer
            # attribution written after this migration is applied.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
