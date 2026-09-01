from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0028_move_due_at_to_event_end_at")]

    operations = [
        migrations.RunSQL(
            sql=r"""
            ALTER TABLE ops.settings_nodes ADD COLUMN IF NOT EXISTS field_ref varchar(200) NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS ux_settings_nodes_field_ref
                ON ops.settings_nodes (field_ref) WHERE field_ref IS NOT NULL;

            -- The product is still in its initial data-entry phase. Replace the
            -- conflicting legacy/system-key trees with one reviewed registry.
            TRUNCATE TABLE ops.settings_nodes;

            INSERT INTO ops.settings_nodes
                (code, name, node_type, system_key, ord, locked)
            VALUES
                ('hr', '인사', 'group', 'domain.hr', 10, true),
                ('contract', '계약', 'group', 'domain.contract', 20, true),
                ('event', '업무 이벤트', 'group', 'domain.event', 30, true);

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, field_ref, ord, locked)
            SELECT root.id, seed.code, seed.name, 'category', seed.field_ref, seed.ord, true
              FROM ops.settings_nodes root
              JOIN (VALUES
                  ('domain.hr', 'employment_type', '고용형태', 'employee.employment_type', 10),
                  ('domain.hr', 'status', '재직상태', 'employee.status', 20),
                  ('domain.hr', 'technical_grade', '기술등급', 'employee.technical_grade', 30),
                  ('domain.hr', 'position_grade', '직급', 'employee.position_grade', 40),
                  ('domain.hr', 'position_title', '직위', 'employee.position_title', 50),
                  ('domain.contract', 'kind', '계약형태', 'contract.kind', 10),
                  ('domain.event', 'stage', '업무단계', 'event.stage', 10),
                  ('domain.event', 'type', '업무유형', 'event.type', 20)
              ) seed(root_key, code, name, field_ref, ord)
                ON root.system_key = seed.root_key;

            INSERT INTO ops.settings_nodes (parent_id, code, name, node_type, ord)
            SELECT category.id, seed.code, seed.name, 'value', seed.ord
              FROM ops.settings_nodes category
              JOIN (VALUES
                  ('employee.employment_type', '정규직', '정규직', 10),
                  ('employee.employment_type', '계약직', '계약직', 20),
                  ('employee.employment_type', '일용직', '일용직', 30),
                  ('employee.employment_type', '파견', '파견', 40),
                  ('employee.employment_type', '용역', '용역', 50),
                  ('employee.employment_type', '프리랜서', '프리랜서', 60),
                  ('employee.employment_type', '인턴', '인턴', 70),
                  ('employee.status', '재직', '재직', 10),
                  ('employee.status', '휴직', '휴직', 20),
                  ('employee.status', '퇴사', '퇴사', 30),
                  ('employee.technical_grade', '초급', '초급', 10),
                  ('employee.technical_grade', '중급', '중급', 20),
                  ('employee.technical_grade', '고급', '고급', 30),
                  ('employee.technical_grade', '특급', '특급', 40),
                  ('employee.position_grade', '임원', '임원', 10),
                  ('employee.position_grade', '부장', '부장', 20),
                  ('employee.position_grade', '차장', '차장', 30),
                  ('employee.position_grade', '과장', '과장', 40),
                  ('employee.position_grade', '대리', '대리', 50),
                  ('employee.position_grade', '주임', '주임', 60),
                  ('employee.position_grade', '사원', '사원', 70),
                  ('employee.position_grade', '인턴', '인턴', 80),
                  ('employee.position_title', '대표', '대표', 5),
                  ('employee.position_title', '대표이사', '대표이사', 10),
                  ('employee.position_title', '본부장', '본부장', 20),
                  ('employee.position_title', '부문장', '부문장', 30),
                  ('employee.position_title', '실장', '실장', 40),
                  ('employee.position_title', '팀장', '팀장', 50),
                  ('employee.position_title', '파트장', '파트장', 60),
                  ('employee.position_title', '팀원', '팀원', 70),
                  ('contract.kind', '총액', '총액계약', 10),
                  ('contract.kind', '공동', '공동계약', 20),
                  ('contract.kind', '장기계속', '장기계속공사', 30),
                  ('contract.kind', '단가', '단가계약', 40),
                  ('contract.kind', '하도급', '하도급계약', 50)
              ) seed(field_ref, code, name, ord)
                ON category.field_ref = seed.field_ref;

            -- Process Stage is limited to the six lifecycle stages. Settlement
            -- is deliberately not a Stage.
            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'category', seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('preparation', '준비', 'workflow.stage.preparation', 10),
                  ('contract', '계약', 'workflow.stage.contract', 20),
                  ('kickoff', '착수', 'workflow.stage.kickoff', 30),
                  ('execution', '수행', 'workflow.stage.execution', 40),
                  ('closeout', '준공', 'workflow.stage.closeout', 50),
                  ('complete', '완료', 'workflow.stage.complete', 60)
              ) seed(code, name, system_key, ord)
             WHERE category.field_ref = 'event.stage';

            -- Event Types have their own grouping axis. The first six groups
            -- correspond to lifecycle stages; settlement remains event-only.
            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT category.id, seed.code, seed.name, 'category', seed.system_key, seed.ord, true
              FROM ops.settings_nodes category
              CROSS JOIN (VALUES
                  ('preparation', '준비', 'workflow.event_group.preparation', 10),
                  ('contract', '계약', 'workflow.event_group.contract', 20),
                  ('kickoff', '착수', 'workflow.event_group.kickoff', 30),
                  ('execution', '수행', 'workflow.event_group.execution', 40),
                  ('closeout', '준공', 'workflow.event_group.closeout', 50),
                  ('complete', '완료', 'workflow.event_group.complete', 60),
                  ('settlement', '정산', 'workflow.event_group.settlement', 70)
              ) seed(code, name, system_key, ord)
             WHERE category.field_ref = 'event.type';

            INSERT INTO ops.settings_nodes
                (parent_id, code, name, node_type, system_key, ord, locked)
            SELECT event_group.id, seed.code, seed.name, 'value', seed.system_key, seed.ord, true
              FROM ops.settings_nodes event_group
              JOIN (VALUES
                  ('workflow.event_group.preparation', 'estimate', '견적', 'workflow.event.estimate', 10),
                  ('workflow.event_group.preparation', 'bid', '입찰', 'workflow.event.bid', 20),
                  ('workflow.event_group.preparation', 'award', '낙찰', 'workflow.event.award', 30),
                  ('workflow.event_group.contract', 'contract_signed', '체결', 'workflow.event.contract_signed', 10),
                  ('workflow.event_group.contract', 'contract_change', '변경', 'workflow.event.contract_change', 20),
                  ('workflow.event_group.contract', 'contract_cancel', '취소', 'workflow.event.contract_cancel', 30),
                  ('workflow.event_group.kickoff', 'kickoff_submitted', '착수계', 'workflow.event.kickoff_submitted', 10),
                  ('workflow.event_group.kickoff', 'kickoff_meeting', '착수회의', 'workflow.event.kickoff_meeting', 20),
                  ('workflow.event_group.kickoff', 'kickoff_approved', '착수승인', 'workflow.event.kickoff_approved', 30),
                  ('workflow.event_group.execution', 'progress_report', '업무보고', 'workflow.event.progress_report', 10),
                  ('workflow.event_group.execution', 'suspend', '중지', 'workflow.event.suspend', 20),
                  ('workflow.event_group.execution', 'resume', '재개', 'workflow.event.resume', 30),
                  ('workflow.event_group.closeout', 'closeout_submitted', '준공계', 'workflow.event.closeout_submitted', 10),
                  ('workflow.event_group.closeout', 'closeout_inspection', '준공검사', 'workflow.event.closeout_inspection', 20),
                  ('workflow.event_group.closeout', 'closeout_approved', '준공승인', 'workflow.event.closeout_approved', 30),
                  ('workflow.event_group.settlement', 'advance_payment', '선급금', 'workflow.event.advance_payment', 10),
                  ('workflow.event_group.settlement', 'progress_payment', '기성금', 'workflow.event.progress_payment', 20),
                  ('workflow.event_group.settlement', 'final_payment', '준공금', 'workflow.event.final_payment', 30)
              ) seed(group_key, code, name, system_key, ord)
                ON event_group.system_key = seed.group_key;

            -- Reviewed, lossy normalization is intentional for the initial data phase.
            UPDATE ops.process_events SET stage = CASE stage
                WHEN 'pre_contract' THEN 'preparation' WHEN 'inspection' THEN 'closeout'
                WHEN 'billing' THEN 'settlement' WHEN 'blilling' THEN 'settlement'
                WHEN 'project' THEN 'execution' ELSE stage END;
            UPDATE ops.process_events SET event_type = CASE event_type
                WHEN 'contract_doc' THEN 'contract_signed' WHEN 'kickoff' THEN 'kickoff_submitted'
                WHEN 'kickoff_doc' THEN 'kickoff_submitted' WHEN 'kickoff_approval' THEN 'kickoff_approved'
                WHEN 'work_report' THEN 'progress_report' WHEN 'inspection_request' THEN 'closeout_inspection'
                WHEN 'inspection' THEN 'closeout_inspection' WHEN 'completion_doc' THEN 'closeout_submitted'
                WHEN 'completion_inspection' THEN 'closeout_inspection'
                WHEN 'correction_request' THEN 'closeout_inspection' WHEN 'reinspection' THEN 'closeout_inspection'
                WHEN 'delivery' THEN 'closeout_submitted' WHEN 'period_extension' THEN 'contract_change'
                WHEN 'closeout_complete' THEN 'closeout_approved' WHEN 'completion_approval' THEN 'closeout_approved'
                WHEN 'progress_invoice' THEN 'progress_payment'
                WHEN 'invoice' THEN 'final_payment' WHEN 'tax_invoice' THEN 'final_payment'
                WHEN 'payment' THEN 'final_payment' ELSE event_type END;

            -- 직급·직위의 source of truth is now the unified registry.
            DROP TABLE IF EXISTS hr.job_grades;
            DROP TABLE IF EXISTS hr.job_positions;
            """,
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
