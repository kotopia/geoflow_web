from django.db import migrations

SQL = """
CREATE TABLE IF NOT EXISTS bid.company_search_profiles (
    company_id uuid PRIMARY KEY REFERENCES ops.my_org_units(id) ON DELETE RESTRICT,
    settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class Migration(migrations.Migration):
    dependencies = [('webgisapp', '0038_bid_central_preferences')]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
