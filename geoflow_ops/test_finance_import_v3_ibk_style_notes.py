from django.test import SimpleTestCase

from .finance_import_views_v3 import _headers


class FinanceImportV3ReaderContractTests(SimpleTestCase):
    def test_ibk_header_fields_are_style_independent(self):
        mapping = _headers([" ", "거래일시", "출금", "입금", "거래후 잔액", "거래내용", "상대계좌번호", "상대은행", "메모", "거래구분", "수표어음금액", "CMS코드", "상대계좌예금주명"])
        self.assertIn("transaction_date", mapping)
        self.assertIn("withdraw_amount", mapping)
        self.assertIn("deposit_amount", mapping)
        self.assertIn("counterparty_name", mapping)
