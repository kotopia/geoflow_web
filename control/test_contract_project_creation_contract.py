from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "geoflow_ops" / "services" / "contract_project_creation.py"
VIEW = ROOT / "geoflow_ops" / "views_contract_creation.py"
SECURITY = ROOT / "geoflow_ops" / "security_views.py"


class ContractProjectCreationContractTests(TestCase):
    def test_active_security_route_uses_atomic_creation_view(self):
        text = SECURITY.read_text()
        self.assertIn("views_contract_creation", text)
        self.assertIn("return views_contract_creation.contract_create(request)", text)
        self.assertIn('_require(request, "contracts.create")', text)

    def test_service_wraps_contract_and_project_in_one_tenant_transaction(self):
        text = SERVICE.read_text()
        self.assertIn("with transaction.atomic(using=alias):", text)
        self.assertIn("contract.save(using=alias)", text)
        self.assertIn("create_project_for_contract(alias, contract", text)
        self.assertIn('"contract": contract', text)
        self.assertIn('"ext": {}', text)

    def test_project_mapping_is_contract_derived(self):
        text = SERVICE.read_text()
        for required in (
            '"name": contract.name',
            '"start_date": contract.start_date',
            '"end_date": contract.end_date',
            '"status": contract.status or "active"',
            '"org_unit_id": getattr(contract, "org_unit_id", None)',
        ):
            self.assertIn(required, text)

    def test_new_view_does_not_silently_swallow_project_failures(self):
        text = VIEW.read_text()
        self.assertNotIn("except Exception", text)
        self.assertNotIn("pass\n", text)
        self.assertIn("save_new_contract_with_project", text)
        self.assertIn("logger.exception", text)
