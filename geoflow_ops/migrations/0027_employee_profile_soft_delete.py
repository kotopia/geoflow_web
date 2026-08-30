from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0026_contract_completion_event_backfill"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE IF EXISTS hr.employee_profile
                        ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
                        ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL,
                        ADD COLUMN IF NOT EXISTS deleted_by text NULL,
                        ADD COLUMN IF NOT EXISTS delete_reason text NULL,
                        ADD COLUMN IF NOT EXISTS restored_at timestamptz NULL,
                        ADD COLUMN IF NOT EXISTS restored_by text NULL;

                    CREATE INDEX IF NOT EXISTS idx_employee_profile_active_name
                        ON hr.employee_profile (name, email)
                        WHERE is_deleted = false;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="employeeprofile",
                    name="is_deleted",
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name="employeeprofile",
                    name="deleted_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="employeeprofile",
                    name="deleted_by",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="employeeprofile",
                    name="delete_reason",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="employeeprofile",
                    name="restored_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="employeeprofile",
                    name="restored_by",
                    field=models.TextField(blank=True, null=True),
                ),
            ],
        ),
    ]
