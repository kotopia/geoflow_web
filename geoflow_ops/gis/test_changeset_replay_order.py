from contextlib import ExitStack, nullcontext
from unittest import TestCase
from unittest.mock import Mock, patch
from . import changeset as service
from .qgis_sync import SyncConflict


class ReplayOrderTests(TestCase):
    payload = {'client_id':'11111111-1111-4111-8111-111111111111', 'changeset_id':'22222222-2222-4222-8222-222222222222', 'base_revision':1, 'changes':[]}

    def run_request(self, receipt, validator):
        with ExitStack() as stack:
            for name, result in [('changeset_runtime_enabled',True),('_layer_specs',[]),('allowed_standard_names',set()),('_ensure_project_state',2),('_receipt_replay',receipt),('_reserve_receipt',True)]:
                stack.enter_context(patch.object(service,name,return_value=result))
            stack.enter_context(patch.object(service.transaction,'atomic',side_effect=lambda **_:nullcontext()))
            return service.apply_project_changeset('isolated',project_id='p',plan={},payload=self.payload,validate_before_apply=validator)

    def test_committed_retry_returns_receipt_before_stale_version_check(self):
        validator = Mock(side_effect=AssertionError('Must not revalidate a committed retry'))
        receipt = {'ok':True,'replayed':True,'current_revision':2}
        self.assertEqual(self.run_request(receipt,validator),receipt)
        validator.assert_not_called()

    def test_new_request_still_rejects_actual_conflict(self):
        validator = Mock(side_effect=SyncConflict([{'reason':'server_object_changed'}]))
        with self.assertRaises(SyncConflict):
            self.run_request(None,validator)
        validator.assert_called_once_with()
