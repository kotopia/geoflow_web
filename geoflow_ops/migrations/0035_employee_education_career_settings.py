from django.db import migrations


SQL = r"""
ALTER TABLE hr.employee_career
    ADD COLUMN IF NOT EXISTS certificate_no text NULL;

INSERT INTO ops.settings_nodes
    (parent_id, code, name, node_type, field_ref, ord, locked)
SELECT root.id, seed.code, seed.name, 'category', seed.field_ref, seed.ord, true
  FROM ops.settings_nodes root
  CROSS JOIN (VALUES
      ('education_degree', '학력 학위', 'employee.education_degree', 60),
      ('education_status', '학력 상태', 'employee.education_status', 70)
  ) AS seed(code, name, field_ref, ord)
 WHERE root.system_key = 'domain.hr'
ON CONFLICT DO NOTHING;

INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, ord)
SELECT category.id, seed.code, seed.name, 'value', seed.ord
  FROM ops.settings_nodes category
  JOIN (VALUES
      ('employee.education_degree', '전문학사', '전문학사', 10),
      ('employee.education_degree', '학사', '학사', 20),
      ('employee.education_degree', '석사', '석사', 30),
      ('employee.education_degree', '박사', '박사', 40),
      ('employee.education_status', '졸업', '졸업', 10),
      ('employee.education_status', '수료', '수료', 20),
      ('employee.education_status', '재학', '재학', 30),
      ('employee.education_status', '휴학', '휴학', 40),
      ('employee.education_status', '퇴학', '퇴학', 50)
  ) AS seed(field_ref, code, name, ord)
    ON category.field_ref = seed.field_ref
ON CONFLICT DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0034_finance_account_card_trash")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
