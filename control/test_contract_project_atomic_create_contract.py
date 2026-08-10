from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
SECURITY_VIEWS = ROOT / "geoflow_ops" / "security_views.py"
PAIR_SERVICE = ROOT / "geoflow_ops" / "services" / "contract_project_pair.py"


class ContractProjectAtomicCreateContractTests(TestCase):
    def test_active_contract_create_path_is_tenant_atomic(self):
        text = SECURITY_VIEWS.read_text()
        self.assertIn('if request.method != "POST":', text)
        self.assertIn("with transaction.atomic(using=alias):", text)
        self.assertIn("response = views_contracts.contract_create(request)", text)
        self.assertIn("contract_id = contract_id_from_create_response(response)", text)
        self.assertIn("create_project_for_new_contract(alias, contract)", text)

    def test_validation_response_does_not_create_project(self):
        text = SECURITY_VIEWS.read_text()
        response_guard = 'if not (300 <= int(getattr(response, "status_code", 0)) < 400):'
        self.assertIn(response_guard, text)
        self.assertLess(text.index(response_guard), text.index("create_project_for_new_contract(alias, contract)"))

    def test_pair_service_rejects_existing_project(self):
        text = PAIR_SERVICE.read_text()
        self.assertIn("filter(contract_id=contract.pk).count()", text)
        self.assertIn('raise RuntimeError("new contract already has a project")', text)

    def test_pair_service_uses_canonical_contract_fields(self):
        text = PAIR_SERVICE.read_text()
        for expected in (
            '"contract_id": contract.pk',
            '"name": contract.name',
            '"start_date": contract.start_date',
            '"end_date": contract.end_date',
            '"status": "active"',
            '"ext": {}',
        ):
            self.assertIn(expected, text)

    def test_no_swallowed_project_creation_exception(self):
        text = SECURITY_VIEWS.read_text()
        create_index = text.index("create_project_for_new_contract(alias, contract)")
        window = text[max(0, create_index - 500): create_index + 300]
        self.assertNotIn("except Exception", window)
        self.assertNotIn("pass", window)
