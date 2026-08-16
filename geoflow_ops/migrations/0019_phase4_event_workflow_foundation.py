from django.db import migrations, models


FORWARD_SQL = r"""
ALTER TABLE ops.process_events
    ADD COLUMN IF NOT EXISTS contract_id uuid NULL;
ALTER TABLE ops.process_events
    ADD COLUMN IF NOT EXISTS project_id uuid NULL;
ALTER TABLE ops.process_events
    ADD COLUMN IF NOT EXISTS owner_department_id uuid NULL;
ALTER TABLE ops.process_events
    ADD COLUMN IF NOT EXISTS assignee_employee_id uuid NULL;
ALTER TABLE ops.process_events
    ADD COLUMN IF NOT EXISTS payload jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_event_contract
    ON ops.process_events (contract_id);
CREATE INDEX IF NOT EXISTS idx_event_project
    ON ops.process_events (project_id);
CREATE INDEX IF NOT EXISTS idx_event_owner_dept
    ON ops.process_events (owner_department_id);
CREATE INDEX IF NOT EXISTS idx_event_assignee
    ON ops.process_events (assignee_employee_id);

-- Preserve every event row while adding the contract/project business lineage.
UPDATE ops.process_events
   SET contract_id = scope_id
 WHERE scope_type = 'contract'
   AND contract_id IS NULL;

UPDATE ops.process_events
   SET project_id = scope_id
 WHERE scope_type = 'project'
   AND project_id IS NULL;

UPDATE ops.process_events AS e
   SET contract_id = p.contract_id
  FROM prj.projects AS p
 WHERE e.project_id = p.id
   AND e.contract_id IS NULL
   AND p.contract_id IS NOT NULL;

-- Normalize only values that were emitted by the legacy GeoFlow event UI.
-- Unknown/custom historical values are intentionally left untouched.
UPDATE ops.process_events SET stage = 'pre_contract'
 WHERE event_type = 'estimate';
UPDATE ops.process_events SET stage = 'contract'
 WHERE event_type IN ('contract_doc', 'suspend');
UPDATE ops.process_events SET stage = 'kickoff'
 WHERE event_type = 'kickoff';
UPDATE ops.process_events SET stage = 'execution'
 WHERE event_type = 'progress_report';
UPDATE ops.process_events SET stage = 'inspection'
 WHERE event_type = 'inspection';
UPDATE ops.process_events SET stage = 'closeout'
 WHERE event_type = 'completion_doc';
UPDATE ops.process_events SET stage = 'billing'
 WHERE event_type IN ('advance_payment', 'invoice', 'payment');

UPDATE ops.process_events SET stage = 'execution'
 WHERE stage = 'project';
UPDATE ops.process_events SET stage = 'billing'
 WHERE stage = 'blilling';
"""


class Migration(migrations.Migration):
    dependencies = [
        ("webgisapp", "0018_processevent_processeventattachment"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=FORWARD_SQL,
                    # Reversing semantic normalization would be lossy because new
                    # events may legitimately use the canonical values. Leaving
                    # the additive columns in place is safer than destructive
                    # rollback; state still reverses normally.
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="processevent",
                    name="contract_id",
                    field=models.UUIDField(blank=True, db_column="contract_id", null=True),
                ),
                migrations.AddField(
                    model_name="processevent",
                    name="project_id",
                    field=models.UUIDField(blank=True, db_column="project_id", null=True),
                ),
                migrations.AddField(
                    model_name="processevent",
                    name="owner_department_id",
                    field=models.UUIDField(blank=True, db_column="owner_department_id", null=True),
                ),
                migrations.AddField(
                    model_name="processevent",
                    name="assignee_employee_id",
                    field=models.UUIDField(blank=True, db_column="assignee_employee_id", null=True),
                ),
                migrations.AddField(
                    model_name="processevent",
                    name="payload",
                    field=models.JSONField(blank=True, db_column="payload", default=dict),
                ),
                migrations.AlterField(
                    model_name="processevent",
                    name="status",
                    field=models.CharField(
                        choices=[
                            ("draft", "작성중"),
                            ("open", "진행중"),
                            ("done", "완료"),
                            ("void", "취소"),
                        ],
                        db_column="status",
                        default="draft",
                        max_length=20,
                    ),
                ),
                migrations.AddIndex(
                    model_name="processevent",
                    index=models.Index(fields=["contract_id"], name="idx_event_contract"),
                ),
                migrations.AddIndex(
                    model_name="processevent",
                    index=models.Index(fields=["project_id"], name="idx_event_project"),
                ),
                migrations.AddIndex(
                    model_name="processevent",
                    index=models.Index(fields=["owner_department_id"], name="idx_event_owner_dept"),
                ),
                migrations.AddIndex(
                    model_name="processevent",
                    index=models.Index(fields=["assignee_employee_id"], name="idx_event_assignee"),
                ),
            ],
        ),
    ]
