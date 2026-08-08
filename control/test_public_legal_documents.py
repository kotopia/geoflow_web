from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = ROOT / "control"


class PublicLegalDocumentContractTests(TestCase):
    def test_public_terms_and_privacy_routes_are_registered_before_tenant_routes(self):
        source = (ROOT / "geoflow_project" / "urls.py").read_text(encoding="utf-8")

        terms_pos = source.index("path('terms/'")
        privacy_pos = source.index("path('privacy/'")
        tenant_pos = source.index("path('', include(('geoflow_ops.urls'")
        self.assertLess(terms_pos, tenant_pos)
        self.assertLess(privacy_pos, tenant_pos)
        self.assertIn("views_legal.terms_view", source)
        self.assertIn("views_legal.privacy_view", source)

    def test_legal_pages_are_explicitly_draft_until_required_policy_is_configured(self):
        source = (CONTROL_DIR / "views_legal.py").read_text(encoding="utf-8")

        for setting_name in (
            "GEOFLOW_LEGAL_OPERATOR_NAME",
            "GEOFLOW_LEGAL_ADDRESS",
            "GEOFLOW_LEGAL_CONTACT_EMAIL",
            "GEOFLOW_PRIVACY_OFFICER_NAME",
            "GEOFLOW_PRIVACY_CONTACT_EMAIL",
            "GEOFLOW_PRIVACY_CONTACT_PHONE",
            "GEOFLOW_SIGNUP_RETENTION_POLICY",
            "GEOFLOW_DESTRUCTION_POLICY",
            "GEOFLOW_THIRD_PARTY_DISCLOSURE",
            "GEOFLOW_PROCESSING_OUTSOURCING_DISCLOSURE",
            "GEOFLOW_EMAIL_PROCESSOR_DISCLOSURE",
            "GEOFLOW_CROSS_BORDER_DISCLOSURE",
            "GEOFLOW_COOKIE_DISCLOSURE",
        ):
            self.assertIn(setting_name, source)
        self.assertIn('"is_draft": bool(missing)', source)
        self.assertIn("def legal_documents_ready()", source)
        self.assertIn("return all(", source)

    def test_signup_remains_closed_until_legal_documents_are_ready_and_confirmed(self):
        source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")

        self.assertIn("and legal_documents_ready()", source)
        self.assertIn("and _legal_documents_confirmed()", source)
        self.assertIn("SIGNUP_LEGAL_DOCUMENTS_CONFIRMED", source)
        self.assertIn("return False", source)

    def test_templates_cover_required_privacy_policy_structure(self):
        privacy = (
            CONTROL_DIR / "templates" / "control" / "privacy.html"
        ).read_text(encoding="utf-8")
        terms = (
            CONTROL_DIR / "templates" / "control" / "terms.html"
        ).read_text(encoding="utf-8")

        for required_text in (
            "비밀번호 해시",
            "처리 및 보유 기간",
            "파기 절차 및 방법",
            "제3자 제공",
            "처리위탁",
            "국외 이전",
            "자동수집 장치",
            "안전성 확보조치",
            "권리·의무 및 행사방법",
            "개인정보 문의 전화",
        ):
            self.assertIn(required_text, privacy)
        self.assertIn("이메일 인증과 관리자 심사", terms)
        self.assertIn("권한이 자동 부여되지는 않습니다", terms)
