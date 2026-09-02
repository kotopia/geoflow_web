from decimal import Decimal

from django.test import SimpleTestCase
from openpyxl import Workbook

from .finance_import_views_v2 import _find_header, _headers, _money, _norm_company


class FinanceImportV2PureTests(SimpleTestCase):
    def test_hometax_header_can_be_detected_below_first_row(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["전자세금계산서 목록"])
        ws.append(["조회기간", "2026-08-01~2026-08-31"])
        ws.append([])
        ws.append([
            "작성일자",
            "공급자 사업자등록번호",
            "공급자 상호",
            "공급받는자 사업자등록번호",
            "공급받는자 상호",
            "공급가액합계",
            "세액합계",
        ])
        row_no, mapping, _ = _find_header(ws, "invoice")
        self.assertEqual(row_no, 4)
        self.assertIn("written_date", mapping)
        self.assertIn("supplier_biz_no", mapping)
        self.assertIn("recipient_name", mapping)
        self.assertIn("supply_amount", mapping)
        self.assertIn("vat_amount", mapping)

    def test_header_normalization_accepts_spacing_and_punctuation(self):
        mapping = _headers(["공급자 사업자등록번호", "공급가액 합계", "발급일자"])
        self.assertIn("supplier_biz_no", mapping)
        self.assertIn("supply_amount", mapping)
        self.assertIn("issued_date", mapping)

    def test_company_normalization_ignores_legal_prefix_and_suffix(self):
        self.assertEqual(_norm_company("주식회사 지오플로우"), "지오플로우")
        self.assertEqual(_norm_company("지오플로우(주)"), "지오플로우")
        self.assertEqual(_norm_company("㈜ 지오플로우"), "지오플로우")

    def test_money_accepts_commas_and_rounds_to_won(self):
        self.assertEqual(_money("1,234.5"), Decimal("1235"))
        self.assertIsNone(_money(""))
