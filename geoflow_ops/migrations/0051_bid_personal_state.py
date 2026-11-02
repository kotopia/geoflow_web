from django.db import migrations

SQL = """
CREATE TABLE IF NOT EXISTS bid.personal_state (
    user_id uuid NOT NULL,
    origin varchar(16) NOT NULL CHECK (origin IN ('central','legacy')),
    notice_id uuid NOT NULL,
    saved boolean NOT NULL DEFAULT false,
    hidden boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, origin, notice_id)
);
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0036_bid_interest_foundation")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
