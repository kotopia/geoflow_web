from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("control", "0007_admin_visibility")]
    # Central, personal preferences only. Preserve saved work on code rollback.
    operations = [migrations.RunSQL('''
        CREATE TABLE saved_filters (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            group_id uuid NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            module varchar(40) NOT NULL,
            name varchar(100) NOT NULL,
            filter_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(user_id, group_id, module, name)
        );
    ''')]
