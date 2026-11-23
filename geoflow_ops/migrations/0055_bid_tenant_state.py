from django.db import migrations

SQL = """
CREATE TABLE bid.tenant_state (
    origin varchar(16) NOT NULL CHECK (origin IN ('central','legacy')),
    notice_id uuid NOT NULL,
    saved boolean NOT NULL DEFAULT false,
    hidden boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (origin, notice_id)
);
INSERT INTO bid.tenant_state(origin,notice_id,saved,hidden,updated_at)
SELECT origin,notice_id,bool_or(saved),bool_and(hidden),max(updated_at)
FROM bid.personal_state GROUP BY origin,notice_id;
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0051_bid_personal_state")]
    # Preserve the pre-transition snapshot for an explicitly planned rollback.
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
