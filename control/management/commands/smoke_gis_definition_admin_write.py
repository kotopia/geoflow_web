"""Transactional production smoke for standard-field authoring through the real view."""
import html
import json
import re

from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.test import RequestFactory

from control import views_gis_admin


DATA_PATTERN = re.compile(
    r'<script id="gis-data" type="application/json">(.*?)</script>', re.DOTALL
)


def response_data(response):
    match = DATA_PATTERN.search(response.content.decode("utf-8"))
    if not match:
        raise CommandError("gis_definition_admin_refresh_payload=missing")
    return json.loads(html.unescape(match.group(1)))


class Command(BaseCommand):
    help = "Exercise standard-field POST and refreshed GET while rolling all values back"

    def handle(self, *args, **options):
        factory = RequestFactory()
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cursor:
                cursor.execute("""SELECT id::text,label,kind,widget_type,visible,required,readonly,sort_order,layout
                    FROM gis.definition_field WHERE source_layer_id IS NOT NULL
                    ORDER BY sort_order,id LIMIT 1""")
                row = cursor.fetchone()
            if not row:
                raise CommandError("gis_definition_admin_write_target=missing")
            keys = ("id", "label", "kind", "widget_type", "visible", "required", "readonly", "sort_order", "layout")
            original = dict(zip(keys, row))
            current = dict(original)
            candidates = {
                "label": (original["label"][:105] + " [저장검사]"),
                "widget_type": "multiline" if original["widget_type"] == "text" else "text",
                "visible": not original["visible"],
                "required": not original["required"],
                "readonly": not original["readonly"],
                "sort_order": original["sort_order"] + 1,
            }

            for changed_key, changed_value in candidates.items():
                current[changed_key] = changed_value
                post = {
                    "action": "standard_field",
                    "id": current["id"],
                    "label": current["label"],
                    "kind": current["kind"],
                    "widget_type": current["widget_type"],
                    "visible": str(current["visible"]).lower(),
                    "required": str(current["required"]).lower(),
                    "readonly": str(current["readonly"]).lower(),
                    "sort_order": str(current["sort_order"]),
                }
                request = factory.post("/control/central/gis/definitions/", post)
                request.user = AnonymousUser()
                request.session = {}
                response = views_gis_admin.dashboard.__wrapped__(request)
                if response.status_code != 200 or not json.loads(response.content)["ok"]:
                    raise CommandError(f"gis_definition_admin_{changed_key}_save=failed")

                refreshed = factory.get("/control/central/gis/definitions/")
                refreshed.user = AnonymousUser()
                refreshed.session = {}
                refreshed_response = views_gis_admin.dashboard.__wrapped__(refreshed)
                if refreshed_response.status_code != 200:
                    raise CommandError(f"gis_definition_admin_{changed_key}_refresh=failed")
                saved = next(
                    field for field in response_data(refreshed_response)["fields"]
                    if field["id"] == current["id"]
                )
                if saved[changed_key] != changed_value:
                    raise CommandError(f"gis_definition_admin_{changed_key}_persisted=no")
                if saved["layout"] != original["layout"]:
                    raise CommandError("gis_definition_admin_layout_preserved=no")
                self.stdout.write(f"gis_definition_admin_{changed_key}_save_refresh=ok")

            transaction.set_rollback(True, using="default")

        self.stdout.write("gis_definition_admin_layout_preserved=yes")
        self.stdout.write("gis_definition_admin_write_smoke_rollback=yes")
