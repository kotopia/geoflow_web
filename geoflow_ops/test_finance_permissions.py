"""DB/S3-free regressions for the independent Finance permission boundary."""
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from geoflow_ops import (
    event_security_views, finance_attachment_views, finance_documents_views,
    finance_import_views_v5, finance_security_views, upload_guard_views,
    views_calendar, views_events, views_uploads, views_workboard,
)
from geoflow_ops.models import ProcessEvent
from geoflow_ops.services import entity_access, finance_access
from geoflow_ops.services.active_event_badges import active_event_labels_for_contracts
from geoflow_ops.services.workflow_state import contract_workflow_summaries


def request_for(perms=(), *, method="get", data=None, roles=()):
    factory = RequestFactory()
    if method == "get":
        request = factory.get("/", data=data or {})
    else:
        request = getattr(factory, method)("/", data=json.dumps(data or {}), content_type="application/json")
    request.user = SimpleNamespace(is_authenticated=True, username="test-actor")
    request.session = {"scope": "tenant", "tenant_db_alias": "tenant-test"}
    request._gf_perms_cache = set(perms)
    request._gf_roles_cache = set(roles)
    return request


def event_for(*, finance=False, scope="contract", scope_id=None):
    return ProcessEvent(
        id=uuid4(), scope_type=scope, scope_id=scope_id or uuid4(),
        stage="settlement" if finance else "execution",
        event_type="advance_payment" if finance else "progress_report",
        title="Financial event" if finance else "Work event", status="open",
        occurred_at=date(2026, 10, 13), payload={}, created_by="test-actor",
    )


class FinancePermissionPolicyTests(SimpleTestCase):
    def test_contract_permissions_and_roles_never_imply_finance_access(self):
        request = request_for({"contracts.view", "contracts.edit", "contracts.create"}, roles={"tenant_admin", "manager"})
        self.assertFalse(finance_access.can_view_finance(request))
        self.assertFalse(finance_access.can_edit_finance(request))

    def test_read_and_write_are_independent_and_write_requires_read(self):
        reader = request_for({"finance.view"})
        self.assertTrue(finance_access.can_view_finance(reader))
        self.assertFalse(finance_access.can_edit_finance(reader))
        self.assertFalse(finance_access.can_edit_finance(request_for({"finance.edit"})))
        self.assertTrue(finance_access.can_edit_finance(request_for({"finance.view", "finance.edit"})))

    def test_missing_request_never_discloses_finance_badges(self):
        self.assertFalse(finance_access.can_view_finance(None))

    def test_settlement_custom_types_and_legacy_billing_are_protected(self):
        for stage, event_type in (
            ("settlement", "tenant_custom_code"), ("billing", "custom"),
            ("blilling", "custom"), ("execution", "advance_payment"),
            ("contract", "progress_payment"), ("closeout", "final_payment"),
            ("execution", "invoice"), ("execution", "tax_invoice"),
            ("execution", "progress_invoice"), ("execution", "payment"),
        ):
            with self.subTest(stage=stage, event_type=event_type):
                self.assertTrue(finance_access.is_finance_event(stage, event_type))
        self.assertFalse(finance_access.is_finance_event("execution", "progress_report"))

    @patch("geoflow_ops.services.entity_access.require_tenant_context", side_effect=PermissionDenied)
    def test_finance_permission_cannot_cross_the_tenant_boundary(self, _guard):
        with self.assertRaises(PermissionDenied):
            finance_access.require_finance_access(request_for({"finance.view", "finance.edit"}), write=True)


class FinanceRoutePermissionTests(SimpleTestCase):
    def test_finance_reads_deny_contract_only_before_any_db_access(self):
        routes = (
            finance_security_views.finance_page, finance_security_views.finance_claims,
            finance_security_views.finance_invoices, finance_security_views.finance_payments,
            finance_security_views.finance_ledger, finance_security_views.finance_balance,
            finance_security_views.finance_settings, finance_security_views.finance_trash,
            finance_security_views.finance_org_options, finance_documents_views.finance_documents,
            finance_import_views_v5.finance_import,
        )
        with patch("geoflow_ops.services.entity_access.current_db_alias", return_value="tenant-test"):
            for view in routes:
                with self.subTest(view=view.__name__), self.assertRaises(PermissionDenied):
                    view(request_for({"contracts.view", "contracts.edit"}))
            for view in (finance_security_views.contract_finance_summary, finance_security_views.finance_contract_defaults):
                with self.subTest(view=view.__name__), self.assertRaises(PermissionDenied):
                    view(request_for({"contracts.view"}), uuid4())

    def test_finance_writes_deny_readers_before_sql_or_s3(self):
        routes = (
            finance_security_views.claim_save, finance_security_views.invoice_save,
            finance_security_views.payment_request_save, finance_security_views.transaction_save,
            finance_security_views.account_save, finance_security_views.card_save,
            finance_attachment_views.finance_attachment_presign,
            finance_attachment_views.finance_attachment_commit,
            finance_import_views_v5.finance_import,
        )
        with patch("geoflow_ops.services.entity_access.current_db_alias", return_value="tenant-test"):
            for view in routes:
                with self.subTest(view=view.__name__), self.assertRaises(PermissionDenied):
                    view(request_for({"finance.view", "contracts.edit"}, method="post"))
            for view in (finance_security_views.account_delete, finance_security_views.card_delete):
                with self.subTest(view=view.__name__), self.assertRaises(PermissionDenied):
                    view(request_for({"finance.view"}, method="post"), uuid4())
            for view in (finance_security_views.record_soft_delete, finance_security_views.record_restore, finance_security_views.record_hard_delete):
                with self.subTest(view=view.__name__), self.assertRaises(PermissionDenied):
                    view(request_for({"finance.view"}, method="post", roles={"tenant_admin"}), "invoice", uuid4())

    @patch("geoflow_ops.finance_pages_v4.finance_section")
    def test_finance_reader_can_enter_without_contract_permissions(self, section):
        with patch("geoflow_ops.services.entity_access.current_db_alias", return_value="tenant-test"):
            request = request_for({"finance.view"})
            finance_security_views.finance_page(request)
        section.assert_called_once_with(request, "dashboard")

    def test_finance_editor_can_write_without_contract_permissions(self):
        with patch("geoflow_ops.services.entity_access.current_db_alias", return_value="tenant-test"):
            request = request_for({"finance.view", "finance.edit"})
            self.assertEqual(finance_security_views._require_write(request), "tenant-test")
            with self.assertRaises(PermissionDenied):
                finance_security_views._require_tenant_admin(request)
            request._gf_roles_cache.add("tenant_admin")
            self.assertEqual(finance_security_views._require_tenant_admin(request), "tenant-test")

    def test_evidence_download_checks_finance_before_signing(self):
        with patch("geoflow_ops.services.entity_access.current_db_alias", return_value="tenant-test"), patch.object(finance_attachment_views, "generate_presigned_get_url") as signer:
            with self.assertRaises(PermissionDenied):
                finance_attachment_views.finance_attachment_download(request_for({"contracts.view"}), "invoice", uuid4())
            signer.assert_not_called()


class FinanceEventPermissionTests(SimpleTestCase):
    def test_update_wrapper_denies_before_reading_workflow_or_validating_payload(self):
        with patch.object(event_security_views, "require_tenant_context", return_value="tenant-test"), patch.object(event_security_views, "get_event_for_access", return_value=None), patch.object(event_security_views, "_workflow_error") as validator:
            response = event_security_views.event_update(request_for({"contracts.edit"}, method="post", data={"title": "Denied"}), uuid4())
            self.assertEqual(response.status_code, 403)
            validator.assert_not_called()

    def test_finance_editor_can_create_a_scoped_settlement_event(self):
        contract_id = uuid4()
        event = event_for(finance=True, scope_id=contract_id)
        cleaned = {"stage": "settlement", "event_type": "advance_payment", "status": "open"}
        with patch.object(views_events, "require_tenant_context", return_value="tenant-test"), patch.object(views_events, "authorize_scope_write", return_value=True), patch.object(views_events, "_validate_mutable_fields", return_value=(cleaned, None)), patch.object(views_events, "default_owner_department_id", return_value=None), patch.object(ProcessEvent, "objects") as manager:
            manager.using.return_value.create.return_value = event
            request = request_for({"contracts.edit", "finance.view", "finance.edit"}, method="post", data={"scope_type": "contract", "scope_id": str(contract_id), "stage": "settlement", "event_type": "advance_payment"})
            self.assertEqual(views_events.create_event(request).status_code, 200)
            self.assertEqual(manager.using.return_value.create.call_args.kwargs["contract_id"], contract_id)

    def test_existing_finance_event_remains_editable_for_authorized_editor(self):
        event = event_for(finance=True)
        event.save = MagicMock()
        with patch.object(views_events, "require_tenant_context", return_value="tenant-test"), patch.object(views_events, "get_event_for_access", return_value=event):
            request = request_for({"finance.view", "finance.edit"}, method="post", data={"title": "Updated settlement"})
            self.assertEqual(views_events.update_event(request, event.id).status_code, 200)
        event.save.assert_called_once_with(using="tenant-test")
        self.assertEqual(event.title, "Updated settlement")

    def test_legacy_list_filters_finance_before_attachment_lookup(self):
        ordinary, finance = event_for(), event_for(finance=True)
        request = request_for({"contracts.view"}, data={"scope_type": "contract", "scope_id": str(ordinary.scope_id)})
        with patch.object(views_events, "require_tenant_context", return_value="tenant-test"), patch.object(views_events, "authorize_scope_read", return_value=True), patch.object(entity_access, "authorize_scope_read", return_value=True), patch.object(ProcessEvent, "objects") as events, patch.object(views_events.ProcessEventAttachment, "objects") as links:
            events.using.return_value.filter.return_value.order_by.return_value = [ordinary, finance]
            links.using.return_value.filter.return_value.select_related.return_value.order_by.return_value = []
            body = json.loads(views_events.list_events(request).content)
        self.assertEqual([row["id"] for row in body["events"]], [str(ordinary.id)])
        links.using.return_value.filter.assert_called_once_with(event=ordinary)

    def test_create_requires_finance_edit_before_inserting_event(self):
        with patch.object(views_events, "require_tenant_context", return_value="tenant-test"), patch.object(views_events, "authorize_scope_write", return_value=True), patch.object(ProcessEvent, "objects") as manager:
            for perms in ({"contracts.edit"}, {"contracts.edit", "finance.view"}):
                request = request_for(perms, method="post", data={"scope_type": "contract", "scope_id": str(uuid4()), "stage": "settlement", "event_type": "advance_payment"})
                self.assertEqual(views_events.create_event(request).status_code, 403)
            manager.using.assert_not_called()

    def test_converting_work_event_to_finance_requires_finance_edit(self):
        event = event_for()
        event.save = MagicMock()
        with patch.object(views_events, "require_tenant_context", return_value="tenant-test"), patch.object(views_events, "get_event_for_access", return_value=event):
            request = request_for({"contracts.edit"}, method="post", data={"stage": "execution", "event_type": "payment"})
            self.assertEqual(views_events.update_event(request, event.id).status_code, 403)
        event.save.assert_not_called()

    def test_stored_finance_event_cannot_be_relabelled_or_deleted_without_permission(self):
        event = event_for(finance=True)
        with patch.object(ProcessEvent, "objects") as manager, patch.object(entity_access, "authorize_scope_write", return_value=True):
            manager.using.return_value.filter.return_value.first.return_value = event
            self.assertIsNone(entity_access.get_event_for_access(request_for({"contracts.edit"}), "tenant-test", event.id, write=True))
            self.assertIsNone(entity_access.get_event_for_access(request_for({"finance.view"}), "tenant-test", event.id, write=True))
            self.assertIs(entity_access.get_event_for_access(request_for({"finance.view", "finance.edit"}), "tenant-test", event.id, write=True), event)

    def test_finance_permission_does_not_override_project_scope(self):
        event = event_for(finance=True, scope="project")
        with patch.object(entity_access, "authorize_scope_read", return_value=False):
            self.assertFalse(entity_access.can_read_event(request_for({"finance.view"}), "tenant-test", event))

    def test_read_scope_cache_is_request_and_tenant_local(self):
        event = event_for()
        request = request_for({"contracts.view"})
        with patch.object(entity_access, "authorize_scope_read", side_effect=[True, False, False]) as authorize:
            self.assertTrue(entity_access.can_read_event(request, "tenant-test", event))
            self.assertTrue(entity_access.can_read_event(request, "tenant-test", event))
            self.assertFalse(entity_access.can_read_event(request, "other-tenant", event))
            self.assertFalse(entity_access.can_read_event(request_for({"contracts.view"}), "tenant-test", event))
            self.assertEqual(authorize.call_count, 3)

    def test_workflow_selector_excludes_finance_for_non_editors(self):
        options = {"stages": [("execution", "Work"), ("settlement", "Finance")], "statuses": [("open", "Open")], "types_by_stage": {"execution": [("progress_report", "Work"), ("payment", "Legacy finance")], "settlement": [("advance_payment", "Finance")]}}
        with patch.object(event_security_views, "require_tenant_context", return_value="tenant-test"), patch.object(event_security_views, "event_workflow_options", return_value=options):
            response = event_security_views.workflow_options(request_for({"finance.view"}))
        body = json.loads(response.content)
        self.assertEqual([row["code"] for row in body["stages"]], ["execution"])
        self.assertEqual([row["code"] for row in body["types_by_stage"]["execution"]], ["progress_report"])

    def test_generic_event_file_access_inherits_finance_permission(self):
        event = event_for(finance=True)
        attachment = SimpleNamespace(entity_type="event", entity_id=event.id, purpose="doc", meta={})
        with patch.object(ProcessEvent, "objects") as manager, patch.object(entity_access, "authorize_scope_read", return_value=True), patch.object(entity_access, "authorize_scope_write", return_value=True):
            manager.using.return_value.filter.return_value.first.return_value = event
            request = request_for({"contracts.view", "contracts.edit"})
            self.assertFalse(entity_access.authorize_attachment_read(request, "tenant-test", attachment))
            self.assertFalse(entity_access.authorize_attachment_write(request, "tenant-test", "event", event.id))


class FinanceEvidenceGenericRouteTests(SimpleTestCase):
    def test_contract_storage_owner_cannot_bypass_finance_access(self):
        for purpose, meta in (("finance_invoice", {}), ("finance_evidence", {}), ("doc", {"finance_record_type": "invoice"})):
            with self.subTest(purpose=purpose):
                attachment = SimpleNamespace(entity_type="contract", entity_id=uuid4(), purpose=purpose, meta=meta)
                request = request_for({"contracts.view", "contracts.edit"}, roles={"tenant_admin"})
                with patch.object(entity_access, "scope_exists") as exists:
                    self.assertFalse(entity_access.authorize_attachment_read(request, "tenant-test", attachment))
                    self.assertFalse(entity_access.authorize_attachment_write(request, "tenant-test", "contract", attachment.entity_id, attachment=attachment))
                    exists.assert_not_called()

    def test_finance_evidence_still_requires_tenant_entity_existence(self):
        attachment = SimpleNamespace(entity_type="contract", entity_id=uuid4(), purpose="finance_invoice", meta={})
        with patch.object(entity_access, "scope_exists", return_value=False):
            self.assertFalse(entity_access.authorize_attachment_read(request_for({"finance.view"}), "tenant-test", attachment))
        with patch.object(entity_access, "scope_exists", return_value=True):
            self.assertTrue(entity_access.authorize_attachment_read(request_for({"finance.view"}), "tenant-test", attachment))
            self.assertFalse(entity_access.authorize_attachment_write(request_for({"finance.view"}), "tenant-test", "contract", attachment.entity_id, attachment=attachment))
            self.assertTrue(entity_access.authorize_attachment_write(request_for({"finance.view", "finance.edit"}), "tenant-test", "contract", attachment.entity_id, attachment=attachment))

    def test_generic_file_routes_deny_before_signing_or_deleting(self):
        attachment = SimpleNamespace(id=uuid4(), entity_type="contract", entity_id=uuid4(), purpose="finance_invoice", meta={}, deleted_at=None, is_deleted=False, active=True, save=MagicMock())
        request = request_for({"contracts.view", "contracts.edit"})
        with patch.object(upload_guard_views, "require_tenant_context", return_value="tenant-test"), patch.object(upload_guard_views.Attachment, "objects") as manager, patch.object(upload_guard_views, "generate_presigned_get_url") as signer:
            manager.using.return_value.filter.return_value.first.return_value = attachment
            self.assertEqual(upload_guard_views.presign_get(request, attachment.id).status_code, 403)
            self.assertEqual(upload_guard_views.preview(request, attachment.id).status_code, 403)
            signer.assert_not_called()
        with patch.object(views_uploads, "require_tenant_context", return_value="tenant-test"), patch.object(views_uploads.Attachment, "objects") as manager:
            manager.using.return_value.filter.return_value.first.return_value = attachment
            self.assertEqual(views_uploads.delete_attachment(request_for({"contracts.edit"}, method="delete"), attachment.id).status_code, 403)
        attachment.save.assert_not_called()


class FinancePresentationPermissionTests(SimpleTestCase):
    def test_combined_timeline_filters_each_row_before_loading_metadata(self):
        contract_id = uuid4()
        ordinary = event_for(scope_id=contract_id)
        finance = event_for(finance=True, scope_id=contract_id)
        other_project = event_for(scope="project")
        request = request_for({"contracts.view", "projects.view"}, data={"scope_type": "contract", "scope_id": str(contract_id)})
        with patch.object(views_workboard, "require_tenant_context", return_value="tenant-test"), patch.object(views_workboard, "authorize_scope_read", return_value=True), patch.object(entity_access, "authorize_scope_read", side_effect=lambda request, alias, scope, scope_id: scope == "contract"), patch.object(views_workboard, "authorize_scope_write", return_value=False), patch.object(ProcessEvent, "objects") as manager, patch.object(views_workboard, "_attachment_map", return_value={}) as attachments, patch.object(views_workboard, "_project_name_map", return_value={}), patch.object(views_workboard, "_event_payload", side_effect=lambda event, **kwargs: {"id": str(event.id)}):
            manager.using.return_value.filter.return_value.exclude.return_value.order_by.return_value = [ordinary, finance, other_project]
            body = json.loads(views_workboard.workboard_event_list(request).content)
            self.assertEqual([row["id"] for row in body["events"]], [str(ordinary.id)])
            attachments.assert_called_once_with("tenant-test", [ordinary])
            request._gf_perms_cache.add("finance.view")
            body = json.loads(views_workboard.workboard_event_list(request).content)
            self.assertEqual([row["id"] for row in body["events"]], [str(ordinary.id), str(finance.id)])
            self.assertFalse(body["events"][1]["can_write"])

    def test_calendar_hides_finance_even_when_contract_can_be_read(self):
        events = [event_for(), event_for(finance=True)]
        for event in events:
            event.payload = {"display": {"calendar_enabled": True}}
        with patch.object(views_calendar, "require_tenant_context", return_value="tenant-test"), patch.object(ProcessEvent, "objects") as manager, patch.object(entity_access, "authorize_scope_read", return_value=True), patch.object(views_calendar, "reverse", return_value="/contract/"):
            manager.using.return_value.exclude.return_value.order_by.return_value.__getitem__.return_value = events
            body = json.loads(views_calendar.calendar_events(request_for({"contracts.view"})).content)
        self.assertEqual([row["id"] for row in body], [str(events[0].id)])

    def test_active_badges_do_not_leak_finance_labels(self):
        contract_id = uuid4()
        finance = event_for(finance=True, scope_id=contract_id)
        finance.contract_id = contract_id
        finance.payload = {"display": {"highlight_enabled": True, "until_closed": True}}
        with patch("geoflow_ops.services.active_event_badges._process_events_ready", return_value=True), patch("geoflow_ops.services.active_event_badges.Project.objects") as projects, patch.object(ProcessEvent, "objects") as manager, patch("geoflow_ops.services.active_event_badges._highlight_active", return_value=True), patch.object(entity_access, "authorize_scope_read", return_value=True):
            projects.using.return_value.filter.return_value.values_list.return_value = []
            manager.using.return_value.filter.return_value.exclude.return_value.only.return_value.order_by.return_value = [finance]
            for request in (None, request_for({"contracts.view"})):
                self.assertEqual(active_event_labels_for_contracts("tenant-test", [contract_id], request=request)[str(contract_id)], [])
            self.assertTrue(active_event_labels_for_contracts("tenant-test", [contract_id], request=request_for({"finance.view"}))[str(contract_id)])

    def test_finance_badge_filter_does_not_change_workflow_state(self):
        contract = SimpleNamespace(id=uuid4())
        cursor = MagicMock()
        cursor.fetchall.return_value = [(str(contract.id), "kickoff", "kickoff_approved", date(2026, 10, 13), {}), (str(contract.id), "settlement", "advance_payment", date(2026, 10, 13), {})]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch("geoflow_ops.services.workflow_state._process_event_summary_schema_ready", return_value=True), patch("geoflow_ops.services.workflow_state.connections", {"tenant-test": connection}), patch("geoflow_ops.services.workflow_state._event_highlight_active", return_value=True):
            hidden = contract_workflow_summaries("tenant-test", [contract], request=request_for({"contracts.view"}))[str(contract.id)]
            visible = contract_workflow_summaries("tenant-test", [contract], request=request_for({"finance.view"}))[str(contract.id)]
        self.assertEqual(hidden["stage"], "execution")
        self.assertEqual(visible["stage"], hidden["stage"])
        self.assertEqual(len(visible["active_event_labels"]), len(hidden["active_event_labels"]) + 1)

    def test_finance_helpers_have_no_contract_permission_fallback(self):
        root = Path(__file__).resolve().parent
        for path in list(root.glob("finance_*.py")) + [root / "views_finance.py"]:
            with self.subTest(path=path.name):
                source = path.read_text()
                for code in ("contracts.view", "contracts.edit", "contracts.create"):
                    self.assertNotIn(code, source)
