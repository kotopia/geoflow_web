"""Read-only production smoke for the central QGIS project runtime."""

from collections import defaultdict
import json

from django.core.management.base import BaseCommand, CommandError

from control.models import GroupDBConfig
from control.management.commands.smoke_gis_survey_source_upload import _tenant_alias
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis import central_definitions, layer_plan
from geoflow_ops.gis.reference_views import _catalog_response
from geoflow_ops.gis.survey_sources import list_survey_sources, survey_source_delete_precheck


def verify_survey_inspection(alias, project_id, plan):
    """Exercise the deployed read/serialization contract without a DELETE."""
    payload = json.loads(_catalog_response(alias, plan).content)
    expected = {str(row['catalog_item_id']) for row in plan.get('capabilities', [])
                if row.get('catalog_level') == 2}
    actual = {row['code'] for row in payload['business_types']}
    # Inactive central items can be omitted, but unrelated scope must never leak.
    if not actual.issubset(expected) or (expected and not actual):
        raise CommandError('survey_inspection_l2_scope=invalid')
    sources = list_survey_sources(alias, project_id=str(project_id),
                                  include_inactive=True, include_deleted=True)
    for source in sources:
        if source.get('deleted_at'):
            continue
        precheck = survey_source_delete_precheck(alias, project_id=str(project_id),
                                                source_id=source['id'])
        if precheck.get('deletion_policy') != 'source_and_points_soft_delete_v1':
            raise CommandError('survey_inspection_delete_contract=invalid')
        if precheck.get('point_count') != source['point_count']:
            raise CommandError('survey_inspection_source_count=mismatch')
    return len(sources), sum(row['point_count'] for row in sources), len(actual)


class Command(BaseCommand):
    help = "Verify tenant project discovery and Final Layer Plans without writing"

    def add_arguments(self, parser):
        parser.add_argument('--survey-inspection', action='store_true')

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
        inspection_projects = inspection_sources = inspection_points = inspection_l2 = 0

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
                    if options.get('survey_inspection'):
                        cursor.execute("SELECT to_regclass('gis.survey_source'),to_regclass('gis.survey')")
                        if all(cursor.fetchone()):
                            with _tenant_alias(config) as alias:
                                plan = layer_plan.project_layer_plan(alias, project_id)
                                sources, points, l2 = verify_survey_inspection(alias, project_id, plan)
                            inspection_projects += 1
                            inspection_sources += sources
                            inspection_points += points
                            inspection_l2 += l2

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
        if options.get('survey_inspection'):
            if not inspection_projects:
                raise CommandError('survey_inspection_projects=missing')
            self.stdout.write(f'survey_inspection_projects={inspection_projects}')
            self.stdout.write(f'survey_inspection_sources_including_deleted={inspection_sources}')
            self.stdout.write(f'survey_inspection_active_points={inspection_points}')
            self.stdout.write(f'survey_inspection_scoped_l2={inspection_l2}')
            self.stdout.write('RESULT survey_inspection_readonly=SUCCESS')
        self.stdout.write("RESULT qgis_project_runtime_smoke=SUCCESS")
