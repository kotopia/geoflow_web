from django.db import migrations

SQL = """
CREATE TABLE IF NOT EXISTS bid.central_preferences (
    id smallint PRIMARY KEY CHECK (id=1),
    rule_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(rule_ids)='array'),
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0037_central_bid_reviews")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
