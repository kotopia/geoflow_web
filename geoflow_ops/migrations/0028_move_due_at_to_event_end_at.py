from django.db import migrations


FORWARD_SQL = r"""
UPDATE ops.process_events
   SET payload = jsonb_set(
       COALESCE(payload, '{}'::jsonb),
       '{display}',
       COALESCE(payload->'display', '{}'::jsonb)
         || jsonb_build_object('end_at', to_char(due_at, 'YYYY-MM-DD')),
       true
   )
 WHERE due_at IS NOT NULL
   AND COALESCE(payload->'display'->>'end_at', '') = '';

-- 완료예정일은 더 이상 업무 데이터로 사용하지 않는다. 이관 후 값은 비운다.
UPDATE ops.process_events
   SET due_at = NULL
 WHERE due_at IS NOT NULL;
"""

REVERSE_SQL = r"""
UPDATE ops.process_events
   SET due_at = NULLIF(payload->'display'->>'end_at', '')::date
 WHERE due_at IS NULL
   AND COALESCE(payload->'display'->>'end_at', '') <> '';
"""


class Migration(migrations.Migration):
    dependencies = [
        ("geoflow_ops", "0027_employee_profile_soft_delete"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
