"""Read-only production smoke test for the central GIS definition page."""

from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.test import RequestFactory

from control import views_gis_admin
from control.services import gis_definitions


TAB_LABELS = (
    "그룹 구성",
    "표준 레이어/필드",
    "추가 필드",
    "참조코드",
    "연결 규칙",
)
STANDARD_TABLE_MARKERS = (
    'id="standard-field-search"',
    'id="standard-kind-filter"',
    'id="standard-widget-filter"',
    'id="standard-visible-filter"',
    'id="standard-required-filter"',
    'id="standard-readonly-filter"',
    'id="standard-field-table"',
)


class Command(BaseCommand):
    help = "Render the central GIS definition GET view against the configured DB without writing"

    def add_arguments(self, parser):
        parser.add_argument("--minimum-layers", type=int, default=19)
        parser.add_argument("--minimum-fields", type=int, default=451)
        parser.add_argument("--minimum-codes", type=int, default=111)

    def handle(self, *args, **options):
        with connections["default"].cursor() as cursor:
            if not gis_definitions.ready(cursor):
                raise CommandError("gis_definition_admin_ready=no")
            try:
                payload = gis_definitions.snapshot(cursor)
            except Exception as exc:
                raise CommandError(
                    "gis_definition_admin_snapshot_query=failed"
                ) from exc

        actual = {
            "layers": len(payload["layers"]),
            "fields": len(payload["fields"]),
            "codes": len(payload["codes"]),
        }
        minimums = {
            "layers": options["minimum_layers"],
            "fields": options["minimum_fields"],
            "codes": options["minimum_codes"],
        }
        for name, minimum in minimums.items():
            if actual[name] < minimum:
                raise CommandError(
                    f"gis_definition_admin_{name}=unexpected:{actual[name]}<{minimum}"
                )

        request = RequestFactory().get("/control/central/gis/definitions/")
        request.user = AnonymousUser()
        request.session = {}
        # Bypass only the central-admin identity wrapper. The method wrapper,
        # real GET view, DB query, template and context remain in the smoke.
        response = views_gis_admin.dashboard.__wrapped__(request)
        if response.status_code != 200:
            raise CommandError(
                f"gis_definition_admin_get_status={response.status_code}"
            )
        html = response.content.decode("utf-8")
        if 'id="gis-data"' not in html or "중앙 업무정의를 준비 중입니다." in html:
            raise CommandError("gis_definition_admin_ready_context=no")
        if any(label not in html for label in TAB_LABELS):
            raise CommandError("gis_definition_admin_tabs=missing")
        if any(marker not in html for marker in STANDARD_TABLE_MARKERS):
            raise CommandError("gis_definition_admin_standard_field_table=missing")

        self.stdout.write("gis_definition_admin_get_status=200")
        self.stdout.write("gis_definition_admin_ready=yes")
        self.stdout.write(f"gis_definition_admin_layers={actual['layers']}")
        self.stdout.write(f"gis_definition_admin_fields={actual['fields']}")
        self.stdout.write(f"gis_definition_admin_reference_codes={actual['codes']}")
        self.stdout.write("gis_definition_admin_tabs=ok")
        self.stdout.write("gis_definition_admin_standard_field_table=ok")
        self.stdout.write("gis_definition_admin_snapshot_query=ok")
"""Read-only production smoke test for the central GIS definition page."""

from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.test import RequestFactory

from control import views_gis_admin
from control.services import gis_definitions


TAB_LABELS = (
    "그룹 구성",
    "표준 레이어/필드",
    "추가 필드",
    "참조코드",
    "연결 규칙",
)


class Command(BaseCommand):
    help = "Render the central GIS definition GET view against the configured DB without writing"

    def add_arguments(self, parser):
        parser.add_argument("--minimum-layers", type=int, default=19)
        parser.add_argument("--minimum-fields", type=int, default=451)
        parser.add_argument("--minimum-codes", type=int, default=111)

    def handle(self, *args, **options):
        with connections["default"].cursor() as cursor:
            if not gis_definitions.ready(cursor):
                raise CommandError("gis_definition_admin_ready=no")
            try:
                payload = gis_definitions.snapshot(cursor)
            except Exception as exc:
                raise CommandError(
                    "gis_definition_admin_snapshot_query=failed"
                ) from exc

        actual = {
            "layers": len(payload["layers"]),
            "fields": len(payload["fields"]),
            "codes": len(payload["codes"]),
        }
        minimums = {
            "layers": options["minimum_layers"],
            "fields": options["minimum_fields"],
            "codes": options["minimum_codes"],
        }
        for name, minimum in minimums.items():
            if actual[name] < minimum:
                raise CommandError(
                    f"gis_definition_admin_{name}=unexpected:{actual[name]}<{minimum}"
                )

        request = RequestFactory().get("/control/central/gis/definitions/")
        request.user = AnonymousUser()
        request.session = {}
        # Bypass only the central-admin identity wrapper. The method wrapper,
        # real GET view, DB query, template and context remain in the smoke.
        response = views_gis_admin.dashboard.__wrapped__(request)
        if response.status_code != 200:
            raise CommandError(
                f"gis_definition_admin_get_status={response.status_code}"
            )
        html = response.content.decode("utf-8")
        if 'id="gis-data"' not in html or "중앙 업무정의를 준비 중입니다." in html:
            raise CommandError("gis_definition_admin_ready_context=no")
        if any(label not in html for label in TAB_LABELS):
            raise CommandError("gis_definition_admin_tabs=missing")

        self.stdout.write("gis_definition_admin_get_status=200")
        self.stdout.write("gis_definition_admin_ready=yes")
        self.stdout.write(f"gis_definition_admin_layers={actual['layers']}")
        self.stdout.write(f"gis_definition_admin_fields={actual['fields']}")
        self.stdout.write(f"gis_definition_admin_reference_codes={actual['codes']}")
        self.stdout.write("gis_definition_admin_tabs=ok")
        self.stdout.write("gis_definition_admin_snapshot_query=ok")
