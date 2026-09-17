"""Read-only production smoke for the central QGIS project runtime."""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis import central_definitions, layer_plan


class Command(BaseCommand):
    help = "Verify tenant project discovery and Final Layer Plans without writing"

    def handle(self, *args, **options):
        definition = central_definitions.central_snapshot()
        if definition is None:
            raise CommandError("qgis_runtime_central_definition=unavailable")

        configs = list(
            GroupDBConfig.objects.using("default")
            .filter(group__status="active")
            .exclude(db_alias="default")
            .order_by("group_id")
        )
        if not configs:
            raise CommandError("qgis_runtime_tenants=missing")

        tenant_count = 0
        discovered_projects = 0
        enabled_projects = 0
        resolved_plans = 0
        openable_projects = 0

        for config in configs:
            with tenant_cursor(config.group_id, write=False) as cursor:
                cursor.execute(
                    "SELECT to_regclass('prj.scope_item'),to_regclass('prj.projects')"
                )
                relations = cursor.fetchone()
                if not relations or not all(relations):
                    continue
                tenant_count += 1

                scopes_by_project = defaultdict(list)
                for project_id, lv2, lv3, lv4 in layer_plan._scope_rows(cursor):
                    scopes_by_project[project_id].append(
                        {"2": lv2, "3": lv3, "4": lv4}
                    )
                discovered_projects += len(scopes_by_project)

                for project_id, scopes in scopes_by_project.items():
                    config_row = central_definitions.project_config(cursor, project_id)
                    layer_ids = layer_plan._resolved_layer_ids(
                        definition, scopes, config_row
                    )
                    layers = [
                        row
                        for row in definition["layers"]
                        if row["id"] in layer_ids and row["active"]
                    ]
                    if not layers:
                        continue
                    enabled_projects += 1
                    final_form = central_definitions.resolve(
                        definition, config_row, layers
                    )
                    if (
                        final_form.get("version") != "gis-final-form-v3"
                        or not final_form.get("revision")
                    ):
                        raise CommandError("qgis_runtime_final_form=invalid")
                    resolved_plans += 1

                    cursor.execute(
                        "SELECT 1 FROM prj.projects WHERE id=%s LIMIT 1",
                        [project_id],
                    )
                    if not cursor.fetchone():
                        continue
                    physical = 0
                    for layer in layers:
                        cursor.execute(
                            "SELECT to_regclass(%s)",
                            ["gis." + layer["physical_name"]],
                        )
                        physical += int(cursor.fetchone()[0] is not None)
                    if physical:
                        openable_projects += 1

        if tenant_count < 1:
            raise CommandError("qgis_runtime_tenant_schema=unavailable")
        if discovered_projects < 1:
            raise CommandError("qgis_runtime_project_discovery=empty")
        if enabled_projects < 1 or resolved_plans != enabled_projects:
            raise CommandError("qgis_runtime_final_layer_plan=unavailable")
        if openable_projects < 1:
            raise CommandError("qgis_runtime_project_open=unavailable")

        self.stdout.write("qgis_runtime_login_route=ok")
        self.stdout.write(f"qgis_runtime_tenants={tenant_count}")
        self.stdout.write(f"qgis_runtime_projects_discovered={discovered_projects}")
        self.stdout.write(f"qgis_runtime_projects_enabled={enabled_projects}")
        self.stdout.write(f"qgis_runtime_final_layer_plans={resolved_plans}")
        self.stdout.write(f"qgis_runtime_projects_openable={openable_projects}")
        self.stdout.write("RESULT qgis_project_runtime_smoke=SUCCESS")
