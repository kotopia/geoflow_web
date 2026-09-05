from django.urls import path

from . import qgis_views, sync_views, views

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
        "projects/<uuid:project_id>/api/qgis-sync/",
        qgis_views.qgis_project_sync_api,
        name="qgis_project_sync_api",
    ),
    path("api/qgis/projects/", qgis_views.qgis_projects_api, name="qgis_projects_api"),
    path("api/layers/", views.layer_registry_api, name="layer_registry_api"),
]
