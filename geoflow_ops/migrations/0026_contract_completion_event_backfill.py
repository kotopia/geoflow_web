from django.db import migrations


FORWARD_SQL = r"""
-- Convert the only legacy Contract.status value that carries terminal business
-- meaning into the new event-driven lifecycle. This is intentionally one-way:
-- after conversion, completion is represented by ops.process_events only.
--
-- `occurred_at` uses the contract end_date when available because the old status
-- did not preserve an explicit completion date. The payload records that this
-- date was inferred so it is never mistaken for an observed historical fact.
INSERT INTO ops.process_events (
    id,
    scope_type,
    scope_id,
    contract_id,
    project_id,
    owner_department_id,
    assignee_employee_id,
    stage,
    event_type,
    title,
    memo,
    status,
    occurred_at,
    due_at,
    created_by,
    payload,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    'contract',
    c.id,
    c.id,
    NULL,
    NULL,
    NULL,
    'closeout',
    'closeout_complete',
    '준공 완료',
    '기존 계약 완료 상태를 이벤트 기반 업무 프로세스로 전환했습니다.',
    'done',
    c.end_date,
    NULL,
    'system:migration:0026',
    jsonb_build_object(
        'source', 'legacy_contract_status_migration',
        'legacy_status', c.status,
        'occurred_at_source', CASE
            WHEN c.end_date IS NOT NULL THEN 'contract.end_date'
            ELSE 'unknown'
        END,
        'occurred_at_inferred', c.end_date IS NOT NULL
    ),
    now(),
    now()
FROM ctr.contracts AS c
WHERE lower(btrim(COALESCE(c.status, ''))) IN ('complete', 'completed', '완료')
  AND NOT EXISTS (
      SELECT 1
        FROM ops.process_events AS e
       WHERE e.contract_id = c.id
         AND e.event_type = 'closeout_complete'
         AND COALESCE(e.status, '') <> 'void'
  );

-- Once a non-void completion event exists, remove the migrated legacy completion
-- token. Other legacy statuses are deliberately untouched because their meaning
-- cannot be reconstructed safely without an observed event date/type.
UPDATE ctr.contracts AS c
   SET status = NULL,
       updated_at = now()
 WHERE lower(btrim(COALESCE(c.status, ''))) IN ('complete', 'completed', '완료')
   AND EXISTS (
       SELECT 1
         FROM ops.process_events AS e
        WHERE e.contract_id = c.id
          AND e.event_type = 'closeout_complete'
          AND COALESCE(e.status, '') <> 'void'
   );
"""


class Migration(migrations.Migration):
    dependencies = [
        ("webgisapp", "0025_myinfo_hr_masters"),
    ]

    operations = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            # Recreating legacy status values on reverse would make the event
            # ledger and Contract.status disagree. Keep the canonical event data.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
