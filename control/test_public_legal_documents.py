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

    def test_final_legal_policy_has_public_defaults_and_stable_versions(self):
        source = (CONTROL_DIR / "legal_policy.py").read_text(encoding="utf-8")

        for expected in (
            'DEFAULT_TERMS_VERSION = "2026-08-08-v1"',
            'DEFAULT_PRIVACY_VERSION = "2026-08-08-v1"',
            '"geoflow-manager/GeoFlow"',
            '"대전광역시"',
            '"peako"',
            '"042-822-8636"',
            '"kotopia79@naver.com"',
            '"ap-northeast-2"',
            '"NAVER',
            '"1년간 보관한 후 "',
        ):
            self.assertIn(expected, source)

    def test_legal_pages_resolve_policy_from_single_policy_module(self):
        source = (CONTROL_DIR / "views_legal.py").read_text(encoding="utf-8")

        self.assertIn("REQUIRED_LEGAL_FIELDS", source)
        self.assertIn("DEFAULT_TERMS_VERSION", source)
        self.assertIn("DEFAULT_PRIVACY_VERSION", source)
        self.assertIn("legal_document_version", source)
        self.assertIn('"is_draft": bool(missing)', source)
        self.assertIn("def legal_documents_ready()", source)
        self.assertIn("LEGAL_ESTABLISHED_DATE", source)
        self.assertIn("LEGAL_EFFECTIVE_DATE_LABEL", source)

    def test_signup_remains_closed_until_legal_documents_are_explicitly_confirmed(self):
        source = (CONTROL_DIR / "views_signup.py").read_text(encoding="utf-8")

        self.assertIn("and legal_documents_ready()", source)
        self.assertIn("and _legal_documents_confirmed()", source)
        self.assertIn("SIGNUP_LEGAL_DOCUMENTS_CONFIRMED", source)
        self.assertIn("return False", source)
        self.assertNotIn("SIGNUP_LEGAL_DOCUMENTS_CONFIRMED = True", source)

    def test_templates_cover_final_privacy_and_terms_structure(self):
        privacy = (
            CONTROL_DIR / "templates" / "control" / "privacy.html"
        ).read_text(encoding="utf-8")
        terms = (
            CONTROL_DIR / "templates" / "control" / "terms.html"
        ).read_text(encoding="utf-8")
        signup = (
            CONTROL_DIR / "templates" / "control" / "signup.html"
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
            "개인정보 보호책임자 및 문의처",
            "개인정보 처리방침의 변경",
        ):
            self.assertIn(required_text, privacy)

        for required_text in (
            "회원가입 신청 및 승인",
            "권한이 자동 부여되지는",
            "이용자가 등록하는 업무자료",
            "개인정보 보호",
            "약관의 변경",
            "준거법",
        ):
            self.assertIn(required_text, terms)

        for required_text in (
            "[필수]",
            "개인정보 수집·이용 안내",
            "필수 개인정보 수집·이용에 동의하지 않은 권리",
            "signup_terms_version",
            "signup_privacy_version",
        ):
            self.assertIn(required_text, signup)

        self.assertNotIn('name="contact_phone"', signup)
        self.assertNotIn('name="invitation_code"', signup)
        self.assertIn("초기 공개 회원가입에서는 연락처와 초대 코드를 수집하지 않습니다", privacy)
