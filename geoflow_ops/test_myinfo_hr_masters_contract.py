from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent.parent


class MyInfoHRMastersContractTests(SimpleTestCase):
    def _read(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_migration_is_additive_and_seeds_common_defaults(self):
        source = self._read("geoflow_ops/migrations/0025_myinfo_hr_masters.py")
        self.assertIn("CREATE TABLE IF NOT EXISTS hr.job_grades", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS hr.job_positions", source)
        self.assertIn("system_default boolean NOT NULL DEFAULT false", source)
        for value in ("임원", "부장", "차장", "과장", "대리", "주임", "사원", "인턴"):
            self.assertIn(value, source)
        for value in ("대표", "대표이사", "본부장", "부문장", "실장", "팀장", "파트장", "팀원"):
            self.assertIn(value, source)
        lowered = source.lower()
        self.assertNotIn("delete from hr.employee_profile", lowered)
        self.assertNotIn("update hr.employee_profile", lowered)
        self.assertNotIn("drop table hr.departments", lowered)

    def test_migration_preserves_legacy_and_employee_values_without_rewriting_employees(self):
        source = self._read("geoflow_ops/migrations/0025_myinfo_hr_masters.py")
        self.assertIn("category.system_key = 'hr.position_grade'", source)
        self.assertIn("category.system_key = 'hr.position_title'", source)
        self.assertIn("SELECT DISTINCT btrim(position_grade) AS name", source)
        self.assertIn("SELECT DISTINCT btrim(title) AS name", source)
        self.assertIn("UPDATE hr.job_grades master", source)
        self.assertIn("UPDATE hr.job_positions master", source)
        self.assertNotIn("UPDATE HR.EMPLOYEE_PROFILE", source.upper())

    def test_myinfo_owns_department_grade_and_position_management(self):
        template = self._read("geoflow_ops/templates/geoflow_ops/myinfo/orgunit_detail.html")
        self.assertIn("myinfo_department_save", template)
        self.assertIn("myinfo_job_grade_save", template)
        self.assertIn("myinfo_job_position_save", template)
        self.assertIn("전체 회사 공통", template)
        self.assertIn("form-switch", template)

    def test_company_detail_uses_four_tabs_and_reuses_private_attachments(self):
        template = self._read("geoflow_ops/templates/geoflow_ops/myinfo/orgunit_detail.html")
        document_tab = self._read("geoflow_ops/templates/geoflow_ops/myinfo/_company_document_tab.html")
        upload_view = self._read("geoflow_ops/views_uploads.py")
        upload_guard = self._read("geoflow_ops/upload_guard_views.py")
        detail_view = self._read("geoflow_ops/views_myinfo.py")

        for label in ("기본정보", "사업·등록 정보", "인증·평가", "조직·인사 기준"):
            self.assertIn(label, template)
        self.assertIn("nav nav-tabs card-header-tabs", template)
        self.assertIn('class="card-header pb-0"', template)
        self.assertIn('class="row py-2 border-top"', template)
        self.assertIn("회사명", template)
        self.assertNotIn("설정", template)
        self.assertIn('name="document_title"', document_tab)
        self.assertIn('name="files" multiple', document_tab)
        self.assertIn('entityType: "orgunit"', template)
        self.assertIn('("orgunit", "business_registration")', upload_view)
        self.assertIn('("orgunit", "certification_evaluation")', upload_view)
        self.assertIn('meta={"document_title": document_title}', upload_view)
        self.assertIn("GEOFLOW_UPLOAD_ORGUNIT_DOC_MAX_BYTES", upload_guard)
        self.assertIn('entity_type="orgunit"', detail_view)

    def test_environment_settings_no_longer_exposes_department_editor(self):
        template = self._read("geoflow_ops/templates/geoflow_ops/settings/settings_page.html")
        self.assertNotIn("settings_department_save", template)
        self.assertNotIn("새 담당부서", template)
        self.assertIn("나의 기업정보로 이동", template)
        self.assertIn("hr.position_grade", template)
        self.assertIn("hr.position_title", template)
        self.assertIn("hiddenIds", template)

    def test_company_info_menu_is_below_settings_and_not_in_topbar(self):
        sidebar = self._read("geoflow_ops/templates/geoflow_ops/partials/sidebar.html")
        topbar = self._read("geoflow_ops/templates/geoflow_ops/partials/topbar.html")
        settings_position = sidebar.index("환경설정")
        company_position = sidebar.index("나의 기업정보")

        self.assertLess(settings_position, company_position)
        self.assertIn("myinfo_orgunit_list", sidebar)
        self.assertNotIn("myinfo_orgunit_list", topbar)

    def test_employee_options_use_hr_master_with_legacy_fallback(self):
        source = self._read("geoflow_ops/employee_security_views.py")
        self.assertIn('category in {"position_grade", "position_title"}', source)
        self.assertIn("master_table_exists(alias, category)", source)
        self.assertIn("list_master_options(alias, category, active_only=True)", source)
        self.assertIn("return views_employee_profile.hr_options(request, category)", source)

    def test_used_grade_or_position_cannot_be_disabled(self):
        source = self._read("geoflow_ops/views_myinfo.py")
        self.assertIn('"position_grade": "position_grade"', source)
        self.assertIn('"position_title": "title"', source)
        self.assertIn("FROM hr.employee_profile", source)
        self.assertIn("직원 정보를 먼저 변경한 뒤 사용 중지하세요", source)

    def test_routes_are_permission_wrapped_and_legacy_department_route_remains(self):
        urls = self._read("geoflow_ops/urls.py")
        security = self._read("geoflow_ops/myinfo_security_views.py")
        self.assertIn("myinfo_department_save", urls)
        self.assertIn("myinfo_job_grade_save", urls)
        self.assertIn("myinfo_job_position_save", urls)
        self.assertIn("settings_department_save", urls)
        self.assertIn('gf_has_perm(request, "directory.edit")', security)

    def test_production_activation_is_protected_and_pinned_to_0025(self):
        workflow = self._read(".github/workflows/phase4-myinfo-hr-masters-production-activation.yml")
        self.assertIn("environment: production", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("candidate_sha_not_current_release_head", workflow)
        self.assertIn("geoflow_ops/migrations/0025_myinfo_hr_masters.py", workflow)
        self.assertIn('DEPENDENCY = "0024_phase4_workflow_handoff_and_contract_access"', workflow)
        self.assertIn('MIGRATION = "0025_myinfo_hr_masters"', workflow)
        self.assertIn("myinfo_hr_activation_db_complete=yes", workflow)

    def test_production_activation_preserves_existing_hr_and_settings_data(self):
        workflow = self._read(".github/workflows/phase4-myinfo-hr-masters-production-activation.yml")
        self.assertIn('"employee_digest": relation_digest(cur, "hr.employee_profile")', workflow)
        self.assertIn('"department_digest": relation_digest(cur, "hr.departments")', workflow)
        self.assertIn('"settings_digest": relation_digest(cur, "ops.settings_nodes")', workflow)
        self.assertIn("protected row count changed", workflow)
        self.assertIn("protected content changed", workflow)
        self.assertIn("existing employee grade not represented by active master", workflow)
        self.assertIn("existing employee position not represented by active master", workflow)
        self.assertIn("legacy settings grade missing from master", workflow)
        self.assertIn("legacy settings position missing from master", workflow)

    def test_production_activation_deploys_only_stabilized_geoflow_service(self):
        workflow = self._read(".github/workflows/phase4-myinfo-hr-masters-production-activation.yml")
        self.assertIn("service='geoflow-stabilized.service'", workflow)
        self.assertIn("collectstatic --noinput", workflow)
        self.assertIn("systemctl restart \"$service\"", workflow)
        self.assertIn("https://geoflow.co.kr/login/", workflow)
        self.assertIn("myinfo_hr_activation_public_login_status", workflow)
        self.assertIn("myinfo_hr_activation_code_rollback_completed=yes", workflow)
        self.assertNotIn("iroomsng.service", workflow)
