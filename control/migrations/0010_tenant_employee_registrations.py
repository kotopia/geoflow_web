from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("control", "0009_gis_reference_code_groups")]
    operations = [migrations.RunSQL(
        """
        CREATE TABLE tenant_employee_registrations (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            group_id uuid NOT NULL REFERENCES groups(id) ON DELETE RESTRICT,
            role_id uuid NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
            actor_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            employee_id uuid NULL,
            status text NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
            error_code text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX tenant_employee_registration_user_idx
            ON tenant_employee_registrations(user_id, created_at DESC);
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
