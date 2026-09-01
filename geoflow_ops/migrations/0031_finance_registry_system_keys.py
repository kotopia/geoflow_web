from django.db import migrations


SQL = r"""
UPDATE ops.settings_nodes v
SET system_key = 'finance.value.' || c.code || '.' || v.code,
    locked = true,
    updated_at = now()
FROM ops.settings_nodes c
WHERE v.parent_id = c.id
  AND c.field_ref LIKE 'finance.%'
  AND COALESCE(v.system_key, '') = '';
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0030_finance_phase1")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
