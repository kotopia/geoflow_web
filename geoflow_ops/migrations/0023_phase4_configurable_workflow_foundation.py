from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("webgisapp", "0022_phase4_project_participation_scope"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            -- Canonicalize only reviewed contract-status aliases. Unknown/custom
            -- historical values are intentionally left untouched.
            DO $$
            BEGIN
                IF to_regclass('ctr.contracts') IS NOT NULL THEN
                    UPDATE ctr.contracts
                       SET status = CASE lower(btrim(status))
                           WHEN 'completed' THEN 'complete'
                           WHEN '완료' THEN 'complete'
                           WHEN 'paused' THEN 'pause'
                           WHEN '중지' THEN 'pause'
                           WHEN 'canceled' THEN 'cancel'
                           WHEN 'cancelled' THEN 'cancel'
                           WHEN '취소' THEN 'cancel'
                           WHEN '진행' THEN 'active'
                           WHEN '진행중' THEN 'active'
                           WHEN '계약전' THEN 'planned'
                           ELSE status
                       END,
                           updated_at = now()
                     WHERE lower(btrim(status)) IN (
                         'completed', '완료', 'paused', '중지', 'canceled', 'cancelled',
                         '취소', '진행', '진행중', '계약전'
                     );
                END IF;
            END $$;

            -- Contract settings categories.
            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT root.id, seed.code, seed.name, 'category', seed.system_key, seed.ord, true
              FROM ops.settings_nodes root
              CROSS JOIN (VALUES
                  ('status', '계약 상태', 'contract.status', 10),
                  ('kind', '계약 형태', 'contract.kind', 20)
              ) AS seed(code, name, system_key, ord)
             WHERE root.system_key = 'domain.contract'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, value, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('planned', '계약전', 'contract.status.planned', 10),
                  ('active', '진행', 'contract.status.active', 20),
                  ('pause', '중지', 'contract.status.pause', 30),
                  ('complete', '완료', 'contract.status.complete', 40),
                  ('cancel', '취소', 'contract.status.cancel', 50)
              ) AS seed(code, name, system_key, ord)
             WHERE category.system_key = 'contract.status'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, value, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('총액', '총액계약', 'contract.kind.total', 10),
                  ('공동', '공동계약', 'contract.kind.joint', 20),
                  ('장기계속', '장기계속계약', 'contract.kind.long_term', 30),
                  ('단가', '단가계약', 'contract.kind.unit', 40),
                  ('하도급', '하도급계약', 'contract.kind.subcontract', 50)
              ) AS seed(code, name, system_key, ord)
             WHERE category.system_key = 'contract.kind'
            ON CONFLICT DO NOTHING;

            -- Event settings roots.
            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT root.id, seed.code, seed.name, 'category', seed.system_key, seed.ord, true
              FROM ops.settings_nodes root
              CROSS JOIN (VALUES
                  ('stage', '업무 단계', 'event.stage', 10),
                  ('type', '업무 유형', 'event.type', 20),
                  ('status', '진행 상태', 'event.status', 30)
              ) AS seed(code, name, system_key, ord)
             WHERE root.system_key = 'domain.event'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, value, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('pre_contract', '계약전', 'event.stage.pre_contract', 10),
                  ('contract', '계약', 'event.stage.contract', 20),
                  ('kickoff', '착수', 'event.stage.kickoff', 30),
                  ('execution', '수행', 'event.stage.execution', 40),
                  ('inspection', '검사', 'event.stage.inspection', 50),
                  ('closeout', '준공', 'event.stage.closeout', 60),
                  ('billing', '청구/정산', 'event.stage.billing', 70)
              ) AS seed(code, name, system_key, ord)
             WHERE category.system_key = 'event.stage'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, value, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('draft', '작성중', 'event.status.draft', 10),
                  ('open', '진행중', 'event.status.open', 20),
                  ('done', '완료', 'event.status.done', 30),
                  ('void', '취소', 'event.status.void', 40)
              ) AS seed(code, name, system_key, ord)
             WHERE category.system_key = 'event.status'
            ON CONFLICT DO NOTHING;

            -- Event-type categories are stage-scoped so a type can only be chosen
            -- under the stage where it is valid.
            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'category', seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('pre_contract', '계약전', 'event.type.pre_contract', 10),
                  ('contract', '계약', 'event.type.contract', 20),
                  ('kickoff', '착수', 'event.type.kickoff', 30),
                  ('execution', '수행', 'event.type.execution', 40),
                  ('inspection', '검사', 'event.type.inspection', 50),
                  ('closeout', '준공', 'event.type.closeout', 60),
                  ('billing', '청구/정산', 'event.type.billing', 70)
              ) AS seed(code, name, system_key, ord)
             WHERE category.system_key = 'event.type'
            ON CONFLICT DO NOTHING;

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, value, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'value', seed.code, seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              JOIN (VALUES
                  ('event.type.pre_contract', 'estimate', '견적제출', 'event.type.pre_contract.estimate', 10),
                  ('event.type.pre_contract', 'etc', '기타', 'event.type.pre_contract.etc', 900),

                  ('event.type.contract', 'contract_doc', '계약체결', 'event.type.contract.contract_doc', 10),
                  ('event.type.contract', 'contract_change', '계약변경', 'event.type.contract.contract_change', 20),
                  ('event.type.contract', 'period_extension', '기간연장', 'event.type.contract.period_extension', 30),
                  ('event.type.contract', 'suspend', '중지', 'event.type.contract.suspend', 40),
                  ('event.type.contract', 'resume', '재개', 'event.type.contract.resume', 50),
                  ('event.type.contract', 'contract_cancel', '계약취소', 'event.type.contract.contract_cancel', 60),
                  ('event.type.contract', 'etc', '기타', 'event.type.contract.etc', 900),

                  ('event.type.kickoff', 'kickoff', '착수', 'event.type.kickoff.kickoff', 10),
                  ('event.type.kickoff', 'kickoff_doc', '착수계', 'event.type.kickoff.kickoff_doc', 20),
                  ('event.type.kickoff', 'etc', '기타', 'event.type.kickoff.etc', 900),

                  ('event.type.execution', 'progress_report', '공정보고', 'event.type.execution.progress_report', 10),
                  ('event.type.execution', 'etc', '기타', 'event.type.execution.etc', 900),

                  ('event.type.inspection', 'inspection_request', '검사요청', 'event.type.inspection.inspection_request', 10),
                  ('event.type.inspection', 'inspection', '검사완료', 'event.type.inspection.inspection', 20),
                  ('event.type.inspection', 'correction_request', '보완요청', 'event.type.inspection.correction_request', 30),
                  ('event.type.inspection', 'reinspection', '재검사', 'event.type.inspection.reinspection', 40),
                  ('event.type.inspection', 'etc', '기타', 'event.type.inspection.etc', 900),

                  ('event.type.closeout', 'completion_doc', '준공계', 'event.type.closeout.completion_doc', 10),
                  ('event.type.closeout', 'delivery', '납품완료', 'event.type.closeout.delivery', 20),
                  ('event.type.closeout', 'etc', '기타', 'event.type.closeout.etc', 900),

                  ('event.type.billing', 'advance_payment', '선금', 'event.type.billing.advance_payment', 10),
                  ('event.type.billing', 'progress_invoice', '기성청구', 'event.type.billing.progress_invoice', 20),
                  ('event.type.billing', 'invoice', '청구', 'event.type.billing.invoice', 30),
                  ('event.type.billing', 'tax_invoice', '세금계산서', 'event.type.billing.tax_invoice', 40),
                  ('event.type.billing', 'payment', '입금/지급완료', 'event.type.billing.payment', 50),
                  ('event.type.billing', 'etc', '기타', 'event.type.billing.etc', 900)
              ) AS seed(parent_key, code, name, system_key, ord)
                ON category.system_key = seed.parent_key
            ON CONFLICT DO NOTHING;

            -- External/temporary workers are tenant personnel, not ad-hoc project
            -- email identities. Add day-worker as a standard employment type.
            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, value, ord)
            SELECT category.id, '일용직', '일용직', 'value', '일용직', 25
              FROM ops.settings_nodes category
             WHERE category.system_key = 'hr.employment_type'
            ON CONFLICT DO NOTHING;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
