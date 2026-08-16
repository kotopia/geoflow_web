from django.db import migrations


FORWARD_SQL = r"""
ALTER TABLE prj.scope_item
    ADD COLUMN IF NOT EXISTS progress_qty numeric(18, 3) NULL;
ALTER TABLE prj.scope_item
    ADD COLUMN IF NOT EXISTS status varchar(20) NULL;
ALTER TABLE prj.scope_item
    ADD COLUMN IF NOT EXISTS completed_at date NULL;
ALTER TABLE prj.scope_item
    ADD COLUMN IF NOT EXISTS assignee_employee_id uuid NULL;
ALTER TABLE prj.scope_item
    ADD COLUMN IF NOT EXISTS variance_reason text NULL;

-- Existing rows never had a workflow state. Preserve their quantities and use the
-- least-assumptive state: rows with any historical completed quantity become
-- in-progress, all others become pending. Nothing is auto-declared complete.
UPDATE prj.scope_item
   SET status = CASE
       WHEN completed_qty IS NOT NULL AND completed_qty <> 0 THEN 'active'
       ELSE 'pending'
   END
 WHERE status IS NULL OR btrim(status) = '';

ALTER TABLE prj.scope_item
    ALTER COLUMN status SET DEFAULT 'pending';
ALTER TABLE prj.scope_item
    ALTER COLUMN status SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scope_item_project_status
    ON prj.scope_item (project_id, status);
CREATE INDEX IF NOT EXISTS idx_scope_item_assignee
    ON prj.scope_item (assignee_employee_id);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("webgisapp", "0019_phase4_event_workflow_foundation"),
    ]

    operations = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            # These columns become part of the live project history. Dropping them
            # would be destructive, so production rollback is intentionally noop.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
