from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0020_phase4_project_task_execution"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            CREATE SCHEMA IF NOT EXISTS ops;
            CREATE SCHEMA IF NOT EXISTS hr;

            CREATE TABLE IF NOT EXISTS ops.settings_nodes (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                parent_id uuid NULL REFERENCES ops.settings_nodes(id) ON DELETE RESTRICT,
                code varchar(100) NOT NULL,
                name varchar(200) NOT NULL,
                node_type varchar(20) NOT NULL DEFAULT 'value',
                value text NULL,
                description text NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                system_key varchar(200) NULL,
                locked boolean NOT NULL DEFAULT false,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT settings_nodes_type_ck CHECK (node_type IN ('group', 'category', 'value'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_settings_nodes_system_key
                ON ops.settings_nodes (system_key) WHERE system_key IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS ux_settings_nodes_parent_code
                ON ops.settings_nodes ((COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)), lower(code));
            CREATE INDEX IF NOT EXISTS idx_settings_nodes_parent_ord
                ON ops.settings_nodes (parent_id, active, ord, name);

            CREATE TABLE IF NOT EXISTS hr.employee_education (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                employee_id uuid NOT NULL,
                school_name text NOT NULL,
                school_type text NULL,
                degree text NULL,
                major text NULL,
                admission_date date NULL,
                graduation_date date NULL,
                education_status text NULL,
                note text NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_employee_education_employee
                ON hr.employee_education (employee_id, active, ord, admission_date);

            CREATE TABLE IF NOT EXISTS hr.employee_qualification (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                employee_id uuid NOT NULL,
                qualification_name text NOT NULL,
                issuer text NULL,
                license_no text NULL,
                acquired_date date NULL,
                expiry_date date NULL,
                note text NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_employee_qualification_employee
                ON hr.employee_qualification (employee_id, active, ord, acquired_date);

            CREATE TABLE IF NOT EXISTS hr.employee_technical_grade (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                employee_id uuid NOT NULL,
                field_name text NULL,
                grade_code text NOT NULL,
                recognized_date date NULL,
                issuer text NULL,
                note text NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_employee_technical_grade_employee
                ON hr.employee_technical_grade (employee_id, active, ord, recognized_date);

            CREATE TABLE IF NOT EXISTS hr.employee_career (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                employee_id uuid NOT NULL,
                company_name text NOT NULL,
                department text NULL,
                position_title text NULL,
                started_on date NULL,
                ended_on date NULL,
                duties text NULL,
                note text NULL,
                ord integer NOT NULL DEFAULT 0,
                active boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_employee_career_employee
                ON hr.employee_career (employee_id, active, ord, started_on);

            -- Platform-wide settings roots. These are intentionally generic so
            -- later Contract / Project / Event / GIS settings can use the same tree.
            INSERT INTO ops.settings_nodes (code, name, node_type, system_key, ord, locked)
            VALUES
                ('hr', '인사', 'group', 'domain.hr', 10, true),
                ('contract', '계약', 'group', 'domain.contract', 20, true),
                ('project', '프로젝트', 'group', 'domain.project', 30, true),
                ('event', '업무 이벤트', 'group', 'domain.event', 40, true),
                ('gis', 'GIS', 'group', 'domain.gis', 50, true)
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT root.id, seed.code, seed.name, 'category', seed.system_key, seed.ord, true
              FROM ops.settings_nodes root
              CROSS JOIN (VALUES
                  ('position_grade', '직급', 'hr.position_grade', 10),
                  ('position_title', '직위/직책', 'hr.position_title', 20),
                  ('employment_type', '고용형태', 'hr.employment_type', 30),
                  ('employment_status', '재직상태', 'hr.status', 40),
                  ('technical_grade', '기술등급', 'hr.technical_grade', 50)
              ) AS seed(code, name, system_key, ord)
             WHERE root.system_key = 'domain.hr'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, value, ord)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.ord
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('임원', '임원', 10), ('부장', '부장', 20), ('차장', '차장', 30),
                  ('과장', '과장', 40), ('대리', '대리', 50), ('주임', '주임', 60),
                  ('사원', '사원', 70), ('인턴', '인턴', 80)
              ) AS seed(code, name, ord)
             WHERE category.system_key = 'hr.position_grade'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, value, ord)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.ord
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('대표', '대표', 10), ('본부장', '본부장', 20),
                  ('팀장', '팀장', 30), ('팀원', '팀원', 40)
              ) AS seed(code, name, ord)
             WHERE category.system_key = 'hr.position_title'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, value, ord)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.ord
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('정규직', '정규직', 10), ('계약직', '계약직', 20), ('파견', '파견', 30),
                  ('용역', '용역', 40), ('프리랜서', '프리랜서', 50), ('인턴', '인턴', 60)
              ) AS seed(code, name, ord)
             WHERE category.system_key = 'hr.employment_type'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, value, ord)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.ord
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('재직', '재직', 10), ('휴직', '휴직', 20), ('퇴사', '퇴사', 30)
              ) AS seed(code, name, ord)
             WHERE category.system_key = 'hr.status'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, value, ord)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.ord
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('초급', '초급', 10), ('중급', '중급', 20),
                  ('고급', '고급', 30), ('특급', '특급', 40)
              ) AS seed(code, name, ord)
             WHERE category.system_key = 'hr.technical_grade'
            ON CONFLICT DO NOTHING;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
