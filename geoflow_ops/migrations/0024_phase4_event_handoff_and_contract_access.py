from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0023_phase4_configurable_workflow_foundation"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            -- Department master remains hr.departments, the same table used by
            -- employee profiles and event assignment. Seed the three agreed
            -- departments for every tenant org unit without replacing custom data.
            DO $$
            BEGIN
                IF to_regclass('hr.departments') IS NOT NULL
                   AND to_regclass('ops.my_org_units') IS NOT NULL THEN
                    INSERT INTO hr.departments (org_unit_id, name, active)
                    SELECT ou.id, seed.name, true
                      FROM ops.my_org_units ou
                      CROSS JOIN (VALUES
                          ('관리부'),
                          ('GIS사업부'),
                          ('지적사업부')
                      ) AS seed(name)
                     WHERE NOT EXISTS (
                         SELECT 1
                           FROM hr.departments d
                          WHERE d.org_unit_id=ou.id
                            AND btrim(d.name)=seed.name
                     );
                END IF;
            END $$;

            CREATE TABLE IF NOT EXISTS ops.contract_document_access_requests (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                contract_id uuid NOT NULL,
                project_id uuid NOT NULL,
                requester_employee_id uuid NOT NULL,
                reason text NULL,
                status varchar(20) NOT NULL DEFAULT 'pending',
                requested_at timestamptz NOT NULL DEFAULT now(),
                decided_at timestamptz NULL,
                decided_by text NULL,
                expires_at timestamptz NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT chk_contract_doc_access_status
                    CHECK (status IN ('pending','approved','rejected','revoked'))
            );

            CREATE INDEX IF NOT EXISTS idx_contract_doc_access_contract
                ON ops.contract_document_access_requests (contract_id, status);
            CREATE INDEX IF NOT EXISTS idx_contract_doc_access_requester
                ON ops.contract_document_access_requests (requester_employee_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_doc_access_pending
                ON ops.contract_document_access_requests
                    (contract_id, project_id, requester_employee_id)
                WHERE status='pending';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
