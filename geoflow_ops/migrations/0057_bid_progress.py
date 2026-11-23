from django.db import migrations

SQL = """
ALTER TABLE bid.tenant_state ADD COLUMN registered_at timestamptz NULL;
ALTER TABLE bid.tenant_state ADD COLUMN submitted_at timestamptz NULL;
"""

class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0055_bid_tenant_state")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
