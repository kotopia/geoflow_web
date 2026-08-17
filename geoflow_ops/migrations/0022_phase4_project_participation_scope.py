from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0021_phase4_employee_settings_foundation"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            CREATE SCHEMA IF NOT EXISTS prj;

            CREATE TABLE IF NOT EXISTS prj.project_members (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id uuid NOT NULL,
                employee_id uuid NULL,
                member_role varchar(32) NOT NULL DEFAULT 'worker',
                membership_status varchar(20) NOT NULL DEFAULT 'active',
                invite_email text NULL,
                invite_name text NULL,
                is_external boolean NOT NULL DEFAULT false,
                note text NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT project_members_role_ck CHECK (
                    member_role IN ('project_manager', 'project_leader', 'worker', 'viewer')
                ),
                CONSTRAINT project_members_status_ck CHECK (
                    membership_status IN ('invited', 'active', 'revoked')
                ),
                CONSTRAINT project_members_identity_ck CHECK (
                    employee_id IS NOT NULL OR NULLIF(BTRIM(invite_email), '') IS NOT NULL
                )
            );

            CREATE INDEX IF NOT EXISTS idx_project_members_project_active
                ON prj.project_members (project_id, membership_status, member_role);
            CREATE INDEX IF NOT EXISTS idx_project_members_employee_active
                ON prj.project_members (employee_id, membership_status, project_id)
                WHERE employee_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_project_members_invite_email
                ON prj.project_members (lower(invite_email), membership_status, project_id)
                WHERE invite_email IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS ux_project_members_project_employee
                ON prj.project_members (project_id, employee_id)
                WHERE employee_id IS NOT NULL AND membership_status <> 'revoked';
            CREATE UNIQUE INDEX IF NOT EXISTS ux_project_members_project_invite_email
                ON prj.project_members (project_id, lower(invite_email))
                WHERE invite_email IS NOT NULL AND membership_status <> 'revoked';

            COMMENT ON TABLE prj.project_members IS
                'Tenant-local project participation boundary used by Project/WebGIS authorization.';
            COMMENT ON COLUMN prj.project_members.member_role IS
                'Project-local responsibility: project_manager, project_leader, worker, viewer.';
            COMMENT ON COLUMN prj.project_members.invite_email IS
                'Reserved for external project invitation/linking. Invited rows do not grant access until activated.';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
