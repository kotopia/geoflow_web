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

            -- Common defaults. They are never deleted automatically; tenants can
            -- switch unused items off from My Company Info.
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
                ('representative', '대표', 5, true, true),
                ('ceo', '대표이사', 10, true, true),
                ('headquarters_head', '본부장', 20, true, true),
                ('division_head', '부문장', 30, true, true),
                ('office_head', '실장', 40, true, true),
                ('team_lead', '팀장', 50, true, true),
                ('part_lead', '파트장', 60, true, true),
                ('team_member', '팀원', 70, true, true)
            ON CONFLICT DO NOTHING;

            -- Preserve tenant customizations that previously lived in the generic
            -- settings tree.  These rows become HR masters; the old tree rows are
            -- retained as history/compatibility data but are no longer the source
            -- for employee grade/title selection.
            INSERT INTO hr.job_grades (code, name, ord, active, system_default)
            SELECT 'settings-' || md5(child.id::text),
                   child.name,
                   child.ord,
                   child.active,
                   false
              FROM ops.settings_nodes category
              JOIN ops.settings_nodes child ON child.parent_id = category.id
             WHERE category.system_key = 'hr.position_grade'
               AND btrim(COALESCE(child.name, '')) <> ''
            ON CONFLICT DO NOTHING;

            INSERT INTO hr.job_positions (code, name, ord, active, system_default)
            SELECT 'settings-' || md5(child.id::text),
                   child.name,
                   child.ord,
                   child.active,
                   false
              FROM ops.settings_nodes category
              JOIN ops.settings_nodes child ON child.parent_id = category.id
             WHERE category.system_key = 'hr.position_title'
               AND btrim(COALESCE(child.name, '')) <> ''
            ON CONFLICT DO NOTHING;

            -- Any value already stored on an employee must stay selectable after
            -- cutover even if it was once a free-text/custom value.  No employee
            -- row is rewritten; only missing master rows are added.
            INSERT INTO hr.job_grades (code, name, ord, active, system_default)
            SELECT 'employee-' || md5(lower(src.name)),
                   src.name,
                   5000 + row_number() OVER (ORDER BY lower(src.name)),
                   true,
                   false
              FROM (
                  SELECT DISTINCT btrim(position_grade) AS name
                    FROM hr.employee_profile
                   WHERE btrim(COALESCE(position_grade, '')) <> ''
              ) src
            ON CONFLICT DO NOTHING;

            INSERT INTO hr.job_positions (code, name, ord, active, system_default)
            SELECT 'employee-' || md5(lower(src.name)),
                   src.name,
                   5000 + row_number() OVER (ORDER BY lower(src.name)),
                   true,
                   false
              FROM (
                  SELECT DISTINCT btrim(title) AS name
                    FROM hr.employee_profile
                   WHERE btrim(COALESCE(title, '')) <> ''
              ) src
            ON CONFLICT DO NOTHING;

            UPDATE hr.job_grades master
               SET active = true, updated_at = now()
             WHERE active = false
               AND EXISTS (
                   SELECT 1
                     FROM hr.employee_profile employee
                    WHERE lower(btrim(employee.position_grade)) = lower(master.name)
               );

            UPDATE hr.job_positions master
               SET active = true, updated_at = now()
             WHERE active = false
               AND EXISTS (
                   SELECT 1
                     FROM hr.employee_profile employee
                    WHERE lower(btrim(employee.title)) = lower(master.name)
               );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
