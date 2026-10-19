"""Exercise the shared ORM ordering against an isolated in-memory database."""
import unittest
from django.db.utils import ConnectionHandler
from geoflow_ops.models import ProcessEvent
from geoflow_ops.views_events import EVENT_TIMELINE_ORDER


class EventTimelineOrderTests(unittest.TestCase):
    def test_dates_creation_contract_tie_id_and_edit_stability(self):
        connection = ConnectionHandler({'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}})['default']
        try:
            with connection.cursor() as cursor:
                cursor.execute("ATTACH DATABASE ':memory:' AS ops")
                cursor.execute('CREATE TABLE ops.process_events (id text, occurred_at date, created_at datetime, updated_at datetime, scope_type text)')
                rows = [
                    ('4', '2026-01-23', '2026-01-23 09:00:00', '', 'project'),
                    ('1', '2026-01-22', '2026-01-25 09:00:00', '', 'contract'),
                    ('3', '2026-01-23', '2026-01-23 09:00:00', '', 'contract'),
                    ('2', '2026-01-23', '2026-01-23 08:00:00', '', 'project'),
                    ('5', '2026-01-23', '2026-01-23 09:00:00', '', 'project'),
                    ('6', None, '2026-01-24 09:00:00', '', 'project'),
                ]
                cursor.executemany('INSERT INTO ops.process_events VALUES (%s,%s,%s,%s,%s)', rows)
                query = ProcessEvent.objects.order_by(*EVENT_TIMELINE_ORDER).values_list('id').query
                sql, params = query.get_compiler(connection=connection).as_sql()
                cursor.execute(sql, params)
                self.assertEqual([r[0] for r in cursor.fetchall()], ['1','2','3','4','5','6'])
                cursor.execute("UPDATE ops.process_events SET updated_at='2026-02-01 12:00:00' WHERE id='2'")
                cursor.execute(sql, params)
                self.assertEqual([r[0] for r in cursor.fetchall()], ['1','2','3','4','5','6'])
        finally:
            connection.close()


class EventAttachmentDeleteTests(unittest.TestCase):
    def test_delete_authorizes_actual_owner_and_only_soft_deletes_attachment(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from django.test import RequestFactory
        from geoflow_ops.views_uploads import delete_attachment
        from uuid import uuid4
        attachment = SimpleNamespace(id=uuid4(), entity_type='event', entity_id=uuid4(), deleted_at=None, is_deleted=False, active=True, save=Mock())
        request = RequestFactory().delete('/api/uploads/delete/')
        request.user = SimpleNamespace(is_authenticated=True, username='tester')
        request.session = {}
        with patch('geoflow_ops.views_uploads.require_tenant_context', return_value='isolated'), patch('geoflow_ops.views_uploads.Attachment') as model, patch('geoflow_ops.views_uploads.authorize_attachment_write') as authorize:
            model.objects.using.return_value.filter.return_value.first.return_value = attachment
            authorize.return_value = False
            self.assertEqual(delete_attachment(request, attachment.id).status_code, 403)
            attachment.save.assert_not_called()
            authorize.assert_called_with(request, 'isolated', 'event', attachment.entity_id, attachment=attachment)
            authorize.return_value = True
            self.assertEqual(delete_attachment(request, attachment.id).status_code, 200)
            self.assertTrue(attachment.is_deleted)
            self.assertFalse(attachment.active)
            self.assertIsNotNone(attachment.deleted_at)
            attachment.save.assert_called_once()
