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

    def test_environment_settings_no_longer_exposes_department_editor(self):
        template = self._read("geoflow_ops/templates/geoflow_ops/settings/settings_page.html")
        self.assertNotIn("settings_department_save", template)
        self.assertNotIn("새 담당부서", template)
        self.assertIn("나의 기업정보로 이동", template)

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
