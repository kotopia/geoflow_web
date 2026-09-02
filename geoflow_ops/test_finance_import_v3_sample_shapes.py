from django.test import SimpleTestCase

from .finance_import_views_v3 import _WorksheetRows, _find_header


class FinanceImportV3SampleShapeTests(SimpleTestCase):
    def test_nonghyup_header_detected_at_row_ten(self):
        rows = _WorksheetRows([
            ["입출금거래내역조회 결과"],
            [], [], ["2026년 09월 02일 16시19분17초"], [],
            ["계좌번호", "", "301-0286-5847-71"],
            ["예금주명", "", "주식회사 선화에스앤지"],
            ["현재통장잔액", "", "3,053,358원"],
            [],
            ["구분", "거래일자", "출금금액(원)", "입금금액(원)", "거래 후 잔액(원)", "거래내용", "거래기록사항", "거래점", "거래시간", "이체메모"],
        ])
        row_no, mapping, _ = _find_header(rows, "transaction")
        self.assertEqual(row_no, 10)
        self.assertIn("transaction_date", mapping)
        self.assertIn("withdraw_amount", mapping)
        self.assertIn("deposit_amount", mapping)
