from django.db import migrations


BACKFILL_SQL = r"""
-- Only the erasure service's synthetic identity plus its disabled identity
-- state qualifies. Pending/inactive real accounts must remain visible.
UPDATE users SET deleted_at=COALESCE(updated_at, now())
 WHERE deleted_at IS NULL
   AND email ~ '^erased-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}@example[.]invalid$'
   AND is_active=FALSE AND email_verified=FALSE AND is_staff=FALSE
   AND name_display IS NULL AND password_hash LIKE '!%'
   AND NOT EXISTS (SELECT 1 FROM user_group_map m WHERE m.user_id=users.id);
"""

CREATE_SETTINGS_SQL = """
CREATE TABLE group_service_menu_settings (
    group_id uuid PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
    bids boolean NOT NULL DEFAULT TRUE,
    gis boolean NOT NULL DEFAULT TRUE,
    finance boolean NOT NULL DEFAULT TRUE,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class Migration(migrations.Migration):
    dependencies = [("control", "0006_account_password_reset_schema")]
    # Preserve audit markers and preferences on code rollback. This migration
    # is intentionally irreversible; no audit-data-destructive reverse DDL.
    operations = [
        migrations.RunSQL("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at timestamptz NULL"),
        migrations.RunSQL(BACKFILL_SQL),
        migrations.RunSQL(CREATE_SETTINGS_SQL),
    ]
