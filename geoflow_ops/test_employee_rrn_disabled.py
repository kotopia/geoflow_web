from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class EmployeeRrnDisabledStaticTests(unittest.TestCase):
    def test_employee_views_reject_rrn_and_have_no_crypto_path(self):
        source = (ROOT / "views_employees.py").read_text(encoding="utf-8")
        self.assertIn('request.POST.get("rrn_plain")', source)
        self.assertIn("주민등록번호는 GeoFlow에서 수집하지 않습니다.", source)
        for forbidden in (
            "pgp_sym_encrypt",
            "pgp_sym_decrypt",
            "RRN_SYM_KEY",
            "rrn_cipher",
            "rrn_hash",
            "rrn_last4",
            "sha256(",
        ):
            self.assertNotIn(forbidden, source)

    def test_employee_template_has_no_rrn_or_demo_identity_content(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "employees" / "employee_detail.html"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "rrn_plain",
            "rrn_masked",
            "주민등록번호",
            "주민번호",
            "관저동로",
            "staciehall.co",
            "정보처리기사",
            "지도제작기능사",
            "운전면허증",
            "Twitter",
            "Facebook",
            "Instagram",
            "LinkedIn",
        ):
            self.assertNotIn(forbidden, source)

    def test_employee_upload_helper_sends_canonical_parent_key(self):
        source = (
            ROOT / "static" / "geoflow_ops" / "js" / "upload-utils.js"
        ).read_text(encoding="utf-8")
        self.assertIn("parent_attachment_id: parentId", source)
        self.assertNotIn("parent_id: parentId", source)
        self.assertIn('entityType: "event"', source)
        self.assertIn("eventId: params.eventId", source)


if __name__ == "__main__":
    unittest.main()
