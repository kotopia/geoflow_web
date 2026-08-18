from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0024_phase4_workflow_handoff_and_contract_access"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            CREATE TABLE IF NOT EXISTS hr.job_grades (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                code text NOT NULL,
                name text NOT NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                system_default boolean NOT NULL DEFAULT false,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_job_grades_code
                ON hr.job_grades (lower(code));
            CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_job_grades_name
                ON hr.job_grades (lower(name));
            CREATE INDEX IF NOT EXISTS ix_hr_job_grades_active_ord
                ON hr.job_grades (active, ord, name);

            CREATE TABLE IF NOT EXISTS hr.job_positions (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                code text NOT NULL,
                name text NOT NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                system_default boolean NOT NULL DEFAULT false,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_job_positions_code
                ON hr.job_positions (lower(code));
            CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_job_positions_name
                ON hr.job_positions (lower(name));
            CREATE INDEX IF NOT EXISTS ix_hr_job_positions_active_ord
                ON hr.job_positions (active, ord, name);

            INSERT INTO hr.job_grades (code, name, ord, active, system_default)
            VALUES
                ('executive', '임원', 10, true, true),
                ('general_manager', '부장', 20, true, true),
                ('deputy_general_manager', '차장', 30, true, true),
                ('manager', '과장', 40, true, true),
                ('assistant_manager', '대리', 50, true, true),
                ('senior_staff', '주임', 60, true, true),
                ('staff', '사원', 70, true, true),
                ('intern', '인턴', 80, true, true)
            ON CONFLICT DO NOTHING;

            INSERT INTO hr.job_positions (code, name, ord, active, system_default)
            VALUES
                ('ceo', '대표이사', 10, true, true),
                ('headquarters_head', '본부장', 20, true, true),
                ('division_head', '부문장', 30, true, true),
                ('office_head', '실장', 40, true, true),
                ('team_lead', '팀장', 50, true, true),
                ('part_lead', '파트장', 60, true, true),
                ('team_member', '팀원', 70, true, true)
            ON CONFLICT DO NOTHING;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
