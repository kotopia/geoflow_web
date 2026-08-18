from django.db import migrations

# Owner-approved protected production retrigger; migration operations remain unchanged.

class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0023_phase4_configurable_workflow_foundation"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            CREATE TABLE IF NOT EXISTS ops.contract_document_access_requests (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                contract_id uuid NOT NULL,
                requester_employee_id uuid NOT NULL,
                reason text NULL,
                status varchar(20) NOT NULL DEFAULT 'pending',
                reviewed_by_employee_id uuid NULL,
                requested_at timestamptz NOT NULL DEFAULT now(),
                reviewed_at timestamptz NULL,
                CONSTRAINT contract_document_access_status_chk
                    CHECK (status IN ('pending','approved','rejected','revoked'))
            );

            CREATE INDEX IF NOT EXISTS ix_contract_document_access_contract_status
                ON ops.contract_document_access_requests(contract_id, status, requested_at);
            CREATE INDEX IF NOT EXISTS ix_contract_document_access_requester
                ON ops.contract_document_access_requests(requester_employee_id, requested_at DESC);

            -- Department is an HR master, not a duplicated settings string. Seed
            -- the three initial departments once for every company/org unit.
            INSERT INTO hr.departments (org_unit_id, name, active)
            SELECT org.id, seed.name, true
              FROM ops.my_org_units org
              CROSS JOIN (VALUES ('관리부'), ('GIS사업부'), ('지적사업부')) AS seed(name)
             WHERE NOT EXISTS (
                SELECT 1
                  FROM hr.departments d
                 WHERE d.org_unit_id = org.id
                   AND d.name = seed.name
             );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]