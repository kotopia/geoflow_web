from django.urls import path

from . import (
    qfield_device_views,
    qfield_package_views,
    qfield_sync_views,
    qfield_views,
    qgis_views,
    realtime_ticket_views,
    realtime_views,
    sync_views,
    views,
)

app_name = "gis"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("projects/<uuid:project_id>/", views.project_dashboard, name="project_dashboard"),
    path(
        "projects/<uuid:project_id>/api/layer-plan/",
        views.project_layer_plan_api,
        name="project_layer_plan_api",
    ),
    path(
        "projects/<uuid:project_id>/api/geojson/",
        views.project_layer_geojson_api,
        name="project_layer_geojson_api",
    ),
    path(
        "projects/<uuid:project_id>/api/features/",
        realtime_views.project_feature_batch_api,
        name="project_feature_batch_api",
    ),
    path(
        "projects/<uuid:project_id>/api/changesets/",
        sync_views.project_changeset_api,
        name="project_changeset_api",
    ),
    path(
        "projects/<uuid:project_id>/api/delta/",
        sync_views.project_delta_api,
        name="project_delta_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/bootstrap/",
        qfield_device_views.qfield_bootstrap_api,
        name="qfield_bootstrap_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/package/",
        qfield_package_views.qfield_package_api,
        name="qfield_package_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/package-import/",
        qfield_package_views.qfield_package_import_api,
        name="qfield_package_import_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/roaming-plan/",
        qfield_views.qfield_roaming_plan_api,
        name="qfield_roaming_plan_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/roaming-cell/",
        qfield_views.qfield_roaming_cell_api,
        name="qfield_roaming_cell_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/delta/",
        qfield_device_views.qfield_device_delta_api,
        name="qfield_device_delta_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qfield/changesets/",
        qfield_sync_views.qfield_device_changeset_api,
        name="qfield_device_changeset_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qgis-manifest/",
        qgis_views.qgis_project_manifest_api,
        name="qgis_project_manifest_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qgis-package/",
        qgis_views.qgis_project_package_api,
        name="qgis_project_package_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qgis-realtime-ticket/",
        realtime_ticket_views.qgis_project_realtime_ticket_api,
        name="qgis_project_realtime_ticket_api",
    ),
    path(
        "projects/<uuid:project_id>/api/qgis-sync/",
        qgis_views.qgis_project_sync_api,
        name="qgis_project_sync_api",
    ),
    path("api/qgis/projects/", qgis_views.qgis_projects_api, name="qgis_projects_api"),
    path("api/layers/", views.layer_registry_api, name="layer_registry_api"),
]
