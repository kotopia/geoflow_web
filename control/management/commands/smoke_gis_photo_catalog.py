"""Exercise the real photo-catalog API and roll every production write back."""
import json
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.test import RequestFactory

from control import views_gis_photo


class Command(BaseCommand):
    help = "Create, update, reload and deactivate photo definitions in a rollback transaction"

    def handle(self, *args, **options):
        factory = RequestFactory()

        def api(method="GET", payload=None):
            request = factory.generic(
                method,
                "/control/central/gis/photo-catalog/api/",
                data=json.dumps(payload) if payload is not None else None,
                content_type="application/json",
                HTTP_ACCEPT="application/json",
            )
            request.user = AnonymousUser()
            request.session = {}
            response = views_gis_photo.catalog_api.__wrapped__(request)
            body = json.loads(response.content)
            if response.status_code != 200 or not body.get("ok"):
                raise CommandError(
                    f"gis_photo_catalog_api=failed status={response.status_code} "
                    f"error={body.get('error', 'unknown')}"
                )
            return body

        marker = uuid4().hex[:12].upper()
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cursor:
                cursor.execute("""SELECT lc.catalog_item_id::text,lc.layer_id::text,
                    p.id::text,p.lv3_id::text
                    FROM gis.definition_layer_catalog lc
                    JOIN gis.definition_layer l ON l.id=lc.layer_id AND l.active
                    LEFT JOIN LATERAL (
                      SELECT id,lv3_id FROM gis.photo_policy
                      WHERE active AND lv2_id=lc.catalog_item_id AND layer_id=lc.layer_id
                      ORDER BY (lv3_id IS NULL) DESC,id LIMIT 1
                    ) p ON true
                    WHERE lc.catalog_level=2 ORDER BY l.sort_order,l.id LIMIT 1""")
                target = cursor.fetchone()
            if not target:
                raise CommandError("gis_photo_catalog_target=missing")
            lv2_id, layer_id, existing_policy_id, lv3_id = target

            template = api("POST", {
                "action": "save", "kind": "template", "code": f"SMOKE_{marker}",
                "name": "사진 저장 검사", "description": "rollback smoke",
                "capture_mode": "GENERAL", "sort_order": 987654,
            })
            template_id = template["id"]
            slot = api("POST", {
                "action": "save", "kind": "slot", "template_id": template_id,
                "code": f"SLOT_{marker}", "name": "사진 항목 저장 검사",
                "description": "rollback smoke", "min_count": 1, "max_count": 2,
                "sort_order": 987654,
                "extra_schema": {"fields": [{"key": "PIPE_COUNT", "label": "관로 수",
                                                "kind": "integer", "required": True}]},
            })
            slot_id = slot["id"]
            policy_payload = {
                "action": "save", "kind": "policy", "lv2_id": lv2_id,
                "lv3_id": lv3_id, "layer_id": layer_id,
                "default_capture_mode": "GENERAL", "direct_template_id": None,
                "indirect_template_id": None, "general_template_id": template_id,
                "allow_extra_photo": True, "sort_order": 987654,
                "description": "rollback smoke",
            }
            if existing_policy_id:
                policy_payload["id"] = existing_policy_id
            policy_id = api("POST", policy_payload)["id"]

            api("POST", {
                "action": "save", "kind": "template", "id": template_id,
                "code": f"SMOKE_{marker}", "name": "사진 저장 검사 수정",
                "description": "rollback smoke updated", "capture_mode": "GENERAL",
                "sort_order": 987655,
            })
            refreshed = api()
            saved_template = next(x for x in refreshed["templates"] if x["id"] == template_id)
            saved_slot = next(x for x in refreshed["slots"] if x["id"] == slot_id)
            saved_policy = next(x for x in refreshed["policies"] if x["id"] == policy_id)
            if saved_template["name"] != "사진 저장 검사 수정":
                raise CommandError("gis_photo_template_save_refresh=no")
            if saved_slot["extra_schema"]["fields"][0]["key"] != "PIPE_COUNT":
                raise CommandError("gis_photo_slot_save_refresh=no")
            if saved_policy["general_template_id"] != template_id:
                raise CommandError("gis_photo_policy_save_refresh=no")

            api("POST", {"action": "deactivate", "kind": "policy", "id": policy_id})
            api("POST", {"action": "deactivate", "kind": "slot", "id": slot_id})
            api("POST", {"action": "deactivate", "kind": "template", "id": template_id})
            inactive = api()
            for collection, item_id in (("templates", template_id), ("slots", slot_id),
                                        ("policies", policy_id)):
                if next(x for x in inactive[collection] if x["id"] == item_id)["active"]:
                    raise CommandError(f"gis_photo_{collection}_soft_delete=no")
            transaction.set_rollback(True, using="default")

        self.stdout.write("gis_photo_template_crud_refresh=ok")
        self.stdout.write("gis_photo_slot_crud_refresh=ok")
        self.stdout.write("gis_photo_policy_crud_refresh=ok")
        self.stdout.write("gis_photo_catalog_smoke_rollback=yes")
