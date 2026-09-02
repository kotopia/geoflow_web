from decimal import Decimal

from django.test import SimpleTestCase

from .finance_import_views_v3 import _WorksheetRows, _find_header, _headers, _split_direction_amount


class FinanceImportV3BankTests(SimpleTestCase):
    def test_ibk_header(self):
        rows = _WorksheetRows([
            ["title"],
            ["account"],
            ["", "거래일시", "출금", "입금", "거래후 잔액", "거래내용", "상대계좌번호", "상대은행", "메모", "거래구분", "수표어음금액", "CMS코드", "상대계좌예금주명"],
            ["1", "2026-08-11 09:08:46", "0", "600000", "47971867", "김두환", "", "우체국", "", "타CD", "0", "", "김두환"],
        ])
        row_no, mapping, _ = _find_header(rows, "transaction")
        self.assertEqual(row_no, 3)
        tx_type, amount, error = _split_direction_amount(list(rows.iter_rows(min_row=4, max_row=4))[0], mapping, "in", "out")
        self.assertEqual(tx_type, "in")
        self.assertEqual(amount, Decimal("600000"))
        self.assertIsNone(error)

    def test_nonghyup_split_columns(self):
        mapping = _headers(["구분", "거래일자", "출금금액(원)", "입금금액(원)", "거래 후 잔액(원)", "거래내용", "거래기록사항", "거래점", "거래시간", "이체메모"])
        self.assertIn("withdraw_amount", mapping)
        self.assertIn("deposit_amount", mapping)
        self.assertNotIn("transaction_type", mapping)
        row = ["2", "2026/08/18", "1752210", "", "17707748", "G-하나은행", "22024성과심사비", "농협 002044", "10:55:12", ""]
        tx_type, amount, error = _split_direction_amount(row, mapping, "in", "out")
        self.assertEqual(tx_type, "out")
        self.assertEqual(amount, Decimal("1752210"))
        self.assertIsNone(error)
